# PAC Sponsor Tracing - Build Notes

**Added:** 2026-08-04 | Fourth layer, after the tracker, entity resolution and the crosswalk.

Pennsylvania bars direct corporate contributions to candidates (25 P.S. 3253), so corporate
money reaches candidates only through a PAC. Donor names at state level therefore almost
never say "corporation." The influence is real but invisible unless each PAC is traced back
to the organization or person behind it. That is what this layer does.

> **Repo note:** the two scripts behind this layer, `pipeline/sponsors.py` and
> `pipeline/chains.py`, are not yet in this repo - see the top-level README's "Known gap."
> This document is kept as the build record for when they're added.

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
