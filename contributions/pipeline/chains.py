"""PAC funding-chain tracing — layer 5, runs after sponsors.py.

Most large PA PACs are *non-connected* — no corporate sponsor by design, so
"who sponsors it" (sponsors.py) is the wrong question. The right question is
who funds it, and those PACs are themselves recipients elsewhere in this
dataset. This module joins each PAC's own receipts back to itself, calls a
dominant funder (>=50% of receipts) a directed edge, and walks the resulting
graph to its origin.

Money moving JEFFREY YASS -> STUDENTS FIRST PAC -> COMMONWEALTH CHILDREN'S
CHOICE FUND -> COMMONWEALTH LEADERS FUND -> a candidate is invisible to any
single-hop view, which would report Commonwealth Leaders Fund itself as a
$16M+ donor with no visible owner. This is the layer that unwinds it.

Input: pac_sponsors.parquet (recipient-level PAC totals, from sponsors.py) plus
the same receipt-level table sponsors.py builds — recomputed here rather than
re-imported so this script also runs standalone against any receipts table
shaped {recipient_key, recipient_name, donor_name_raw, donor_class, amount}.

Output: pac_funding_sources.csv, ultimate_sources.csv, both in ~/pafin/out/.
"""
import os
import numpy as np, pandas as pd
from classify import norm
import sponsors as sp

OUT = sp.OUT
DOMINANCE = 0.50   # a funder must supply at least this share of a PAC's receipts
                   # to become a chain edge — a PAC funded 45/45/10 by three
                   # sources has no dominant funder and reads as its own origin.
MAX_HOPS = 6       # circular PAC-to-PAC transfers break at the first repeat,
                   # not by exhausting this cap; it is a backstop, not the
                   # expected chain length (the deepest verified real chain is 5).


def build_receipts():
    cm = sp.fec_seed()
    r = pd.concat([sp.pac_receipts_from_unified(), sp.pac_receipts_from_fec_oth(cm)],
                  ignore_index=True)
    return r[r.donor_name_raw.str.len() > 0]


def dominant_funders(receipts, pac_keys):
    """{recipient_key: (funder_name, funder_key_or_None, share)} for every PAC
    whose top donor clears DOMINANCE. funder_key is set only when the funder is
    itself one of the PACs in this dataset (i.e. the edge can be walked further);
    otherwise the funder is a terminal individual/org and funder_key is None."""
    by_pac = (receipts.groupby(["recipient_key", "donor_name_raw"], as_index=False)
                       .amount.sum())
    totals = by_pac.groupby("recipient_key").amount.sum()
    by_pac["share"] = by_pac.amount / by_pac.recipient_key.map(totals)
    top = (by_pac.sort_values("amount", ascending=False)
                 .drop_duplicates("recipient_key"))
    top = top[top.share >= DOMINANCE]

    # Is the dominant funder itself a PAC we're tracking? Match on normalized
    # name against every other tracked PAC's own recipient_name — this is a
    # name join, not an ID join, because a PAC appears as a *donor* row with only
    # a raw name string, never its own recipient_key.
    name_to_key = {}
    for key, name in pac_keys.items():
        name_to_key.setdefault(norm(name), key)

    out = {}
    for _, row in top.iterrows():
        fk = name_to_key.get(norm(row.donor_name_raw))
        if fk == row.recipient_key:
            fk = None   # never a self-loop
        out[row.recipient_key] = (row.donor_name_raw, fk, float(row.share))
    return out


