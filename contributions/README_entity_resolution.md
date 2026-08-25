# Donor Entity Resolution - Build Notes

**Added:** 2026-08-04 | Supplements `README_PA_Contributions_Tracker.md`

Collapses name variants of the same real-world donor into one entity. Every one of the
3.0M transactions now carries a `donor_entity_id`.

---

## 1. Result

| Metric | Value |
|---|---|
| Donor name variants (input) | 350,759 |
| Resolved entities (output) | 315,029 |
| Variants absorbed | 35,730 (10.2%) |
| Deterministic merges (exact signature) | 30,824 |
| Fuzzy merges (scored) | 8,306 |
| Clusters split to break transitive chains | 3,224 |
| Pairs queued for human review | 10,100 |
| **Top-100 donors that were fragmented** | **48** |
| Dollars sitting inside multi-variant entities | $471.8M |

**Nearly half the top-100 donor list was split across multiple name spellings.** Any ranking
built before this was wrong.

---

## 2. Why it had to be derived

There is **no deterministic donor identifier in any of the three sources.**

Philadelphia's schema publishes `donor_id`, `donor_name_std`, `donor_filer_id` and
`donor_naics`. All four are **0% populated**. PA state and the FEC publish nothing
equivalent. So matching runs entirely on name structure plus corroborating attributes
(zip5 is 99.8% populated; employer is 61.8%).

---

## 3. Method

**Stage 1 - deterministic.** Exact signature match on (first, last, zip5) or
(first, last, employer) for persons; exact canonical string plus identical digit set for
organizations. 30,824 merges, no review needed.

**Stage 2 - blocked fuzzy.** Phonetic surname + first initial, and zip5 + surname prefix,
for persons. Metaphone of leading token, and canonical prefix, for organizations. A
vectorized `rapidfuzz.process.cdist` prefilter runs inside each block, then a detailed
scorer decides. 510,650 candidate pairs evaluated.

**Stage 2b - cluster consistency split.** Union-find is transitive, so a chain of
individually-plausible links can assemble a cluster whose endpoints are obviously different
people. Each person cluster is re-partitioned by expanded first name, then again by middle
initial and state. 3,224 clusters split.

**Stage 3 - canonical naming.** Highest-dollar variant wins; HTML entities decoded.

---

## 4. Guards (over-merging is the expensive failure)

A wrongly merged donor produces a fabricated influence claim, so the system is tuned to
under-merge. Auto-merge threshold 0.90; 0.82-0.90 goes to the review queue.

- **Numbers must match exactly.** IBEW Local 98 can never merge with IBEW Local 5.
- **Initial-only first names need two corroborations.** "A WILLIAMS" is equally consistent
  with Arthur, Avril, Anita and August. It requires matching zip AND matching employer, or
  it goes to review.
- **Middle-initial conflict is disqualifying** when both names carry one.
- **Conservative nickname list only.** NANCY, MARIA, LINDA, TRACY, CAROL, ROSE, NORA,
  MOLLY, JULIE and ANNA are deliberately NOT treated as nicknames. Traditional nickname
  tables map them (NANCY to ANN, etc.) and doing so measurably over-merged - it put
  "WILLIAMS, NANCY" in the same entity as "A MORRIS WILLIAMS".
- **Whole-string similarity guard** on the exact-name shortcut, so "MARIE AMEY-TAYLOR"
  does not collapse into "Marie Taylor" in a different city.
- **Person and organization entities never merge.**

---

## 5. Defects found and fixed during validation

Each of these was caught by auditing output, not by reasoning about the design:

1. `A MORRIS WILLIAMS`, `Arthur Williams`, `AVRIL WILLIAMS` and `WILLIAMS, NANCY` merged
   into one entity - three separate causes (bad nickname mapping, unguarded initial
   matching, transitive chaining). All three fixed.
2. `John M. Arnold` of Reading PA folded into the Houston megadonor `John D. Arnold` via a
   middle-initial-free variant. Fixed by extending the consistency split to middle initial
   and state.
3. `MARIE AMEY-TAYLOR` merged with `Marie Taylor` in a different city, because hyphen
   normalization truncated the surname. Fixed with a whole-string similarity guard.
4. Reporting rollup lines (`Federal Contributions, Non-PA Activity`, `Non Pennsylvania
   Receipts`, `AFT COPE - Contributions from FEC Report`) surfaced as top-20 donors once
   resolution consolidated them. $33.6M reclassified as EXCLUDE-ROLLUP.
5. `AMERICAN OPPORTUNITY ACTION` was scoring as an individual because the person-name
   heuristic returned true for any three-token name and vetoed the advocacy-org rule.

---

## 6. Known residual

Entities remain **under-merged by design**. A donor's resolved total is a floor, not a
ceiling. The review queue (10,100 pairs, sheet 11 of the workbook) is where the remaining
recall lives - work it top-down by dollar value.

---

## 7. Files

- `PA_Political_Contributions_Tracker.xlsx` - sheets 02, 05, 06, 07 and 11 are the entity layer
- `donor_entity_master.csv.gz` - all 315,029 entities with totals, gift counts, recipient reach
- `entity_review_queue.csv` - 10,100 borderline pairs for human adjudication
- `top200_donor_entities.csv` - preview extract (top 25 rows in this Box copy; full file delivered in chat)
- `pipeline/resolve.py` - the resolver

## 8. Refresh

`build.py` -> `resolve.py` -> `workbook.py`. All idempotent. ~20 minutes end to end.
Entity IDs are re-issued on each run and re-attached to transactions by `workbook.py`, so
never persist a `donor_entity_id` outside this pipeline as a permanent key.
