# 14_Legislation

**Owner:** GBCA Government Relations & Advocacy Data Engine (GRADE)
**Feeds:** Sheet **LT-04 - Pennsylvania Legislation Index**
(`01_Current_Version/PA_Legislation_Map.html`)
**Established:** 2026-08-05
**Coverage:** four regular sessions - 2019-2020, 2021-2022, 2023-2024, 2025-2026

---

## What is here

| Path | Contents |
|---|---|
| `01_Data/` | The dataset. Per session: `legislation_<session>.json` (the sheet payload), `bills_<session>.csv` (one row per measure) and `bill_sponsors_<session>.csv` (one row per sponsor signature). |
| `02_Build/` (`build/` in this repo) | `assemble.py` (raw harvest -> dataset), `build_legislation_map.py` (dataset -> sheet), `build_index.py` (sheet index), `verify.py` (headless browser checks). |
| `03_Raw/` | The harvest output. Closed sessions are archived as `raw_<session>.zip`; the live 2025-2026 session stays loose in `03_Raw/2025-2026/` because it is still being appended to. Kept so a rebuild never has to re-scrape. |

The rendered sheet does **not** live here. Per the folder convention it lives in
`01_Current_Version/`, with backups in `02_Backup Versions/` under RULE_01. Neither the
dataset (`01_Data/`), the raw harvest (`03_Raw/`), nor the rendered sheet are checked into
this repo - only the build scripts. All of it lives in the team's Box workspace.

## Where the numbers stand

| Session | Measures | Sponsor rosters loaded | Sponsor links | Acts | Map era |
|---|---|---|---|---|---|
| 2025-2026 | 4,874 | 1,073 | 19,182 | 134 | post-2022 |
| 2023-2024 | 4,787 | 982 | 16,513 | 238 | post-2022 |
| 2021-2022 | 4,739 | 825 | 11,526 | 292 | pre-2022 |
| 2019-2020 | 5,701 | 1,718 | 38,226 | 290 | pre-2022 |
| **Total** | **20,101** | **4,598** | **85,447** | **954** | |

## Why the sheet is generated, not edited

Box will not return raw HTML through its API - for `.html` it exposes only png, pdf and
extracted_text representations. A cloud session can write that file but cannot read it
back, which makes in-place editing unverifiable. Box **does** return `.py`, `.json`, `.csv`
and `.md` verbatim, so everything upstream of the HTML is stored in a format that
round-trips. This is the same decision already recorded for LT-01 in
`07_Claude_Instructions/build_delegation_map.py`, and it is what keeps this sheet
maintainable from Box MCP alone, with no computer attached.

## Rebuilding the sheet - Box MCP only

1. Read `02_Build/build_legislation_map.py` and save it locally.
2. Read each `01_Data/legislation_<session>.json` into a `work/` directory beside it.
3. `python build_legislation_map.py` -> writes `PA_Legislation_Map.html`.
4. `python build_index.py` -> rewrites `index.html` from whatever sessions it finds.
5. `python verify.py` -> headless browser checks; it must print `PASS`.
6. **Back up** the existing `01_Current_Version/` files per RULE_01, then upload the new ones.
7. Append a row to `02_Backup Versions/03_Backup_Log.md`.

No step requires reading an `.html` file back out of Box. The sheet itself now exceeds the
Box MCP inline write ceiling, so placing it needs the desktop bridge - see
`NOTES_size_ceiling.md`, and note the hydration finding in the backup log.

## Adding another session

`assemble.py` reads `<raw>/*.jsonl` and writes the dataset; it is idempotent. To add a
prior session: harvest its inventory and sponsor pages into a new `raw<yy>/` directory, add
an entry to `SESSIONS` in `assemble.py` (with its `raw` directory, `year`, `closed`,
`map_era` and `inventory_note`), add the filename to `SESSION_FILES` in
`build_legislation_map.py`, and rebuild. The session selector and the index card pick it
up with no other change - both scale their own wording to however many sessions are loaded.

## Schema

`legislation_<session>.json`

```
session, sessionLabel, closed, generated, rosterIsCurrent, mapEra, inventoryNote
counts    { bills, loaded, edges, members, enacted, acts, gbca }
seatFixes[] name, seat, n
bills[]   id, pref, num, chamber, kind, title, status, rank, outcome, act,
          committee, lastDate, lastAction, prime[], co[], loaded, gbca, pa, ls
members[] key, chamber, district, name, party, leadership, counties, residence,
          ballot2026, seat_id, person_id, inRoster, prime[], co[],
          heldNowBy?, sharedSeat?
```