def walk_chains(edges, pac_names):
    """Walk every PAC back to its origin. Returns one row per PAC that has a
    funding edge at all, with the full hop-by-hop path and the terminal source."""
    rows = []
    for start in edges:
        path = [start]
        seen = {start}
        cur = start
        cycle = False
        stalled = False  # walked onto a tracked PAC that has no dominant funder
                          # of its own — it IS the origin, not a break in the data
        while True:
            if cur not in edges:
                stalled = True
                break
            funder_name, funder_key, share = edges[cur]
            path.append(funder_key or f"[terminal] {funder_name}")
            if funder_key is None:
                break
            if funder_key in seen:
                cycle = True
                break
            if len(path) - 1 >= MAX_HOPS:
                break
            seen.add(funder_key)
            cur = funder_key
        origin_name, origin_key, origin_share = edges[start]
        # walk to the actual terminal node's name/share, not just the first hop
        terminal_key = cur
        if stalled:
            terminal_name = pac_names.get(terminal_key, terminal_key)
        else:
            terminal_name = (edges[terminal_key][0] if edges[terminal_key][1] is None
                              else pac_names.get(terminal_key, edges[terminal_key][0]))
        rows.append({
            "pac_key": start, "pac_name": pac_names.get(start, start),
            "hops": len(path) - 1,
            "immediate_funder": origin_name, "immediate_funder_share": origin_share,
            "ultimate_source": terminal_name,
            "path": " -> ".join(pac_names.get(p, p) if p in pac_names else p for p in path),
            "broke_on_cycle": cycle,
        })
    return pd.DataFrame(rows)


def main():
    receipts = build_receipts()
    pac_names = (receipts.drop_duplicates("recipient_key")
                          .set_index("recipient_key").recipient_name.to_dict())
    print(f"tracing funding chains for {len(pac_names):,} recipient committees")

    edges = dominant_funders(receipts, pac_names)
    print(f"PACs with a dominant funder (>= {DOMINANCE:.0%} of receipts): {len(edges):,}")

    chains = walk_chains(edges, pac_names)
    if chains.empty:
        print("no chains found — nothing to write")
        return chains, pd.DataFrame()

    with_chain = chains[chains.hops > 0]
    print(f"chains longer than one hop: {len(with_chain[with_chain.hops > 1]):,}")
    if chains.broke_on_cycle.any():
        print(f"chains that hit a cycle and were cut: {int(chains.broke_on_cycle.sum())}")

    # pac_funding_sources.csv — per-PAC view, top funders + share
    by_pac = (receipts.groupby(["recipient_key", "donor_name_raw"], as_index=False)
                       .amount.sum())
    totals = by_pac.groupby("recipient_key").amount.sum().rename("pac_total")
    by_pac = by_pac.merge(totals, on="recipient_key")
    by_pac["share"] = (by_pac.amount / by_pac.pac_total).round(4)
    top5 = (by_pac.sort_values(["recipient_key", "amount"], ascending=[True, False])
                  .groupby("recipient_key").head(5))
    top5["pac_name"] = top5.recipient_key.map(pac_names)
    top5 = top5[["recipient_key", "pac_name", "donor_name_raw", "amount", "share"]]
    top5.columns = ["pac_key", "pac_name", "funder", "amount", "share"]

    # ultimate_sources.csv — money rolled up to the origin of each chain
    terminal_only = chains[~chains.broke_on_cycle].copy()
    ult = (terminal_only.groupby("ultimate_source", as_index=False)
                        .agg(total_traced=("immediate_funder_share", "count"),
                             pacs_in_chain=("pac_key", "nunique")))
    # dollars: sum each chain's starting PAC total, attributed to its ultimate source
    pac_totals = receipts.groupby("recipient_key").amount.sum()
    terminal_only["pac_total"] = terminal_only.pac_key.map(pac_totals)
    ult_dollars = (terminal_only.groupby("ultimate_source", as_index=False)
                                .pac_total.sum().rename(columns={"pac_total": "total_dollars"}))
    ult = ult.merge(ult_dollars, on="ultimate_source").sort_values(
        "total_dollars", ascending=False)

    os.makedirs(OUT, exist_ok=True)
    top5.to_csv(f"{OUT}/pac_funding_sources.csv", index=False)
    ult.to_csv(f"{OUT}/ultimate_sources.csv", index=False)
    chains.sort_values("hops", ascending=False).to_csv(
        f"{OUT}/funding_chains_detail.csv", index=False)
    print(ult.head(10).to_string(index=False))
    return top5, ult


if __name__ == "__main__":
    main()
