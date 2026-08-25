"""Generator for the GRADE sheet index (01_Current_Version/index.html).

Box will not return raw HTML through the API, so the index - like the sheets - is
generated from source rather than edited in place. Edit CONFIG / SHEETS / FINDINGS
below and re-run. Per RULE_01, back up 01_Current_Version/index.html before
uploading the result.

    python build_index.py            -> writes index.html
"""
import json, pathlib, sys, datetime

CONFIG = {
    "ORG":     "General Building Contractors Association",
    "BRAND":   "Government Relations &amp; Advocacy Data Engine",
    "TITLE":   "Sheet index",
    "PAGE":    "GBCA Government Relations &amp; Advocacy Data Engine - Sheet index",
    "ASOF":    "2026-08-20",
    "REV":     "Rev 004",
    "COVERAGE": "Compiled by GBCA Government Relations &amp; Advocacy Data Engine (GRADE) "
                "from public campaign finance and legislative filings. Coverage runs through "
                "the Pennsylvania campaign finance export dated 2026-07-24 and the "
                "2019-2020, 2021-2022, 2023-2024 and 2025-2026 legislative records as of "
                "2026-08-20.",
}

# Sheet cards, in order. stats = list of (value, label) pairs.
SHEETS = [
    {
        "id": "LT-01", "name": "Delegation Map", "file": "PA_Delegation_Map.html",
        "blurb": "Every PA House, Senate and executive branch official, mapped by county. "
                 "Filter by body, party, municipality, 2026 ballot status, leadership post "
                 "or agency tier.",
        "stats": [("203", "House"), ("50", "Senate"), ("30", "Executive"), ("67", "Counties")],
    },
    {
        "id": "LT-02", "name": "Contributions Index",
        "file": "PA_Political_Contributions_Index.html",
        "blurb": "The summary view. Corporate versus individual split by politician, money "
                 "by industry, the PAC funding chains, and the full method and limitations "
                 "record.",
        "stats": [("$1.007B", "Tracked"), ("3.01M", "Contributions"), ("2024–26", "Filing years")],
    },
    {
        "id": "LT-03", "name": "Contributions Explorer",
        "file": "PA_Political_Contributions_Explorer.html",
        "blurb": "The complete record. Search any politician or any donor, then walk the "
                 "network in either direction — who funded them, and who else that donor funds.",
        "stats": [("1,347", "Politicians"), ("315,029", "Donors"), ("165,907", "Links")],
    },
    {
        "id": "LT-04", "name": "Legislation Index", "file": "PA_Legislation_Map.html",
        "blurb": "AUTO_LEG_BLURB",
        "stats": "AUTO",   # filled from the legislation JSON
    },
]

FINDINGS = [
    ("$71.25M",
     "traced to a single individual — Jeffrey Yass — across 17 vehicles and up to five hops "
     "of PAC-to-PAC transfer, against $33.79M given directly. No other traced origin exceeds "
     "$1.5M."),
    ("10 to 1",
     "the ratio by which building trades labor ($29.7M) outspends construction contracting "
     "($3.1M) in Pennsylvania politics — inside GBCA's own industry."),
    ("AUTO_LEG", ""),
]

SOURCES = [
    ("Pennsylvania", "Dept. of State full campaign finance export", "Periodic restatement"),
    ("Philadelphia", "City campfin_contributions API", "Near real time"),
    ("Federal", "FEC bulk files, filtered to PA", "Weekly (Sunday)"),
    ("Officeholders", "PA General Assembly and pa.gov, cross-verified", "Weekly"),
    ("Legislation", "PA General Assembly record, harvested via LegiScan", "Per session sitting"),
    ("Prior sessions", "Same pipeline, seats corrected to the session being described", "Once, on load"),
]

ORD = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
       7: "seven", 8: "eight", 9: "nine", 10: "ten"}

