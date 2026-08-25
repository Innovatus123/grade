# PA Political Contributions Tracker

**Owner:** Jelani Ellington | **Built:** 2026-08-04 | **Coverage:** filing years 2024-2026

Tracks all contributions to Pennsylvania politicians across three jurisdictions, split
organizational (corporate / PAC / union / party) vs individual.

---

## 1. Headline numbers (2024 - 2026 filings, deduplicated)

| Metric | Value |
|---|---|
| Rows ingested | 3,157,741 |
| Rows after dedupe | 3,014,777 |
| Cross-jurisdiction duplicates removed | 142,964 |
| Rollup / unitemized pseudo-donor rows excluded | 1,166 |
| **Total tracked** | **$1,040,537,000** |
| Individual | $452,161,800 (43.5%) |
| Organizational | $577,434,200 (55.5%) |
| Unresolved | $10,941,300 (1.1%) |

---

## 2. Sources

| Jurisdiction | Source | Format | Refresh |
|---|---|---|---|
| PA state | PA Dept. of State Full Campaign Finance Export | annual ZIP: `filer` / `contrib` / `expense` / `debt` / `receipt` pipe-free CSV | Restated periodically; re-pull `{year}.zip` |
| Philadelphia | `campfin_contributions` via Carto SQL API | CSV per `report_year` | Near real-time as reports are filed |
| Federal | FEC bulk: `cn` (candidates), `ccl` (linkage), `itpas2` (PAC-to-candidate), `itcont` (individuals) | pipe-delimited, filtered to PA | Weekly, typically Sunday |

---

## 3. Legal framework (drives the schema)

**Pennsylvania state**
- Corporations may **not** contribute directly to candidates - 25 P.S. Sec. 3253. Corporate money must move through a separate segregated fund (PAC). Exception: ballot questions.
- No dollar limits on contributions to PA state candidates beyond that treasury ban.
- Practical consequence: "corporate money" at the state level is almost never labeled corporate. It arrives as a PAC contribution. Tracking corporate influence requires tracing PAC sponsors, not reading donor names.

**Philadelphia**
- Individual limit **$3,700/yr**; non-individual (PAC, partnership, sole proprietorship, other business organization) limit **$14,800/yr**. Effective 2024-01-01; next quadrennial CPI adjustment 2028.
- Pay-to-play: exceeding the limit bars non-competitively bid city contracts (>$10,000 individual / >$25,000 business) for the officeholder's term. Attribution reaches affiliates, related entities, partners, directors, officers, and associated PACs.

**Federal**
- Corporate treasury contributions to candidates prohibited; corporate PACs (SSFs) permitted.
- Limits indexed per two-year cycle - verify current figures at fec.gov before any compliance use.

---

## 4. The central design problem

**No jurisdiction publishes a reliable corporate-vs-individual flag.**

- PA state: no donor-type field at all. Only the report schedule (IA/IB/IC/ID/IIF/IIG), occupation, and employer.
- Philadelphia: has a `donor_type` field, but it is **92% "Not Specified"** across 2024-2026.
- Federal: `ENTITY_TP` is populated and reliable - the one clean source.

Everything is therefore **derived** by a classifier with a documented precedence order:

1. Rollup-line screen (excludes "Unitemized", "Anonymous", "Total Other Contributions" - these carried ~$49M and would otherwise read as individual mega-donors)
2. Source-provided flag (Philadelphia `donor_type`)
3. FEC `ENTITY_TP`
4. Donor name matches a registered committee filer
5. Organizational name tokens (union / party / PAC / corporate legal form / advocacy)
6. PA report schedule (empirically: IA/IC/IIG organizational, IB/ID/IIF individual)
7. Employer or occupation present - implies a natural person
8. Name shape

Every row carries `donor_class`, `donor_class_method`, and `donor_class_conf`. **Filter on confidence before using any figure externally.** 4.1% of rows and 0.4% of dollars sit below 0.70 confidence.

---

## 5. Deduplication

Philadelphia's dataset and the PA state export both carry the same contributions for committees that dual-file. Measured overlap: **47% of Philadelphia dollars duplicated a PA-STATE row**.

Stacking the three sources naively overstates totals by ~$73M in this window alone.

Rows are **flagged, not deleted**. Take all totals on `is_primary = TRUE`. Philadelphia wins ties (richer record: donor_id, NAICS, incumbency, election outcome).

---

## 6. Known limitations

1. **Donor entity resolution** - donors match on normalized name only. "Jeff Yass" and "Jeffrey Yass" remain separate keys. Fuzzy matching is the next build phase. Sheet `09_Donor_Resolution_QA` flags 2,340 likely-same-entity name pairs above $25k.
2. **PA candidate IDs rotate** - PA state candidate FILERIDs are re-issued every election year (e.g. `2026C0421`). Cross-year candidate tracking requires a manual politician master crosswalk. Not yet built.
3. **Candidate committees are not typed as such** in the PA source - they carry FILERTYPE 2, same as any PAC. A filer is treated as a candidate vehicle when OFFICE is populated.
4. **Federal individual contributions** cover the 2026 cycle file only. Earlier cycles need additional `indiv[YY].zip` pulls.
5. **PA state export is filing-year based** - a contribution can appear in a different report year than its transaction date.

---

## 7. File layout

```
PA Political Contributions Tracker/
  README_PA_Contributions_Tracker.md        <- this file
  PA_Political_Contributions_Tracker.xlsx   <- aggregated analysis layer (10 sheets)
  top150_candidates_corp_vs_individual.csv  <- quick-reference extract
  detail/                                   <- 3.0M-row transaction layer, gzipped CSV by
                                               jurisdiction and year (~128 MB compressed)
  pipeline/                                 <- classify.py, build.py, finalize.py
```

The Excel workbook is the reading layer. The detail CSVs are the system of record. Never try to load 3M rows into Excel.

---

## 8. Refresh procedure

Re-run `build.py` then `finalize.py`. Both are idempotent - they re-download sources, re-classify, re-dedupe, and rewrite the workbook. Runtime approximately 12 minutes, dominated by the 2GB FEC individual-contributions download.

Recommended cadence: monthly, plus within one week of each PA reporting deadline.
