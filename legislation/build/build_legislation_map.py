"""Generator for the GBCA PA Legislation Index (Sheet LT-04).

WHY THIS FILE EXISTS
--------------------
Same reason as build_delegation_map.py: Box will not return raw HTML through the
API - for .html it exposes only png, pdf and extracted_text representations, so a
cloud session can write that file but cannot read it back. Box *does* return .py
and .json verbatim, so the page template lives here as source and the data lives
beside it as JSON. Both round-trip through Box MCP with no computer attached.

TO REBUILD (Box-MCP-only workflow):
    1. read 14_Legislation/01_Data/legislation_2025-2026.json -> save locally
    2. read 14_Legislation/02_Build/build_legislation_map.py  -> save locally
    3. python build_legislation_map.py
    4. back up 01_Current_Version/PA_Legislation_Map.html per RULE_01
    5. place the new PA_Legislation_Map.html in 01_Current_Version/

    NOTE on step 5: the built sheet is ~3.3 MB. Box MCP's upload tools take file
    content inline in the tool call, which caps a single write at roughly 40 KB of
    text. index.html and these scripts fit; the sheet does not. Uploading it needs
    the desktop app or the Box web UI. Everything upstream of that one step is
    fully cloud-native - see NOTES_size_ceiling.md.

TO ADD A PRIOR SESSION:
    Produce legislation_<SESSION>.json with the same schema (see assemble.py) and
    add its filename to SESSION_FILES below. The sheet's session selector picks it
    up automatically; nothing else changes.

TO CHANGE COPY: edit CONFIG. TO CHANGE LAYOUT: edit TEMPLATE.
"""
import json, re, sys, pathlib

CONFIG = {
    "ORG":           "General Building Contractors Association",
    "BRAND":         "Government Relations &amp; Advocacy Data Engine",
    "PREPARED_FOR":  "GBCA GRADE",
    "SHEET_ID":      "LT-04",
    "SHEET_TITLE":   "Pennsylvania Legislation Index",
    "PAGE_TITLE":    "PA Legislation Index - GBCA Government Relations &amp; Advocacy Data Engine",
    "FOOTER_ATTRIB": "Compiled by GBCA Government Relations &amp; Advocacy Data Engine (GRADE) "
                     "from Pennsylvania General Assembly and LegiScan records.",
}

# Newest first. Each entry: (session label, json filename).
SESSION_FILES = [
    ("2025-2026", "legislation_2025-2026.json"),
    ("2023-2024", "legislation_2023-2024.json"),
    ("2021-2022", "legislation_2021-2022.json"),
    ("2019-2020", "legislation_2019-2020.json"),
]

OUTPUT = "PA_Legislation_Map.html"

TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{PAGE_TITLE}}</title>
<style>
:root{
  --ink:#1a1a19; --ink-2:#4a4a46; --ink-3:#7a7a72;
  --rule:#dedbd2; --rule-2:#efece4; --paper:#fbfaf7; --card:#ffffff;
  --accent:#7c2d12; --accent-soft:#fdf4ee;
  --dem:#1d4e89; --rep:#9b2226; --ind:#5b5b55;
  --ok:#2f6b4f; --warn:#8a6d1f; --bad:#8c2f39;
  --mono:"SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1240px;margin:0 auto;padding:0 28px}

/* masthead */
header.mast{border-bottom:2px solid var(--ink);background:var(--card)}
.mast .wrap{display:flex;justify-content:space-between;align-items:flex-end;
  padding-top:22px;padding-bottom:14px;gap:24px;flex-wrap:wrap}
.org{font-family:var(--serif);font-size:19px;letter-spacing:.01em}
.brand{font-size:11px;text-transform:uppercase;letter-spacing:.14em;color:var(--ink-3);
  margin-top:3px}
.mast .meta{font-size:11px;color:var(--ink-3);text-align:right;line-height:1.7}
.sheetbar{background:var(--ink);color:#f4f2ec}
.sheetbar .wrap{display:flex;align-items:center;gap:18px;padding:9px 28px;flex-wrap:wrap}
.sheetbar .sid{font-family:var(--mono);font-size:11px;letter-spacing:.12em;
  background:rgba(255,255,255,.14);padding:2px 7px;border-radius:2px}
.sheetbar h1{font-family:var(--serif);font-weight:500;font-size:17px;margin:0}
.sheetbar .sess{margin-left:auto;display:flex;align-items:center;gap:8px;font-size:12px}
.sheetbar select{font:inherit;font-size:12px;background:rgba(255,255,255,.12);
  color:#f4f2ec;border:1px solid rgba(255,255,255,.28);border-radius:3px;padding:3px 7px}
.sheetbar select option{color:#1a1a19}

/* stat strip */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:1px;background:var(--rule);border-bottom:1px solid var(--rule);margin:0}
.stat{background:var(--card);padding:13px 18px}
.stat .n{font-family:var(--serif);font-size:23px;line-height:1.1}
.stat .l{font-size:10.5px;text-transform:uppercase;letter-spacing:.1em;
  color:var(--ink-3);margin-top:3px}

/* tabs */
nav.tabs{border-bottom:1px solid var(--rule);background:var(--card)}
nav.tabs .wrap{display:flex;gap:2px}
nav.tabs button{font:inherit;font-size:13px;background:none;border:none;cursor:pointer;
  padding:11px 15px;color:var(--ink-2);border-bottom:2px solid transparent}
nav.tabs button:hover{color:var(--ink)}
nav.tabs button[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--accent);
  font-weight:600}

main{padding:22px 0 60px}
.panel{display:none}
.panel.on{display:block}

/* controls */
.controls{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
.controls input[type=search],.controls select{font:inherit;font-size:13px;padding:6px 9px;
  border:1px solid var(--rule);border-radius:3px;background:var(--card);color:var(--ink)}
.controls input[type=search]{min-width:290px;flex:1 1 290px}
.chip{font-size:12px;border:1px solid var(--rule);background:var(--card);border-radius:14px;
  padding:4px 11px;cursor:pointer;color:var(--ink-2)}
.chip[aria-pressed="true"]{background:var(--accent-soft);border-color:var(--accent);
  color:var(--accent);font-weight:600}
.count{font-size:12px;color:var(--ink-3);margin-left:auto}

/* tables */
table{width:100%;border-collapse:collapse;background:var(--card);
  border:1px solid var(--rule)}
th{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.1em;
  color:var(--ink-3);font-weight:600;padding:9px 12px;border-bottom:1px solid var(--rule);
  background:var(--rule-2);white-space:nowrap}
td{padding:9px 12px;border-bottom:1px solid var(--rule-2);vertical-align:top;font-size:13.5px}
tbody tr{cursor:pointer}
tbody tr:hover{background:var(--accent-soft)}
tbody tr:last-child td{border-bottom:none}
.bid{font-family:var(--mono);font-size:12.5px;white-space:nowrap;font-weight:600}
.ttl{line-height:1.4}
.muted{color:var(--ink-3);font-size:12px}

/* pills */
.pill{display:inline-block;font-size:10.5px;letter-spacing:.04em;padding:2px 7px;
  border-radius:10px;white-space:nowrap;border:1px solid transparent}
.p-Enacted{background:#e8f2ec;color:var(--ok);border-color:#c5ded1}
.p-Adopted{background:#e8f2ec;color:var(--ok);border-color:#c5ded1}
.p-Passed{background:#e8f2ec;color:var(--ok);border-color:#c5ded1}
.p-Passedonechamber{background:#fdf6e3;color:var(--warn);border-color:#ecdfba}
.p-Diedafteronechamber{background:#fdf6e3;color:var(--warn);border-color:#ecdfba}
.p-Diedincommittee{background:var(--rule-2);color:var(--ink-3);border-color:var(--rule)}
.p-Vetoed{background:#f9ecee;color:var(--bad);border-color:#e6c9ce}
.p-Incommittee{background:var(--rule-2);color:var(--ink-3);border-color:var(--rule)}
.p-Noaction{background:var(--rule-2);color:var(--ink-3);border-color:var(--rule)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;
  vertical-align:baseline}
.d-D{background:var(--dem)} .d-R{background:var(--rep)} .d-I{background:var(--ind)}
.gbca{display:inline-block;font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--accent);border:1px solid var(--accent);border-radius:2px;padding:0 4px;
  margin-left:6px;vertical-align:1px}

.more{display:block;width:100%;margin-top:12px;padding:9px;font:inherit;font-size:13px;
  background:var(--card);border:1px solid var(--rule);border-radius:3px;cursor:pointer;
  color:var(--ink-2)}
.more:hover{background:var(--accent-soft);color:var(--accent)}
.empty{padding:34px;text-align:center;color:var(--ink-3);background:var(--card);
  border:1px solid var(--rule)}

/* detail drawer */
.scrim{position:fixed;inset:0;background:rgba(26,26,25,.42);opacity:0;pointer-events:none;
  transition:opacity .16s;z-index:40}
.scrim.on{opacity:1;pointer-events:auto}
aside.drawer{position:fixed;top:0;right:0;height:100%;width:min(660px,100%);
  background:var(--card);border-left:1px solid var(--rule);z-index:50;
  transform:translateX(100%);transition:transform .2s ease;overflow-y:auto;
  box-shadow:-8px 0 30px rgba(0,0,0,.10)}
aside.drawer.on{transform:none}
.dhead{position:sticky;top:0;background:var(--card);border-bottom:1px solid var(--rule);
  padding:16px 22px;display:flex;gap:14px;align-items:flex-start;z-index:2}
.dhead .x{margin-left:auto;background:none;border:none;font-size:22px;line-height:1;
  cursor:pointer;color:var(--ink-3);padding:0 2px}
.dhead .x:hover{color:var(--ink)}
.dbody{padding:18px 22px 50px}
.dbody h3{font-size:10.5px;text-transform:uppercase;letter-spacing:.1em;color:var(--ink-3);
  margin:22px 0 8px;font-weight:600}
.dbody h3:first-child{margin-top:0}
.dtitle{font-family:var(--serif);font-size:17px;line-height:1.4;margin:0 0 4px}
.kv{display:grid;grid-template-columns:130px 1fr;gap:5px 14px;font-size:13px}
.kv dt{color:var(--ink-3);font-size:12px}
.kv dd{margin:0}
.slist{list-style:none;margin:0;padding:0;border:1px solid var(--rule);border-radius:3px}
.slist li{padding:7px 12px;border-bottom:1px solid var(--rule-2);font-size:13px;
  display:flex;align-items:center;gap:9px;cursor:pointer}
.slist li:last-child{border-bottom:none}
.slist li:hover{background:var(--accent-soft)}
.slist .role{margin-left:auto;font-size:10px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--ink-3)}
.slist .role.prime{color:var(--accent);font-weight:600}
.links a{display:inline-block;margin-right:14px;font-size:13px}
.notice{background:var(--accent-soft);border:1px solid #f0dccd;border-radius:3px;
  padding:11px 14px;font-size:12.5px;color:var(--ink-2);margin:14px 0}

/* prose */
.prose{background:var(--card);border:1px solid var(--rule);padding:26px 32px;max-width:820px}
.prose h2{font-family:var(--serif);font-weight:500;font-size:20px;margin:26px 0 9px}
.prose h2:first-child{margin-top:0}
.prose p{margin:0 0 12px;font-size:14px;line-height:1.65;color:var(--ink-2)}
.prose ul{margin:0 0 12px;padding-left:20px;font-size:14px;line-height:1.65;color:var(--ink-2)}
.prose li{margin-bottom:5px}
.prose table{border:1px solid var(--rule);margin:0 0 14px}
.prose td{font-size:13px}
.prose strong{color:var(--ink)}

footer{border-top:1px solid var(--rule);margin-top:40px;padding:20px 0 44px;
  font-size:11.5px;color:var(--ink-3);line-height:1.7}
@media (max-width:760px){
  .wrap{padding:0 16px}
  .sheetbar .wrap{padding:9px 16px}
  .kv{grid-template-columns:1fr}
  th.hide-s,td.hide-s{display:none}
}
</style>
</head>
<body>

<header class="mast">
  <div class="wrap">
    <div>
      <div class="org">{{ORG}}</div>
      <div class="brand">{{BRAND}}</div>
    </div>
    <div class="meta">
      Prepared for {{PREPARED_FOR}}<br>
      <span id="genline"></span>
    </div>
  </div>
</header>

<div class="sheetbar">
  <div class="wrap">
    <span class="sid">Sheet {{SHEET_ID}}</span>
    <h1>{{SHEET_TITLE}}</h1>
    <label class="sess">Session
      <select id="sessionSel"></select>
    </label>
  </div>
</div>

<div class="stats" id="stats"></div>

<nav class="tabs">
  <div class="wrap">
    <button id="tab-bills"   aria-selected="true"  onclick="showTab('bills')">Legislation</button>
    <button id="tab-members" aria-selected="false" onclick="showTab('members')">Members</button>
    <button id="tab-method"  aria-selected="false" onclick="showTab('method')">Method &amp; limits</button>
  </div>
</nav>

<main class="wrap">

  <section id="panel-bills" class="panel on">
    <div class="controls">
      <input type="search" id="q" placeholder="Search bill number, title, committee or sponsor name">
      <select id="fChamber"><option value="">Both chambers</option>
        <option>House</option><option>Senate</option></select>
      <select id="fKind"><option value="">Bills and resolutions</option>
        <option>Bill</option><option>Resolution</option></select>
      <select id="fOutcome"><option value="">Any status</option></select>
      <select id="fCommittee"><option value="">Any committee</option></select>
      <button class="chip" id="cGbca"    aria-pressed="false">Construction-relevant</button>
      <button class="chip" id="cLoaded"  aria-pressed="false">Sponsor roster loaded</button>
      <span class="count" id="billCount"></span>
    </div>
    <div id="billTable"></div>
  </section>

  <section id="panel-members" class="panel">
    <div class="controls">
      <input type="search" id="mq" placeholder="Search member name, district or county">
      <select id="mChamber"><option value="">Both chambers</option>
        <option>House</option><option>Senate</option></select>
      <select id="mParty"><option value="">Any party</option>
        <option>Democratic</option><option>Republican</option></select>
      <span class="count" id="memCount"></span>
    </div>
    <div id="memTable"></div>
  </section>

  <section id="panel-method" class="panel">
    <div class="prose" id="methodBody"></div>
  </section>

</main>

<div class="scrim" id="scrim" onclick="closeDrawer()"></div>
<aside class="drawer" id="drawer" role="dialog" aria-modal="true">
  <div class="dhead" id="dhead"></div>
  <div class="dbody" id="dbody"></div>
</aside>

<footer class="wrap">
  {{FOOTER_ATTRIB}}<br>
  Sheets regenerate from source; see <span style="font-family:var(--mono)">07_Claude_Instructions/</span>
  for the build and retention rules. Bill numbers link to the Pennsylvania General Assembly
  record of the measure.
</footer>

<script>
const SESSIONS = {{DATA}};
let D = null, SESS = null;
const M = {};          // district key -> member
const B = {};          // bill id -> bill
let billRows = [], memRows = [], billShown = 0, memShown = 0;
const PAGE = 120;

const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const pcode = p => (p || "").charAt(0).toUpperCase();
const cls = s => "p-" + String(s || "").replace(/[^A-Za-z]/g, "");

/* ---------------------------------------------------------------- load */
function loadSession(key){
  SESS = key;
  D = SESSIONS[key];
  for (const k in M) delete M[k];
  for (const k in B) delete B[k];
  D.members.forEach(m => M[m.key] = m);
  D.bills.forEach(b => B[b.id] = b);

  document.getElementById("genline").innerHTML =
    esc(D.sessionLabel) + "<br>Data as of " + esc(D.generated);

  const c = D.counts;
  document.getElementById("stats").innerHTML = [
    [c.bills.toLocaleString(),  "Measures"],
    [c.acts.toLocaleString(),   "Enacted as Acts"],
    [c.enacted.toLocaleString(),"Enacted or adopted"],
    [c.loaded.toLocaleString(), "Sponsor rosters loaded"],
    [c.edges.toLocaleString(),  "Bill-member links"],
    [c.members.toLocaleString(),"Members linked"],
    [c.gbca.toLocaleString(),   "Construction-relevant"],
  ].map(s => '<div class="stat"><div class="n">' + s[0] +
             '</div><div class="l">' + s[1] + "</div></div>").join("");

  const outs = [...new Set(D.bills.map(b => b.outcome))].sort();
  document.getElementById("fOutcome").innerHTML =
    '<option value="">Any status</option>' +
    outs.map(o => "<option>" + esc(o) + "</option>").join("");

  const coms = [...new Set(D.bills.map(b => b.committee).filter(Boolean))].sort();
  document.getElementById("fCommittee").innerHTML =
    '<option value="">Any committee</option>' +
    coms.map(o => "<option>" + esc(o) + "</option>").join("");

  renderMethod();
  filterBills();
  filterMembers();
}

/* ---------------------------------------------------------------- bills */
function sponsorNames(b){
  return b.prime.concat(b.co).map(k => (M[k] || {}).name || "").join(" ");
}
function filterBills(){
  const q  = document.getElementById("q").value.trim().toLowerCase();
  const ch = document.getElementById("fChamber").value;
  const kd = document.getElementById("fKind").value;
  const oc = document.getElementById("fOutcome").value;
  const cm = document.getElementById("fCommittee").value;
  const gb = document.getElementById("cGbca").getAttribute("aria-pressed") === "true";
  const ld = document.getElementById("cLoaded").getAttribute("aria-pressed") === "true";

  billRows = D.bills.filter(b => {
    if (ch && b.chamber !== ch) return false;
    if (kd && b.kind !== kd) return false;
    if (oc && b.outcome !== oc) return false;
    if (cm && b.committee !== cm) return false;
    if (gb && !b.gbca) return false;
    if (ld && !b.loaded) return false;
    if (!q) return true;
    return (b.id + " " + b.title + " " + b.committee + " " + b.act + " " +
            sponsorNames(b)).toLowerCase().includes(q);
  });
  billRows.sort((a, z) => (z.rank - a.rank) ||
    (z.lastDate < a.lastDate ? -1 : z.lastDate > a.lastDate ? 1 : 0) ||
    a.pref.localeCompare(z.pref) || a.num - z.num);
  billShown = 0;
  document.getElementById("billCount").textContent =
    billRows.length.toLocaleString() + " of " + D.bills.length.toLocaleString() + " measures";
  const host = document.getElementById("billTable");
  if (!billRows.length){ host.innerHTML = '<div class="empty">No measures match those filters.</div>'; return; }
  host.innerHTML = '<table><thead><tr><th>Bill</th><th>Title</th>' +
    '<th class="hide-s">Status</th><th class="hide-s">Sponsors</th>' +
    '<th class="hide-s">Last action</th></tr><tbody id="billBody"></tbody></table>' +
    '<button class="more" id="billMore" onclick="moreBills()"></button>';
  moreBills();
}
function moreBills(){
  const body = document.getElementById("billBody");
  const slice = billRows.slice(billShown, billShown + PAGE);
  body.insertAdjacentHTML("beforeend", slice.map(b => {
    const n = b.prime.length + b.co.length;
    return '<tr onclick="openBill(\'' + b.id + '\')">' +
      '<td class="bid">' + esc(b.id) + "</td>" +
      '<td class="ttl">' + esc(b.title.length > 190 ? b.title.slice(0, 190) + "…" : b.title) +
        (b.gbca ? '<span class="gbca">Industry</span>' : "") + "</td>" +
      '<td class="hide-s"><span class="pill ' + cls(b.outcome) + '">' + esc(b.outcome) + "</span>" +
        (b.act ? '<div class="muted">' + esc(b.act) + "</div>" : "") + "</td>" +
      '<td class="hide-s">' + (b.loaded ? n : '<span class="muted">not loaded</span>') + "</td>" +
      '<td class="hide-s muted">' + esc(b.lastDate || "—") + "</td></tr>";
  }).join(""));
  billShown += slice.length;
  const btn = document.getElementById("billMore");
  if (billShown >= billRows.length) btn.style.display = "none";
  else { btn.style.display = "block";
         btn.textContent = "Show " + Math.min(PAGE, billRows.length - billShown) +
           " more (" + (billRows.length - billShown).toLocaleString() + " remaining)"; }
}

/* ---------------------------------------------------------------- members */
function filterMembers(){
  const q  = document.getElementById("mq").value.trim().toLowerCase();
  const ch = document.getElementById("mChamber").value;
  const pt = document.getElementById("mParty").value;
  memRows = D.members.filter(m => {
    if (ch && m.chamber !== ch) return false;
    if (pt && m.party !== pt) return false;
    if (!q) return true;
    return (m.name + " " + m.key + " " + m.counties + " " + m.residence + " " +
            m.leadership).toLowerCase().includes(q);
  });
  memRows.sort((a, z) => (z.prime.length + z.co.length) - (a.prime.length + a.co.length));
  memShown = 0;
  document.getElementById("memCount").textContent =
    memRows.length.toLocaleString() + " of " + D.members.length.toLocaleString() + " members";
  const host = document.getElementById("memTable");
  if (!memRows.length){ host.innerHTML = '<div class="empty">No members match.</div>'; return; }
  host.innerHTML = '<table><thead><tr><th>Member</th><th>District</th>' +
    '<th class="hide-s">Counties</th><th>Prime</th><th>Cosponsored</th></tr>' +
    '<tbody id="memBody"></tbody></table>' +
    '<button class="more" id="memMore" onclick="moreMembers()"></button>';
  moreMembers();
}
function moreMembers(){
  const body = document.getElementById("memBody");
  const slice = memRows.slice(memShown, memShown + PAGE);
  body.insertAdjacentHTML("beforeend", slice.map(m =>
    '<tr onclick="openMember(\'' + m.key + '\')">' +
    '<td><span class="dot d-' + pcode(m.party) + '"></span>' + esc(m.name) +
      (m.leadership ? '<div class="muted">' + esc(m.leadership) + "</div>" : "") + "</td>" +
    '<td class="bid">' + esc(m.key) + "</td>" +
    '<td class="hide-s muted">' + esc(m.counties) + "</td>" +
    "<td>" + m.prime.length + "</td><td>" + m.co.length + "</td></tr>").join(""));
  memShown += slice.length;
  const btn = document.getElementById("memMore");
  if (memShown >= memRows.length) btn.style.display = "none";
  else { btn.style.display = "block";
         btn.textContent = "Show " + Math.min(PAGE, memRows.length - memShown) + " more"; }
}

/* ---------------------------------------------------------------- drawer */
function openBill(id){
  const b = B[id]; if (!b) return;
  location.hash = "bill/" + id;
  document.getElementById("dhead").innerHTML =
    '<div><div class="bid" style="font-size:14px">' + esc(b.id) + "</div>" +
    '<div class="muted">' + esc(b.chamber) + " " + esc(b.kind) + " · " +
    esc(D.session) + "</div></div>" +
    '<button class="x" onclick="closeDrawer()" aria-label="Close">&times;</button>';

  const roster = b.prime.map(k => [k, "prime"]).concat(b.co.map(k => [k, "co"]));
  const rosterHtml = b.loaded
    ? (roster.length
        ? '<ul class="slist">' + roster.map(([k, r]) => {
            const m = M[k] || {name: k, party: ""};
            return '<li onclick="openMember(\'' + k + '\')">' +
              '<span class="dot d-' + pcode(m.party) + '"></span>' +
              "<span>" + esc(m.name) + '</span><span class="muted">' + esc(k) + "</span>" +
              '<span class="role ' + r + '">' + (r === "prime" ? "Prime sponsor" : "Cosponsor") +
              "</span></li>";
          }).join("") + "</ul>"
        : '<div class="muted">No sponsors recorded on the source page.</div>')
    : '<div class="notice">The sponsor roster for this measure has not been harvested yet. ' +
      'Coverage in this release is every measure that passed a chamber or was enacted, ' +
      'plus recovery fetches. Open the General Assembly record below for the full ' +
      'cosponsor list, or run the backfill described in Method &amp; limits.</div>';

  document.getElementById("dbody").innerHTML =
    '<p class="dtitle">' + esc(b.title || "(no title recorded)") + "</p>" +
    (b.gbca ? '<span class="gbca">Construction-relevant</span>' : "") +
    "<h3>Record</h3><dl class=\"kv\">" +
    "<dt>Status</dt><dd><span class=\"pill " + cls(b.outcome) + '">' + esc(b.outcome) + "</span></dd>" +
    (b.act ? "<dt>Act number</dt><dd>" + esc(b.act) + "</dd>" : "") +
    (b.committee ? "<dt>Committee</dt><dd>" + esc(b.committee) + "</dd>" : "") +
    "<dt>Last action</dt><dd>" + esc(b.lastAction || "—") +
      (b.lastDate ? ' <span class="muted">' + esc(b.lastDate) + "</span>" : "") + "</dd>" +
    "</dl>" +
    "<h3>Sponsors" + (b.loaded ? " · " + (b.prime.length + b.co.length) : "") + "</h3>" +
    rosterHtml +
    '<h3>Open the record</h3><div class="links">' +
    '<a href="' + b.pa + '" target="_blank" rel="noopener">Pennsylvania General Assembly ↗</a>' +
    '<a href="' + b.ls + '" target="_blank" rel="noopener">LegiScan ↗</a></div>';
  showDrawer();
}

function openMember(key){
  const m = M[key]; if (!m) return;
  location.hash = "member/" + key;
  document.getElementById("dhead").innerHTML =
    '<div><div style="font-family:var(--serif);font-size:17px">' +
    '<span class="dot d-' + pcode(m.party) + '"></span>' + esc(m.name) + "</div>" +
    '<div class="muted">' + esc(m.party) + " · " + esc(m.key) +
    (m.leadership ? " · " + esc(m.leadership) : "") + "</div></div>" +
    '<button class="x" onclick="closeDrawer()" aria-label="Close">&times;</button>';

  const list = (ids, label) => ids.length
    ? "<h3>" + label + " · " + ids.length + "</h3><ul class=\"slist\">" +
      ids.map(id => {
        const b = B[id] || {id: id, title: "", outcome: ""};
        return '<li onclick="openBill(\'' + id + '\')">' +
          '<span class="bid">' + esc(id) + "</span>" +
          "<span>" + esc((b.title || "").slice(0, 96)) + ((b.title || "").length > 96 ? "…" : "") +
          '</span><span class="role">' + esc(b.outcome) + "</span></li>";
      }).join("") + "</ul>"
    : "<h3>" + label + "</h3><div class=\"muted\">None recorded in loaded coverage.</div>";

  document.getElementById("dbody").innerHTML =
    "<dl class=\"kv\">" +
    "<dt>Chamber</dt><dd>" + esc(m.chamber) + "</dd>" +
    "<dt>District</dt><dd>" + esc(m.key) + "</dd>" +
    (m.counties ? "<dt>Counties</dt><dd>" + esc(m.counties) + "</dd>" : "") +
    (m.residence ? "<dt>Residence</dt><dd>" + esc(m.residence) + "</dd>" : "") +
    (m.ballot2026 ? "<dt>2026 status</dt><dd>" + esc(m.ballot2026) + "</dd>" : "") +
    (m.heldNowBy ? "<dt>Seat held now by</dt><dd>" + esc(m.heldNowBy) + "</dd>" : "") +
    (m.sharedSeat ? "<dt>Seat changed hands</dt><dd>This seat was held by more than one " +
      "member during the session. Sponsorships below are the seat's, not one person's: " +
      m.sharedSeat.map(x => esc(x.name) + " (" + x.sponsorships + ")").join(", ") +
      "</dd>" : "") +
    (m.inRoster || !D.rosterIsCurrent ? "" :
      "<dt>Roster</dt><dd class=\"muted\">Not in the LT-01 roster snapshot; " +
      "identity taken from the bill record.</dd>") +
    "</dl>" + list(m.prime, "Prime sponsor") + list(m.co, "Cosponsored");
  showDrawer();
}

function showDrawer(){
  document.getElementById("drawer").classList.add("on");
  document.getElementById("scrim").classList.add("on");
  document.getElementById("drawer").scrollTop = 0;
}
function closeDrawer(){
  document.getElementById("drawer").classList.remove("on");
  document.getElementById("scrim").classList.remove("on");
  if (location.hash) history.replaceState(null, "", location.pathname + location.search);
}
document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });

/* ---------------------------------------------------------------- tabs */
function showTab(name){
  ["bills", "members", "method"].forEach(t => {
    document.getElementById("panel-" + t).classList.toggle("on", t === name);
    document.getElementById("tab-" + t).setAttribute("aria-selected", String(t === name));
  });
}

function renderMethod(){
  const c = D.counts;
  const pct = Math.round(c.loaded / c.bills * 100);
  document.getElementById("methodBody").innerHTML = `
<h2>What this sheet contains</h2>
<p>Every bill and resolution introduced in the Pennsylvania General Assembly's
${esc(D.sessionLabel)} — <strong>${c.bills.toLocaleString()} measures</strong> — with its
title, status, committee, last recorded action and a link to the official record.
<strong>${c.loaded.toLocaleString()}</strong> of them (${pct}%) also carry the complete
sponsor roster, which is what makes the bill-to-member links on this sheet work in both
directions: open a measure to see everyone who signed it, open a member to see everything
they signed.</p>

<h2>Sponsor coverage is deliberately partial in this release</h2>
<p>A full cosponsor roster is a separate page fetch per measure. Harvesting all
${c.bills.toLocaleString()} would take several thousand requests, so this release
prioritises the measures where sponsorship carries weight: <strong>everything that was
enacted, adopted or passed at least one chamber</strong>${D.closed ? "" : ", plus recovery fetches for measures the inventory pass missed"}. Everything else is listed with its record and links
out; nothing is hidden.</p>
<p>The <em>Sponsor roster loaded</em> filter isolates the covered set. Backfilling the
remainder is mechanical — it needs no new logic, only more fetches — and the loaded flag
on each measure is what makes it resumable.</p>

<h2>How a sponsor becomes a link</h2>
<p>Sponsors are matched to the LT-01 delegation roster by <strong>district code</strong>
(HD-001 … HD-203, SD-01 … SD-50), not by name. District is the only identifier both
sources publish reliably, and it survives the spelling variance that makes name matching
unsafe. Where a bill records a district our roster snapshot does not carry — a seat that
changed hands mid-session, for instance — the member is created from the bill record and
flagged in their detail panel rather than dropped.</p>

${D.rosterIsCurrent ? "" : `
<h2>This is a closed session, and that changes who a district means</h2>
<p>Members here are the people who held the seat during ${esc(D.session)}, taken from the
bill records themselves rather than from the LT-01 roster - LT-01 describes the
<em>current</em> chamber.</p>
${D.mapEra === "pre-2022" ? `
<p><strong>These district numbers are not today's districts.</strong> ${esc(D.session)} ran
under the map drawn after the 2010 census. Pennsylvania's current map took effect for terms
beginning 1 December 2022, and it renumbered and redrew seats. HD-189 in ${esc(D.session)}
is not the same ground as HD-189 now. Two things follow, and both are enforced in the data
rather than left to the reader: county geography is <em>not</em> joined onto members in
this session, and the member panel does <em>not</em> report who holds the seat today. Read
a district here as a label for a person in that session, nothing more.</p>
` : `
<p>County geography is still joined from LT-01 by district, which is safe for this session:
Pennsylvania's current map took effect in 2022 and covers it. Where the seat has since
changed hands, the member panel names who holds it now.</p>
`}
${(D.seatFixes && D.seatFixes.length) ? `
<p><strong>The source misfiles members who changed chamber, and that is corrected here.</strong>
LegiScan stamps every sponsor with the seat they hold <em>today</em>, not the seat they held
during the session. ${D.seatFixes.length} member${D.seatFixes.length === 1 ? " has" : "s have"}
changed chamber since ${esc(D.session)}. Left alone, their sponsorships would file under a
Senate district they did not hold at the time. The tell is a sponsor whose chamber does not
match the bill's - in Pennsylvania sponsorship is always same-chamber - and every such row is
remapped to the seat the member actually held that session, each verified against the General
Assembly member record and a second independent source. A member who moved mid-session
legitimately spans both seats, and the bill's own chamber decides which applies. Any chamber
conflict without a verified override is dropped rather than guessed; this build had none.</p>
<table>
<tr><th style="text-align:left">Member</th><th style="text-align:left">Seat in ${esc(D.session)}</th><th style="text-align:left">Sponsorships remapped</th></tr>
${D.seatFixes.map(f => "<tr><td>" + esc(f.name) + "</td><td>" + esc(f.seat) + "</td><td>" + f.n.toLocaleString() + "</td></tr>").join("")}
</table>
` : ""}
`}
<h2>Sources</h2>
<table>
<tr><td><strong>Bill inventory</strong></td><td>LegiScan Pennsylvania
${esc(D.session)} session listing, all pages</td></tr>
<tr><td><strong>Sponsor rosters</strong></td><td>LegiScan per-measure sponsor pages</td></tr>
<tr><td><strong>Member roster</strong></td><td>LT-01 delegation index, itself compiled from
the PA General Assembly and pa.gov</td></tr>
<tr><td><strong>Canonical record</strong></td><td>Every bill links to
palegis.us, the General Assembly's own record</td></tr>
</table>
<p>The General Assembly site could not be read directly during this build — its robots
file was unreachable from the build environment for the whole session — so LegiScan was
used as the harvest surface and palegis.us as the link target. If a figure here matters
externally, open the General Assembly record and confirm it there.</p>

<h2>Known limits</h2>
<ul>
<li>${D.inventoryNote === "collision"
  ? "Roughly 100 measures were lost to a caching collision on two inventory pages and recovered only partially. Bill numbers that appear nowhere in the source listing were tested individually; the large majority returned no " + esc(D.session) + " record, which is the expected result for reserved-but-unused numbers."
  : "The inventory for this session is complete: every listing page was fetched, page continuity was verified against last-action dates to catch the caching collisions that corrupted an earlier pass, and no page was lost or duplicated."}</li>
<li>Titles come from the listing pages and are occasionally truncated by the source with
an ellipsis. The bill's own record always carries the full title.</li>
<li><em>Construction-relevant</em> is a keyword screen over the title, not a subject-matter
judgement. It is a starting filter, not a curated watchlist.</li>
<li>${D.closed
  ? "This session has adjourned sine die, so every status is final. Measures that never left committee are shown as <em>Died in committee</em> rather than <em>In committee</em> - the source labels both the same way, and calling a dead bill pending would be misleading."
  : "Status reflects the last action recorded at harvest time. The session is live; verify before citing."}</li>
</ul>

<h2>Adding a prior session</h2>
<p>The sheet is built to hold more than one. Produce a
<span style="font-family:var(--mono)">legislation_&lt;session&gt;.json</span> with the same
schema, add it to <span style="font-family:var(--mono)">SESSION_FILES</span> in
<span style="font-family:var(--mono)">build_legislation_map.py</span>, and rebuild — the
session selector picks it up with no other change.</p>`;
}

/* ---------------------------------------------------------------- boot */
(function(){
  const sel = document.getElementById("sessionSel");
  sel.innerHTML = Object.keys(SESSIONS)
    .map(k => "<option value=\"" + k + "\">" + k + "</option>").join("");
  sel.onchange = () => loadSession(sel.value);
  loadSession(Object.keys(SESSIONS)[0]);

  document.getElementById("q").oninput          = filterBills;
  document.getElementById("fChamber").onchange  = filterBills;
  document.getElementById("fKind").onchange     = filterBills;
  document.getElementById("fOutcome").onchange  = filterBills;
  document.getElementById("fCommittee").onchange= filterBills;
  ["cGbca", "cLoaded"].forEach(id => {
    document.getElementById(id).onclick = e => {
      const on = e.currentTarget.getAttribute("aria-pressed") === "true";
      e.currentTarget.setAttribute("aria-pressed", String(!on));
      filterBills();
    };
  });
  document.getElementById("mq").oninput         = filterMembers;
  document.getElementById("mChamber").onchange  = filterMembers;
  document.getElementById("mParty").onchange    = filterMembers;

  const route = () => {
    const h = decodeURIComponent(location.hash.replace(/^#/, ""));
    if (h.startsWith("bill/"))        openBill(h.slice(5));
    else if (h.startsWith("member/")) openMember(h.slice(7));
  };
  window.addEventListener("hashchange", route);
  route();
})();
</script>
</body>
</html>
"""


def build() -> str:
    data = {}
    for label, fname in SESSION_FILES:
        p = pathlib.Path(fname)
        if not p.exists():
            p = pathlib.Path("work") / fname
        if not p.exists():
            raise SystemExit(f"missing data file: {fname} (put it beside this script)")
        data[label] = json.loads(p.read_text(encoding="utf-8"))

    html = TEMPLATE
    missing = set(re.findall(r"\{\{(\w+)\}\}", html)) - set(CONFIG) - {"DATA"}
    if missing:
        raise SystemExit(f"template needs CONFIG keys not present: {sorted(missing)}")
    for k, v in CONFIG.items():
        html = html.replace("{{" + k + "}}", v)
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace("{{DATA}}", blob)
    left = re.findall(r"\{\{\w+\}\}", html)
    if left:
        raise SystemExit(f"unsubstituted tokens remain: {left}")
    return html


if __name__ == "__main__":
    out = OUTPUT
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    html = build()
    pathlib.Path(out).write_text(html, encoding="utf-8")
    print(f"built {out}  {len(html):,} bytes")