CAVEATS = [
    ("Donor classification is derived.",
     "No jurisdiction publishes a reliable corporate-versus-individual flag — Pennsylvania has "
     "no such field, Philadelphia's is 92% unspecified, and only the FEC's entity code is "
     "dependable. Every row carries its method and a confidence score."),
    ("Totals use primary rows only.",
     "47% of Philadelphia dollars duplicate a Pennsylvania state row for committees that file "
     "in both places. Duplicates are flagged, never deleted."),
    ("Donor entities are deliberately under-merged.",
     "A wrong merge invents an influence claim, so borderline matches go to a review queue "
     "instead. Every donor total is a floor, not a ceiling."),
    ("Sponsor coverage on LT-04 is partial by design.", "AUTO_LEG_COVERAGE"),
    ("A district does not name the same person in every session.", "AUTO_LEG_SEATS"),
    ("LT-04's two oldest sessions predate the current district map.", "AUTO_LEG_MAP"),
]

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{PAGE}}</title>
<style>
:root{
  --ink:#1a1a19; --ink-2:#4a4a46; --ink-3:#7a7a72;
  --rule:#dedbd2; --rule-2:#efece4; --paper:#fbfaf7; --card:#ffffff;
  --accent:#7c2d12; --accent-soft:#fdf4ee;
  --mono:"SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:15px;
  line-height:1.55;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1120px;margin:0 auto;padding:0 28px}

header.mast{border-bottom:2px solid var(--ink);background:var(--card)}
.mast .wrap{display:flex;justify-content:space-between;align-items:flex-end;
  padding:22px 28px 14px;gap:24px;flex-wrap:wrap}
.org{font-family:var(--serif);font-size:20px}
.brand{font-size:11px;text-transform:uppercase;letter-spacing:.14em;color:var(--ink-3);
  margin-top:3px}
.mast .meta{font-size:11px;color:var(--ink-3);text-align:right;line-height:1.7}

.lede{background:var(--card);border-bottom:1px solid var(--rule)}
.lede .wrap{padding:30px 28px 34px;max-width:1120px}
.lede h1{font-family:var(--serif);font-weight:500;font-size:27px;margin:0 0 10px}
.lede p{margin:0;max-width:760px;font-size:15px;line-height:1.7;color:var(--ink-2)}

main{padding:34px 0 10px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(285px,1fr));gap:18px}
.card{background:var(--card);border:1px solid var(--rule);border-radius:3px;
  padding:20px 22px 18px;display:flex;flex-direction:column}
.card .sid{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;color:var(--ink-3);
  text-transform:uppercase}
.card h2{font-family:var(--serif);font-weight:500;font-size:21px;margin:5px 0 9px}
.card p{margin:0 0 15px;font-size:13.5px;line-height:1.6;color:var(--ink-2);flex:1}
.figs{display:grid;grid-template-columns:1fr 1fr;gap:9px 16px;border-top:1px solid var(--rule-2);
  padding-top:13px;margin-bottom:15px}
.fig .n{font-family:var(--serif);font-size:18px;line-height:1.1}
.fig .l{font-size:10px;text-transform:uppercase;letter-spacing:.09em;color:var(--ink-3);
  margin-top:2px}
.open{font-size:13px;font-weight:600}
.card.new{border-color:var(--accent)}
.card.new .sid::after{content:"New";margin-left:8px;background:var(--accent);color:#fff;
  border-radius:2px;padding:1px 5px;letter-spacing:.06em}

section.findings{margin-top:40px;background:var(--card);border:1px solid var(--rule);
  border-radius:3px;padding:26px 28px}
section.findings h2{font-family:var(--serif);font-weight:500;font-size:20px;margin:0 0 18px}
.flist{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:22px}
.f .n{font-family:var(--serif);font-size:26px;color:var(--accent);line-height:1.1}
.f p{margin:6px 0 0;font-size:13.5px;line-height:1.6;color:var(--ink-2)}

section.src{margin-top:34px}
section.src h2,section.cav h2{font-family:var(--serif);font-weight:500;font-size:20px;
  margin:0 0 12px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--rule)}
