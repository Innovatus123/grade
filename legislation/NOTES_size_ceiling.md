# NOTE - the Box MCP write ceiling, and what it means for this tracker

**Recorded:** 2026-08-05 during the LT-04 build
**Applies to:** every sheet in `01_Current_Version/`

---

## The finding

Two separate limits govern what a cloud session can do to a file in Box. They are often
confused. They are not the same limit and they do not have the same fix.

**1. Reading HTML back - impossible, at any size.**
For `.html` Box exposes only png, pdf and extracted_text representations. There is no raw
read. This was already recorded in `07_Claude_Instructions/RULE_01` and it is why every
sheet is generated from a `.py` source rather than edited in place.

**2. Writing - possible, but capped at roughly 40 KB.**
Box MCP's `upload_file` and `upload_file_version` take the file's entire content **inline
as a parameter of the tool call**. That content has to be produced token by token, so the
practical ceiling is a few tens of kilobytes - about 40 KB of text before a single call
becomes unreliable.

## What was verified, not assumed

`index.html` was written through Box MCP and then checked with `get_file_details` on the
`sha1` field:

```
Box   e8fc6dea9c43c8e2b12aa7ab320ddb2d8ee346ad   10,847 bytes
Local e8fc6dea9c43c8e2b12aa7ab320ddb2d8ee346ad   10,847 bytes
```

All three build scripts verified the same way. **This corrects the note in
`02_Backup Versions/03_Backup_Log.md` dated 2026-08-05,** which said a cloud-written file
could not be verified. It can - `sha1` from `get_file_details` compared against a local
`sha1sum` is a byte-level check, and it costs one API call. Any cloud write to Box should
be verified this way from now on.

## What this means per file

| File | Size | Cloud-writable through Box MCP |
|---|---|---|
| `index.html` | 11 KB | **Yes** - verified |
| `*.py` build scripts | 10-33 KB | **Yes** - verified |
| `*.md` rules and notes | small | **Yes** |
| `PA_Delegation_Map.html` | 65 KB | Borderline - regenerate locally, place by hand |
| `PA_Legislation_Map.html` | 3.3 MB | **No** |
| `PA_Political_Contributions_Explorer.html` | 5.9 MB | **No** |
| `legislation_2025-2026.json` | 3.3 MB | **No** |

## The consequence, stated plainly

A cloud session can maintain **everything upstream of the rendered sheet** - the data
pipeline, the page template, the copy, the index, the rules - and can verify each write
byte for byte. It cannot put the large rendered sheets into Box. That last step needs the
desktop app or the Box web UI, and it is a drag-and-drop, not a rebuild.

This is a smaller dependency than it first appears. The expensive, error-prone work is the
harvest, the entity joins and the template. All of that is cloud-native and version
controlled in `02_Build/`. What remains manual is copying one finished file into one
folder.

## Do not work around it by shrinking the sheet

It is tempting to compress the embedded data - gzip plus base64 with a runtime inflate gets
LT-04 from 3.3 MB to roughly 280 KB. It was measured. It still does not fit in one tool
call, and it buys a smaller file at the cost of truncated bill titles and a decode step
that fails silently on an older browser. The sheets are read by people who may need to cite
them. Full fidelity beats a delivery convenience.
