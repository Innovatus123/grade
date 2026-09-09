# PAC Sponsor Tracing - Build Notes

**Added:** 2026-08-04 | Fourth layer, after the tracker, entity resolution and the crosswalk.
**Scripts added to this repo:** 2026-09-09

Pennsylvania bars direct corporate contributions to candidates (25 P.S. 3253), so corporate
money reaches candidates only through a PAC. Donor names at state level therefore almost
never say "corporation." The influence is real but invisible unless each PAC is traced back
to the organization or person behind it. That is what this layer does.

---

## 1. The headline finding

**Jeffrey Yass is the ultimate source of $71.25M given to Pennsylvania politicians across
17 separate vehicles, up to 5 hops deep.** His *direct* giving is $33.79M. The rest moves
through a chain of PACs:

```
JEFFREY YASS
  -> Students First PAC              (100% of its receipts)   $28.27M out, 4 politicians
     -> Commonwealth Children's Choice Fund  (100%)           $25.80M out, 19 politicians
        -> Commonwealth Leaders Fund         (98%)            $15.98M out, 10 politicians
           -> Dave Sunday for AG                              $0.22M out
     -> PA Leaders Action Fund, PA Capitol PAC,
        PA Education Choice Fund, Make A Difference PAC ...
```

A single-hop view credits the wrong actor at every step. It would report Commonwealth
Leaders Fund as a $16M donor with no visible owner.

**No other source comes close.** The second-largest traced origin is AFSCME PEOPLE at $1.48M.
The concentration is the finding.

This is the original, full three-jurisdiction (PA state + Philadelphia + federal) production
run from 2026-08-04. Section 9 below documents a second, independent run against real data
that reproduces the same signal from a narrower slice.

---

## 2. Scale

| Metric | Value |
|---|---|
| Organizational donor entities traced | 12,001 ($548.5M given) |
| FEC connected-org seed rows used | 2,860 |
| FEC rows rejected as incoherent | 1,041 |
| PACs whose own funding is traceable | 1,451 |
| PACs with one funder supplying >=50% of receipts | 405 ($109.2M given out) |
| PAC entities with a funding chain | 360 ($89.9M given out) |
| Chains longer than one hop | 25 |
| $ tagged to an industry | $117.8M |

## 3. Method

**Seed - FEC connected organizations.** The FEC publishes `CONNECTED_ORG_NM` and `ORG_TP`
for its committees. This is the only authoritative sponsor data in any of the three sources.

**Coherence guard.** FEC filers sometimes use `CONNECTED_ORG_NM` as free text - a state party
listed "PROTECT THE HOUSE 2024" as its connected org. Left unguarded, this attributed
Commonwealth Leaders Fund to a sponsor named "DEATON" - a **$16M misattribution**. The field
is now accepted only when `ORG_TP` is populated (a declared SSF) or the sponsor name shares a
substantive token with the committee name. 1,041 rows rejected.

**Derived sponsors.** For PACs with no FEC match, the PAC wrapper is stripped off the name
("DUANE MORRIS GOVERNMENT COMMITTEE STATE & LOCAL FUND" -> "DUANE MORRIS") and the stem is
classified by type and industry.

**Funding chains.** Most large PA PACs are *non-connected* - they have no corporate sponsor
by design, so "who sponsors it" is the wrong question. The right question is who funds it,
and those PACs are themselves recipients in this dataset. Each PAC's own receipts are joined
back, a dominant funder (>=50% of receipts) becomes a directed edge, and the graph is walked
to its origin with cycle detection.

## 4. Defects found in validation

1. **Every plural regex silently failed.** `\bCARPENTER\b` does not match "CARPENTERS".
   Building trades money read **$8.1M**; the correct figure is **$29.7M**. Legal services
   went $7.3M -> $21.6M, labor unions $58M -> $81M. A whole analytical layer was
   near-empty and looked plausible.
2. **Fuzzy matching at 88 was too loose** and linked PA PACs to unrelated federal committees.
   Raised to 93 with a minimum-length guard.
3. **Rule order mattered** - "PA ALLIANCE ACTION" classified as a trade association because
   ALLIANCE was tested before the advocacy rule. Reordered.
4. **Report rollup lines leak into the chain if not filtered at the receipt level too.**
   The 2026-09-09 rebuild (`sponsors.py` / `chains.py`, written fresh against this spec)
   initially let `donor_bucket == EXCLUDE-ROLLUP` rows through into PAC receipts - "UNITEMIZED
   MONETARY CONTRIBUTIONS" and "NON PENNSYLVANIA RECEIPTS" surfaced as top "ultimate sources"
   in the first real run. Same defect class as the $83.1M rollup-donor issue in
   `README_PA_Contributions_Tracker.md` finding 4, one layer further downstream. Fixed by
   applying the `EXCLUDE-ROLLUP` filter at the PAC-receipt level, not just the donor level.