th{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.1em;
  color:var(--ink-3);font-weight:600;padding:9px 14px;background:var(--rule-2);
  border-bottom:1px solid var(--rule)}
td{padding:9px 14px;border-bottom:1px solid var(--rule-2);font-size:13.5px;color:var(--ink-2)}
tr:last-child td{border-bottom:none}

section.cav{margin-top:34px}
.cav .box{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--accent);
  padding:18px 22px}
.cav .box p{margin:0 0 11px;font-size:13.5px;line-height:1.65;color:var(--ink-2)}
.cav .box p:last-child{margin-bottom:0}
.cav .box strong{color:var(--ink)}

footer{border-top:1px solid var(--rule);margin-top:44px;padding:22px 0 50px;font-size:11.5px;
  color:var(--ink-3);line-height:1.75}
@media (max-width:640px){.wrap{padding:0 16px}.mast .wrap{padding:20px 16px 12px}
  .lede .wrap{padding:24px 16px 26px}}
</style>
</head>
<body>

<header class="mast">
  <div class="wrap">
    <div>
      <div class="org">{{ORG}}</div>
      <div class="brand">{{BRAND}}</div>
    </div>
    <div class="meta">{{TITLE}}<br>Data as of {{ASOF}} &middot; {{REV}}</div>
  </div>
</header>

<div class="lede">
  <div class="wrap">
    <h1>Pennsylvania political intelligence</h1>
    <p>Four sheets built from public filings: who holds office, who funds them, whose money it
    actually is once you trace it through the PACs, and what they are all voting on. Every figure
    is derived from primary sources with its method and confidence recorded &mdash; open any sheet's
    <em>Method &amp; limits</em> tab before citing a number externally.</p>
  </div>
</div>

<main class="wrap">
  <div class="cards">{{CARDS}}</div>

  <section class="findings">
    <h2>Three findings that shape everything else</h2>
    <div class="flist">{{FINDINGS}}</div>
  </section>

  <section class="src">
    <h2>Sources</h2>
    <table>
      <thead><tr><th>Jurisdiction</th><th>Source</th><th>Refresh</th></tr></thead>
      <tbody>{{SOURCES}}</tbody>
    </table>
  </section>

  <section class="cav">
    <h2>Before citing any figure</h2>
    <div class="box">{{CAVEATS}}</div>
  </section>
</main>

<footer class="wrap">
  {{COVERAGE}}<br>
  Sheets regenerate from source; see <span style="font-family:var(--mono)">07_Claude_Instructions/</span>
  for the build and retention rules.
</footer>

