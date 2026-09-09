# GRADE — GBCA Government Relations & Advocacy Data Engine

Build pipelines for the General Building Contractors Association's Pennsylvania political
intelligence tracker: who holds office, who funds them, whose money it actually is once
traced through the PACs, and what they're voting on.

This repo holds the **code that builds the sheets**, not the sheets themselves or the raw
data. The rendered HTML sheets, the workbook, and the multi-hundred-megabyte transaction
detail live in the team's Box workspace (`Legislative_Tracker/`); this repo is what
regenerates them.

## Two pipelines

### `legislation/` — Sheet LT-04, Pennsylvania Legislation Index

Every bill and resolution across four PA General Assembly sessions (2019-2020 through
2025-2026), cross-linked in both directions to the members who sponsored them.

| | |
|---|---|
| Measures | 20,101 across 4 sessions |
| Sponsor rosters loaded | 4,598 (everything enacted, adopted, vetoed, or passed a chamber) |
| Sponsor links | 85,447 |
| Acts | 954 |

See `legislation/README.md` for the schema, the join logic (district-keyed, not
name-matched), and the two data hazards the build corrects for: LegiScan stamping sponsors
with their *current* seat rather than their session seat, and the pre-2022 sessions running
under a different district map.

### `contributions/` — Political Contributions Tracker

All inbound contributions to Pennsylvania politicians across PA state, Philadelphia, and
federal filings (2024-2026), with donor entities resolved and PAC money traced to its
ultimate source.

| | |
|---|---|
| Total tracked | $1.007B (3.01M contributions, deduplicated) |
| Split | Individual 44.4% / Organizational 54.5% / Unresolved 1.1% |
| Donor entities resolved | 315,029 (from 350,759 name variants) |
| Politicians crosswalked | 1,347 (from 2,039 filing vehicles), 99.9% of candidate $ mapped |

Two findings drive the build: Pennsylvania bars direct corporate giving to candidates, so
corporate influence is invisible without tracing PAC sponsors back to source — doing that
traces **$71.25M to Jeffrey Yass** across 17 vehicles and five hops. And **building trades
labor outspends construction contracting roughly 10 to 1** in PA politics, which is the
board-level fact for GBCA's own industry.

See `contributions/00_START_HERE.md` for the four-layer build order and the four things to
check before quoting any number externally.

## What's not here

Raw harvest data, the generated JSON/CSV datasets, the rendered HTML sheets, and the
transaction-detail layer are excluded from this repo — some for size (the detail layer is
~150MB gzipped), some because they're the output of a run rather than source. All of it
lives in Box; each pipeline's own README documents exactly what it produces and where.

## Pipeline completeness

`contributions/pipeline/` ships all seven scripts referenced in the contributions READMEs:
`build.py`, `classify.py`, `resolve.py`, `workbook.py`, `crosswalk.py`,
`politician_report.py`, and — as of 2026-09-09 — `sponsors.py` and `chains.py`, the fourth
layer that produces the PAC funding-chain trace (`pac_funding_sources.csv`,
`ultimate_sources.csv`, `sponsor_detail.csv`). See `contributions/README_pac_sponsor_tracing.md`
for the method and a real validation run against live FEC and Philadelphia data.

**Environment note.** Claude's cloud sandbox can reach the FEC's bulk-download endpoints and
Philadelphia's Carto SQL API directly, but PA's own campaign-finance site
(`campaignfinanceonline.pa.gov`) returns `403` to it — the same bot-protection pattern
already documented for `palegis.us` in the LT-04 build. A full `sponsors.py` / `chains.py`
run (all three jurisdictions) needs to happen wherever `build.py` itself already runs today;
from Claude's sandbox alone, only the FEC and Philadelphia slices are reachable.

## Status

Both pipelines are actively maintained. See each README's "Open build items" for the
priority-ordered backlog — highest-value items on both sides are the same shape: linking
LT-04's legislative record to the contributions tracker's politician roster, and overlaying
GBCA's own member list against the money.
