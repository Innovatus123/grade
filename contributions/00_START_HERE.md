# 13_Political_Contributions - Start Here

**Owner:** Jelani Ellington | **Last build:** 2026-08-04
**Path:** 20_GBCA / 80_Projects / Legislative_Tracker / 13_Political_Contributions

Tracks all contributions to Pennsylvania politicians across state, city and federal
filings, split organizational (corporate / PAC / union / party) vs individual, with donor
entities resolved, politicians crosswalked, and PAC money traced to its ultimate source.

---

## Headline numbers

| | |
|---|---|
| Contributions tracked | 3,014,777 (after dedupe) |
| **Total** | **$1,006,859,585** |
| Individual | $447.4M (44.4%) / Organizational $548.5M (54.5%) / Unresolved $10.9M |
| Donor entities (from 350,759 name variants) | 315,029 |
| Politicians (from 2,039 filing vehicles) | 1,347 - 99.9% of candidate $ mapped |
| PACs with a traceable funding chain | 360 ($89.9M given out) |
| Coverage window | Filing years 2024-2026 (through 2026-07-24) |

---

## Four layers, built in order

**1. The tracker** - ingests PA Dept. of State, Philadelphia and FEC bulk data into one
normalized schema, classifies donors, deduplicates across jurisdictions.
See `README_PA_Contributions_Tracker.md`.

**2. Donor entity resolution** - collapses name variants into one entity. 48 of the top 100
donors were fragmented. See `README_entity_resolution.md`.

**3. Politician crosswalk** - links every candidate filing vehicle to one stable politician
ID, so a politician can be followed across years, committees and jurisdictions.
See `README_politician_crosswalk.md`.

**4. PAC sponsor tracing** - traces each PAC to the organization or person behind it, and
follows PAC-to-PAC money to its origin. See `README_pac_sponsor_tracing.md`.

---

## The two findings that matter most

**Jeffrey Yass is the ultimate source of $71.25M** given to PA politicians across 17
vehicles, up to 5 hops deep - versus $33.79M in direct giving. The money moves
Yass -> Students First PAC (100%) -> Commonwealth Children's Choice Fund (100%) ->
Commonwealth Leaders Fund (98%) -> candidates. No other traced origin exceeds $1.5M.

**Building trades labor outspends construction contracting roughly 10 to 1** in PA politics
($29.7M vs $3.1M). If GBCA members are being outspent by an order of magnitude on the labor
side, that is a board-level fact.

---

## What to open

| File | Use |
|---|---|
| `PA_Political_Contributions_Tracker.xlsx` | The reading layer, 25 sheets. Sheet 00 has all rules and limitations. |
| `pac_funding_sources.csv` | Each PAC with its top five funders and their shares |
| `ultimate_sources.csv` | Money rolled up to the origin of each chain |
| `sponsor_detail.csv` | Every PAC with sponsor, type, industry, funder, full chain |
| `politician_master.csv` / `politician_totals.csv` | 1,347 politicians, dollars and splits |
| `donor_entity_master.csv.gz` | 315,029 resolved donor entities |
| `entity_review_queue.csv` | 10,100 borderline donor matches for human adjudication |
| `detail/` | The 3.0M-row transaction layer, gzipped CSV (~149 MB) |
| `pipeline/` | The seven scripts that rebuild everything |

Start at sheets `19_PAC_Funding_Sources`, `21_Ultimate_Sources`, `14_Politician_By_Year`.

---

## Four things to know before quoting any number

1. **All donor classification is derived.** No jurisdiction publishes a reliable
   corporate-vs-individual flag. Every row carries a confidence score.
2. **Take totals on `is_primary = TRUE`.** 47% of Philadelphia dollars duplicate a PA-STATE
   row for dual-filing committees. Rows are flagged, not deleted.
3. **Entities are deliberately under-merged.** A donor's resolved total is a floor.
4. **Sponsor chains use a 50% dominance threshold.** A PAC funded 45/45/10 has no chain edge
   and reads as its own origin.

---

## Legal framework driving the schema

- **PA state:** corporations may not contribute directly to candidates (25 P.S. 3253);
  corporate money must move through a PAC. No dollar limits otherwise. **This is why the
  sponsor-tracing layer exists** - without it, corporate influence is invisible.
- **Philadelphia:** $3,700/yr individual, $14,800/yr non-individual (effective 2024-01-01).
  Pay-to-play bars non-competitively bid city contracts.
- **Federal:** corporate treasury ban; corporate PACs permitted; limits indexed per cycle.

---

## Refresh

`build.py` -> `resolve.py` -> `workbook.py` -> `crosswalk.py` -> `politician_report.py` ->
`sponsors.py` -> `chains.py`. All idempotent, ~30 minutes end to end. Monthly, plus within
one week of each PA reporting deadline.

Entity, politician and sponsor IDs are re-issued each run - never persist them outside the
pipeline as permanent keys.

---

## Open items

1. **GBCA member-roster overlay.** Tag sponsors against the GBCA member list and by NAICS to
   isolate member-company giving from the wider construction field. Highest value remaining.
2. **Outbound layer.** GBCA PAC and Reconstruction PAC giving against the politician master.
3. Work the 10,100-pair donor review queue top-down by dollar value.
4. Reduce the "Unclassified" industry bucket ($430.7M) - much is party committees with no
   industry, but some is genuinely untagged.
5. Extend federal coverage to prior cycles.

*Note: this repo ships `pipeline/build.py`, `classify.py`, `resolve.py`, `workbook.py`,
`crosswalk.py` and `politician_report.py`. `sponsors.py` and `chains.py` (the layer behind
`pac_funding_sources.csv` / `ultimate_sources.csv` / `sponsor_detail.csv`) were not in the
archived pipeline bundle this repo was built from and still need to be added - see the
top-level README's "Known gap".*