</body>
</html>
"""


def main():
    # every session the sheet carries, newest first
    paths = sorted(pathlib.Path("work").glob("legislation_*.json"), reverse=True)
    if not paths:
        paths = sorted(pathlib.Path(".").glob("legislation_*.json"), reverse=True)
    sess = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    leg = sess[0] if sess else None

    cards = []
    for s in SHEETS:
        blurb = s["blurb"]
        if blurb == "AUTO_LEG_BLURB":
            words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
                     7: "seven", 8: "eight", 9: "nine", 10: "ten"}
            blurb = (f"Every bill and resolution of {words.get(len(sess), len(sess))} "
                     "Pennsylvania legislative "
                     f"sessions, {sess[-1]['session']} through {sess[0]['session']}, each "
                     "clickable through to its record — and linked in both directions to the "
                     "members who sponsored it. Switch sessions from the header.")
        stats = s["stats"]
        if stats == "AUTO":
            if not leg:
                raise SystemExit("legislation_2025-2026.json is needed for the LT-04 card")
            tot = lambda k: sum(x["counts"][k] for x in sess)
            span = f"{sess[-1]['session'][:4]}–{sess[0]['session'][-2:]}"
            stats = [(f"{tot('bills'):,}", "Measures"),
                     (f"{tot('acts'):,}", "Enacted as Acts"),
                     (f"{tot('edges'):,}", "Sponsor links"),
                     (span, f"{len(sess)} sessions")]
        figs = "".join(
            f'<div class="fig"><div class="n">{v}</div><div class="l">{l}</div></div>'
            for v, l in stats)
        new = " new" if s["id"] == "LT-04" else ""
        cards.append(
            f'<article class="card{new}">'
            f'<div class="sid">Sheet {s["id"]}</div>'
            f'<h2>{s["name"]}</h2>'
            f'<p>{blurb}</p>'
            f'<div class="figs">{figs}</div>'
            f'<a class="open" href="{s["file"]}">Open sheet →</a>'
            f"</article>")

    findings = []
    for n, body in FINDINGS:
        if n == "AUTO_LEG":
            if not leg:
                continue
            tot = lambda k: sum(x["counts"][k] for x in sess)
            n = f"{tot('edges'):,}"
            words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
                     7: "seven", 8: "eight", 9: "nine", 10: "ten", 12: "twelve"}
            yrs = words.get(int(sess[0]["session"][-4:]) - int(sess[-1]["session"][:4]) + 1,
                            int(sess[0]["session"][-4:]) - int(sess[-1]["session"][:4]) + 1)
            body = (f"sponsor signatures now resolve to a named member and district across "
                    f"{tot('loaded'):,} measures in {words.get(len(sess), len(sess))} sessions, "
                    "covering everything "
                    f"that passed a chamber, was vetoed, or was enacted. {tot('gbca'):,} measures "
                    f"touch construction, labor or procurement directly — an {yrs}-year record of "
                    f"who signed what.")
        findings.append(f'<div class="f"><div class="n">{n}</div><p>{body}</p></div>')

    sources = "".join(f"<tr><td>{a}</td><td>{b}</td><td>{c}</td></tr>" for a, b, c in SOURCES)
    # LT-04 language scales with however many sessions are actually loaded.
    pre22 = [x["session"] for x in sess if x.get("mapEra") == "pre-2022"]
    fixed_names = sorted({f["name"] for x in sess for f in x.get("seatFixes", [])})
    auto = {
        "AUTO_LEG_COVERAGE":
            (f"Every measure of all {ORD.get(len(sess), len(sess))} sessions is listed, but full cosponsor rosters "
             "are loaded for the measures that passed a chamber, were vetoed, or were enacted. "
             "The sheet marks which is which; it does not present partial coverage as complete."),
        "AUTO_LEG_SEATS":
            ("LT-04's historical sessions identify members from the bill records of that session, "
             "not from today's roster. The source stamps each sponsor with the seat they hold now, "
             f"so {len(fixed_names)} members who have since changed chamber are remapped to the "
             "seat they actually held, each verified against two independent sources. A seat that "
             "changed hands mid-session names everyone who sponsored from it. Do not read a "
             "historical district as the member who holds it now."),
        "AUTO_LEG_MAP":
            ((f"{' and '.join(pre22)} ran under the pre-2022 legislative map. Those district "
              "numbers do not describe the same ground as today's — HD-189 then is not HD-189 now. "
              "The sheet therefore withholds county geography and current-occupant labels for "
              "those two sessions rather than joining data across incompatible maps. Treat a "
              "district number there as a label for a person, not a place.")
             if pre22 else "All loaded sessions share the current district map."),
    }
    caveats = "".join(f"<p><strong>{h}</strong> {auto.get(b, b)}</p>" for h, b in CAVEATS)

    html = TEMPLATE
    for k, v in CONFIG.items():
        html = html.replace("{{" + k + "}}", v)
    html = (html.replace("{{CARDS}}", "".join(cards))
                .replace("{{FINDINGS}}", "".join(findings))
                .replace("{{SOURCES}}", sources)
                .replace("{{CAVEATS}}", caveats))
    out = "index.html"
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    pathlib.Path(out).write_text(html, encoding="utf-8")
    print(f"built {out}  {len(html):,} bytes")


if __name__ == "__main__":
    main()