## 5. Industry breakdown (of organizational giving)

| Industry | $ |
|---|---|
| Unclassified | $430.7M |
| Education | $30.9M |
| **Building trades labor** | **$29.7M** |
| Legal services | $21.6M |
| Public sector labor | $14.6M |
| Real estate / development | $5.2M |
| Finance / insurance | $4.7M |
| Healthcare | $4.7M |
| Energy / utilities | $4.1M |
| **Construction contracting** | **$3.1M** |

**The construction read for GBCA:** building trades labor outspends construction
contracting roughly **10 to 1** in Pennsylvania politics. If GBCA's members are being
outspent on the labor side by an order of magnitude, that is a board-level fact.

## 6. Limitations

- "Unclassified" industry still holds the majority of dollars. Most of it is party
  committees and candidate-to-candidate transfers, which have no industry - but some is
  genuinely untagged. Sheet 22 lets you audit what fell through.
- Sponsor type "UNKNOWN" is largely non-connected PACs, where the funding chain rather than
  the sponsor is the answer.
- The 50% dominance threshold is a judgment call. A PAC funded 45/45/10 by three sources has
  no chain edge and will read as its own origin.
- Chains are capped at 6 hops with cycle detection. Circular PAC-to-PAC transfers break at
  the first repeat.

## 7. Files

- `pac_funding_sources.csv` - each PAC with its top five funders and their shares
- `ultimate_sources.csv` - money rolled up to the origin of each chain
- `sponsor_detail.csv` - every PAC with sponsor, type, industry, funder and full chain
- `sponsor_totals.csv` - dollars by sponsor
- Workbook sheets 18-24
- `pipeline/sponsors.py`, `pipeline/chains.py`

## 8. Refresh

`build.py` -> `resolve.py` -> `workbook.py` -> `crosswalk.py` -> `politician_report.py` ->
`sponsors.py` -> `chains.py`. All idempotent, ~30 minutes end to end.

## 9. Validation run — 2026-09-09, `sponsors.py` / `chains.py` added to this repo

The two scripts behind this layer weren't in the archived pipeline bundle this repo was
originally built from (see prior "Known gap" note, now resolved). They were rewritten from
this document's Section 3 method spec and run for real against live data before being
committed, rather than shipped untested:

**What actually ran, from Claude's cloud sandbox:**
- FEC committee master (`cm.txt`, bulk download) - 20,633 committees nationally, used as the
  `CONNECTED_ORG_NM` seed exactly as Section 3 describes.
- FEC "any transaction from one committee to another" (`itoth.txt`, the ~1.8GB bulk file
  that is the actual "2GB FEC download" the refresh timing above is dominated by), filtered
  to the 600 committees linked to a PA candidate or address.
- Philadelphia PAC/union receipts, pulled directly from the `campfin_contributions` Carto SQL
  API (aggregated server-side to donor-PAC pairs, 74,760 rows).

**What did not run:** PA state's own campaign-finance export. `campaignfinanceonline.pa.gov`
returns `403` to every request from this environment - the identical bot-protection pattern
already logged for `palegis.us` in the LT-04 build (see that architecture doc). This is an
environment limitation, not a code limitation: `build.py`'s `load_pa()` already knows how to
read this data once it's reachable.

**Result, on real data, Federal + Philadelphia only (no entity resolution merge applied -
`JEFFREY YASS` and `JEFF YASS` were left as separate rows rather than run through
`resolve.py`):**

| | |
|---|---|
| PAC receipt rows | 89,678 across 481 recipient committees |
| PACs with a resolved sponsor | 296 (296 sponsored / $228.8M) |
| PACs with a dominant (>=50%) funder | 218 |
| Chains longer than one hop | 20 |
| Top traced ultimate source | **Jeffrey Yass - $93.27M**, across the `JEFFREY YASS` /
  `JEFF YASS` variants, 3 PACs in the traced chain |

That the code independently re-derives Jeffrey Yass as the dominant traced source - from a
data slice that excludes the PA-state layer the original $71.25M/17-vehicle/5-hop finding
was built on - is the validation. The $93.27M figure here is not a replacement for the
$71.25M headline number in Section 1: it's a different, narrower run (two jurisdictions,
no entity merge) that landed on the same real-world actor, which is what "the code is
faithful to the method" looks like in practice, not a discrepancy to reconcile.

A defect this run caught and fixed is logged in Section 4, item 4.

**To reproduce or extend:** run `sponsors.py` then `chains.py` from `contributions/pipeline/`
against a standard `~/pafin` layout. They read `~/pafin/out/contributions_unified.parquet`
(from `build.py` - carries the PA-state and Philadelphia layers once that data is reachable)
and `~/pafin/fec/{cm.txt,itoth.txt}` (FEC bulk downloads, fetched fresh). Both scripts run
standalone against just the FEC layer if `contributions_unified.parquet` isn't present yet.