`prime[]` and `co[]` on a bill hold **district keys** (`HD-168`, `SD-24`), and the same
keys index `members[]`. That is the join, in both directions, and it is why the sheet can
walk from a bill to its sponsors and from a member back to their bills.

`status` is one of `Pass`, `Veto`, `Engross`, `Intro`, `N/A`. `outcome` is the human
reading of it against the last recorded action and whether the session has adjourned:
`Enacted`, `Adopted`, `Passed`, `Vetoed`, `Passed one chamber` / `Died after one chamber`,
`In committee` / `Died in committee`, `No action`.

## The join key is district, not name

Sponsors are matched to the LT-01 delegation roster by district code. District is the only
identifier both sources publish reliably; name spellings vary between them and name
matching would produce silent wrong merges - the same failure mode already documented in
the contributions build. Where a bill carries a district the roster snapshot does not
have, the member is created from the bill record and flagged `inRoster: false` rather than
dropped.

## Two corrections the historical sessions require

**1. The source reports today's seat, not the session's seat.** LegiScan stamps every
sponsor with the district they hold now. For a member who has since moved from the House to
the Senate, that files their historical sponsorships under a Senate seat they did not hold
at the time. The tell is a sponsor whose chamber does not match the bill's - in Pennsylvania
sponsorship is always same-chamber. `SEAT_OVERRIDES` in `assemble.py` remaps those rows to
the seat actually held, each district verified against two independent sources. Eleven
members are covered; `seatFixes` in each payload records who and how many rows. A chamber
conflict with no verified override is **dropped, not guessed** - all four builds currently
have zero.

**2. The two oldest sessions predate the current district map.** 2019-2020 and 2021-2022 ran
under the map drawn after the 2010 census; the current map took effect for terms beginning
2022-12-01. The same number describes different ground. Those sessions are therefore built
with `map_era: "pre-2022"`, which suppresses the county join from LT-01 and suppresses the
"held now by" label - joining either across incompatible maps would invent a fact. The sheet
says so on its method tab.

A seat that changed hands mid-session folds two people under one district key. Rather than
hide that, `sharedSeat` names everyone who sponsored from that seat, with counts.

## Known limits

- **Sponsor coverage is partial and marked.** Full cosponsor rosters are loaded for every
  measure that was enacted, adopted, vetoed or passed a chamber - 4,598 of 20,101. Everything
  else is listed with its record and links out, flagged `loaded: false`. Backfilling needs
  more fetches, not new logic.
- **Seven measures returned no sponsor names** across the 2019-2020 harvest and three across
  2021-2022; the source shows only a partisan-composition summary for them. They are recorded
  as unloaded rather than as having no sponsors.
- **palegis.us was unreachable from the build environment** - its robots file would not
  resolve - so LegiScan was the harvest surface. Every bill still links to the General
  Assembly's own record, which is the citable source.
- **Roughly 100 measures were lost to a source-side caching collision** in the 2025-2026
  inventory pass only. The later passes verify page continuity against last-action dates and
  use per-page cache-busters; 2023-2024, 2021-2022 and 2019-2020 are complete with zero
  collisions.
- **Titles occasionally arrive truncated** with an ellipsis from the listing pages. The
  bill's own record carries the full title.
- **`gbca` is a keyword screen** over the title - a starting filter, not a curated
  watchlist.

## Open build items (priority order)

1. **Cross-link LT-04 to LT-02/03** - a member's contributions beside their bills is the
   analytically valuable join, and both sheets are already district-indexed. This is now the
   highest-value remaining item.
2. **Committee membership layer** (`10_PA_Politicians/05_Committees` exists but is unused
   here) - who sits on the committee a bill died in is the question GBCA actually asks.
3. **Backfill sponsor rosters** for the ~15,500 measures that never cleared a chamber.
   Mechanical; the `loaded` flag makes it resumable in shards.
4. **A curated GBCA watchlist** replacing the keyword screen.
5. **2017-2018 and earlier.** Same pipeline. Note the override table will need extending for
   anyone who changed chamber between then and now, and the map era is pre-2022 throughout.
