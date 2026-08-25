# Politician Master Crosswalk - Build Notes

**Added:** 2026-08-04 | Third layer, after the tracker and entity resolution.

Links every candidate filing vehicle to one stable `politician_id`, so a politician can be
tracked across election years, committees and jurisdictions. Every contribution to a
candidate now carries that ID.

---

## 1. Result

| Metric | Value |
|---|---|
| Candidate filing vehicles | 2,039 |
| Distinct politicians | 1,347 |
| Politicians with more than one vehicle | 507 |
| Politicians spanning more than one jurisdiction | 30 |
| Max vehicles for a single politician | 5 |
| Contributions mapped to a politician | 432,820 |
| **Coverage of candidate dollars** | **99.9%** |
| Unmapped candidate dollars | $98,710 |

---

## 2. The problem

PA re-issues candidate FILERIDs every election year (`2026C0421`), and one politician files
under several vehicles simultaneously - a personal candidate record, one or more "Friends
of" committees with stable IDs, a Philadelphia filer, one or more federal committees.
Nothing in the published data links them. Before this, a politician's totals were split
across vehicles and could not be followed across cycles at all.

## 3. The key insight

PA candidate filers come in two shapes:

- **Rotating IDs** (`^\d{4}C...`) usually carry the politician's OWN name as the filer name:
  `KENYATTA, MALCOLM`, `JORDAN A. HARRIS`.
- **Stable IDs** carry the committee name: `FRIENDS OF ANGELA GIROL`.

Strip the committee wrapper off the second and it matches the first. That is the spine of
the crosswalk. Federal records seed it directly (FEC `CAND_ID` is already stable across
cycles); Philadelphia contributes its `filer_candidate_name` field where populated.

## 4. Method

**Stage 1 - exact name.** Parse every vehicle name to (first, middle, last, suffix), then
link on exact (first, last). 635 links.

**Stage 2 - fuzzy within surname blocks.** Metaphone surname blocking, then scored
comparison. Only 2 additional links - stage 1 does nearly all the work once names are
parsed correctly.

**Stage 3 - surname-only vehicles.** Committee names that reduce to a bare surname
("Shapiro for Pennsylvania" -> SHAPIRO) attach to a named politician only when exactly one
candidate shares that surname AND office class. 55 linked, 5 left ambiguous and standing
alone.

## 5. Guards

- **Party conflict blocks a link.** Two same-named candidates of different parties are two people.
- **Same office class, same year, different district blocks a link.** Two people, not one.
- **Middle-initial conflict is disqualifying.**
- Validated: Jordan Harris, Gregory Harris and Keith Harris stay three separate
  politicians. Amy Fitzpatrick (Common Pleas) stays separate from Brian Fitzpatrick (US House).

## 6. Defects found in validation

1. **Comma stripping reversed every federal name.** `FITZPATRICK, BRIAN` was being parsed as
   first=FITZPATRICK, last=BRIAN because normalization removed the comma before the parser
   could use it to detect "LAST, FIRST" order. Federal records therefore never matched
   their PA counterparts. Fixing this took usable-name coverage from 83.2% to 92.5% and
   exact-name links from 394 to 635.
2. **Rotating IDs do not always carry a bare name.** `2024C0510` is
   `CITIZENS FOR JORDAN A. HARRIS`. Assuming otherwise parsed first=CITIZENS and forked
   Jordan Harris into two politicians. Wrapper stripping now runs on every record.
3. **Election-year tokens survived as names.** `WECHT 2025` was its own politician;
   year and district-number tokens are now stripped so the surname falls through to stage 3.
4. **A coverage metric read 170%** because it divided mapped dollars by a narrower
   denominator than the numerator. Corrected to compare like with like - actual 99.9%.

## 7. Known limitations

1. **111 politician records do not parse as person names** (e.g. `KEYSTONE PROSPERITY`,
   `NICOLE`). Some are PACs whose filings populate an OFFICE field; some are single-name
   committees. They are flagged `name_parses_as_person = FALSE` in `politician_master.csv`
   and `politician_totals.csv`. They are correctly isolated - the label is wrong, not the money.
2. **5 surname-only vehicles left ambiguous** because more than one candidate shares the
   surname and office class. They stand alone rather than being guessed.
3. **One source date is corrupt** - a 2205 transaction year in a Wecht record. Source typo,
   not a pipeline error.
4. Philadelphia vehicles often have no office or party populated, so those fields are blank
   for some city politicians.

## 8. What this unlocks

Sheet `14_Politician_By_Year` is the thing that was impossible before: one politician, one
row, dollars by year across every vehicle. Sheet `17_Donor_to_Politician` is the influence
map - resolved donor entity to resolved politician, with totals and years. Sheet
`13_Politician_Totals` carries the corporate-vs-individual split per politician.

Chris Rabb shows offices `STH,USC` - a state House member running for Congress, tracked
through both. Sharif Street shows 3 vehicles across 2 jurisdictions. That cross-office,
cross-cycle view is the whole point.

## 9. Files

- `politician_master.csv` - 1,347 politicians with every linked FILERID
- `politician_totals.csv` - dollars per politician, corporate vs individual split
- `top120_politicians.csv` - quick-reference extract
- `PA_Political_Contributions_Tracker.xlsx` sheets 12-17
- `pipeline/crosswalk.py`, `pipeline/politician_report.py`

## 10. Refresh

`build.py` -> `resolve.py` -> `workbook.py` -> `crosswalk.py` -> `politician_report.py`.
All idempotent. `politician_id` is re-issued each run - never persist it outside the
pipeline as a permanent key.
