import json, re, sys
from playwright.sync_api import sync_playwright

PATH = "file:///root/legis/PA_Legislation_Map.html"
fails, notes = [], []

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    pg = b.new_page()
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(PATH, wait_until="load")
    pg.wait_for_timeout(1500)

    if errs:
        fails.append("JS errors: " + " | ".join(errs[:5]))

    # stat strip populated
    stats = pg.eval_on_selector_all(".stat .n", "els=>els.map(e=>e.textContent)")
    notes.append("stats: " + ", ".join(stats))
    if len(stats) != 7:
        fails.append("stat strip has %d tiles, expected 7" % len(stats))

    # bill table rendered
    rows = pg.eval_on_selector_all("#billBody tr", "e=>e.length")
    notes.append("first page rows: %d" % rows)
    if rows < 100:
        fails.append("bill table rendered only %d rows" % rows)

    cnt = pg.inner_text("#billCount")
    notes.append("count line: " + cnt)

    # open a bill that has sponsors
    pg.evaluate("openBill('HB2400')")
    pg.wait_for_timeout(400)
    if not pg.is_visible("#drawer.on"):
        fails.append("drawer did not open for HB2400")
    dt = pg.inner_text("#dbody")
    notes.append("HB2400 drawer chars: %d" % len(dt))
    sp = pg.eval_on_selector_all("#dbody .slist li", "e=>e.length")
    notes.append("HB2400 sponsor rows: %d" % sp)
    if sp == 0:
        fails.append("HB2400 shows no sponsor roster")
    if "Pennsylvania General Assembly" not in dt:
        fails.append("bill drawer missing General Assembly link")

    # click a sponsor -> member drawer
    if sp:
        pg.eval_on_selector("#dbody .slist li", "e=>e.click()")
        pg.wait_for_timeout(400)
        md = pg.inner_text("#dbody").lower()   # CSS uppercases the h3 headings
        notes.append("member drawer chars: %d" % len(md))
        if "prime sponsor" not in md and "cosponsored" not in md:
            fails.append("member drawer missing bill lists")
        mb = pg.eval_on_selector_all("#dbody .slist li", "e=>e.length")
        notes.append("member bill rows: %d" % mb)
        if mb == 0:
            fails.append("member drawer lists no bills")
        # click back to a bill
        pg.eval_on_selector("#dbody .slist li", "e=>e.click()")
        pg.wait_for_timeout(400)
        if "open the record" not in pg.inner_text("#dbody").lower():
            fails.append("member -> bill round trip failed")

    pg.evaluate("closeDrawer()")

    # unloaded bill shows the honest notice
    unl = pg.evaluate("(D.bills.find(b=>!b.loaded)||{}).id")
    if unl:
        pg.evaluate("openBill('%s')" % unl)
        pg.wait_for_timeout(300)
        if "not been harvested" not in pg.inner_text("#dbody"):
            fails.append("unloaded bill %s missing coverage notice" % unl)
        notes.append("unloaded sample: " + unl)
        pg.evaluate("closeDrawer()")

    # search
    pg.fill("#q", "prevailing wage")
    pg.wait_for_timeout(600)
    notes.append("search 'prevailing wage': " + pg.inner_text("#billCount"))
    pg.fill("#q", "")
    pg.wait_for_timeout(400)

    # filter chip
    pg.click("#cGbca")
    pg.wait_for_timeout(600)
    notes.append("industry filter: " + pg.inner_text("#billCount"))
    pg.click("#cGbca")
    pg.wait_for_timeout(300)

    # members tab
    pg.click("#tab-members")
    pg.wait_for_timeout(700)
    mrows = pg.eval_on_selector_all("#memBody tr", "e=>e.length")
    notes.append("member rows: %d / %s" % (mrows, pg.inner_text("#memCount")))
    if mrows < 100:
        fails.append("members tab rendered %d rows" % mrows)

    # method tab
    pg.click("#tab-method")
    pg.wait_for_timeout(400)
    mt = pg.inner_text("#methodBody")
    notes.append("method chars: %d" % len(mt))
    if len(mt) < 1500:
        fails.append("method tab looks empty")

    # deep link
    pg.goto(PATH + "#bill/SB704", wait_until="load")
    pg.wait_for_timeout(1500)
    if not pg.is_visible("#drawer.on"):
        fails.append("deep link #bill/SB704 did not open the drawer")
    else:
        notes.append("deep link ok: " + pg.inner_text("#dhead").split("\n")[0])

    # ---- second session ----
    pg.goto(PATH, wait_until="load"); pg.wait_for_timeout(1500)
    opts = pg.eval_on_selector_all("#sessionSel option", "e=>e.map(x=>x.value)")
    notes.append("sessions: " + ", ".join(opts))
    if len(opts) < 2:
        fails.append("session selector has %d options" % len(opts))
    else:
        pg.select_option("#sessionSel", opts[1])
        pg.wait_for_timeout(1800)
        st2 = pg.eval_on_selector_all(".stat .n", "e=>e.map(x=>x.textContent)")
        notes.append("%s stats: %s" % (opts[1], ", ".join(st2)))
        if st2 == stats:
            fails.append("switching session did not change the stat strip")
        c2 = pg.inner_text("#billCount")
        notes.append("%s count: %s" % (opts[1], c2))
        # a bill that only exists in the historical session
        pg.evaluate("openBill('HB1300')")
        pg.wait_for_timeout(400)
        if pg.is_visible("#drawer.on"):
            d2 = pg.inner_text("#dbody")
            notes.append("%s bill drawer chars: %d" % (opts[1], len(d2)))
            if "/2023" not in pg.eval_on_selector_all("#dbody a", "e=>e.map(x=>x.href)")[1]:
                fails.append("historical bill links do not point at the 2023 session")
            pg.evaluate("closeDrawer()")
        # seat correction: Pisciottano must sit in HD-038 for 2023-24, not SD-45
        chk = pg.evaluate("(()=>{const m=M['HD-038']; return m? m.name+'|'+(m.prime.length+m.co.length) : 'MISSING';})()")
        notes.append("2023-24 HD-038: " + chk)
        if "Pisciottano" not in chk:
            fails.append("seat correction failed: HD-038 is %s" % chk)
        sd45 = pg.evaluate("(()=>{const m=M['SD-45']; return m? m.name+'|'+(m.heldNowBy||'') : 'MISSING';})()")
        notes.append("2023-24 SD-45: " + sd45)
        if "Brewster" not in sd45:
            fails.append("SD-45 should be the 2023-24 senator (Brewster), got %s" % sd45)
        if "Pisciottano" not in sd45:
            fails.append("SD-45 does not name its current occupant")
        shared = pg.evaluate("(()=>{const m=M['HD-108']; return m && m.sharedSeat ? m.sharedSeat.map(x=>x.name).join('+') : 'NONE';})()")
        notes.append("2023-24 HD-108 shared seat: " + shared)
        if "Culver" not in shared:
            fails.append("HD-108 does not disclose the mid-session handover")
        # method tab should carry the closed-session language
        pg.click("#tab-method"); pg.wait_for_timeout(400)
        mt2 = pg.inner_text("#methodBody")
        if "closed session" not in mt2.lower():
            fails.append("method tab missing closed-session note for %s" % opts[1])
        if "Pisciottano" not in mt2:
            fails.append("method tab does not disclose the seat correction")
        notes.append("%s method chars: %d" % (opts[1], len(mt2)))

    # ---- the two pre-2022-map sessions ----
    for sess in ("2021-2022", "2019-2020"):
        pg.goto(PATH, wait_until="load"); pg.wait_for_timeout(1500)
        pg.select_option("#sessionSel", sess)
        pg.wait_for_timeout(2500)
        st = pg.eval_on_selector_all(".stat .n", "e=>e.map(x=>x.textContent)")
        notes.append("%s stats: %s" % (sess, ", ".join(st)))
        if len(st) != 7 or st[0] in ("0", ""):
            fails.append("%s stat strip did not populate" % sess)
        n = pg.eval_on_selector_all("#billBody tr", "e=>e.length")
        notes.append("%s rows: %d / %s" % (sess, n, pg.inner_text("#billCount")))
        if n < 100:
            fails.append("%s rendered %d bill rows" % (sess, n))

        # a vetoed measure must exist, carry the Vetoed outcome, and be styled
        vet = pg.evaluate("(D.bills.find(b=>b.outcome==='Vetoed')||{}).id")
        notes.append("%s veto sample: %s" % (sess, vet))
        if not vet:
            fails.append("%s has no Vetoed measure - the Veto status stem is not parsed" % sess)
        else:
            pg.evaluate("openBill('%s')" % vet)
            pg.wait_for_timeout(400)
            if not pg.is_visible("#dbody .p-Vetoed"):
                fails.append("%s vetoed bill %s is missing the Vetoed pill" % (sess, vet))
            pg.evaluate("closeDrawer()")
        if "Vetoed" not in pg.eval_on_selector_all("#fOutcome option", "e=>e.map(x=>x.value)"):
            fails.append("%s outcome filter does not offer Vetoed" % sess)

        # pre-2022 map: county geography and "held now by" must be suppressed
        cty = pg.evaluate("D.members.filter(m=>m.counties).length")
        hnb = pg.evaluate("D.members.filter(m=>m.heldNowBy).length")
        notes.append("%s members with counties: %d, with heldNowBy: %d" % (sess, cty, hnb))
        if cty:
            fails.append("%s joins current-map county geography onto pre-2022 districts (%d members)" % (sess, cty))
        if hnb:
            fails.append("%s claims a current occupant for pre-2022 district numbers (%d members)" % (sess, hnb))

        # method tab must disclose the map change and list the seat corrections
        pg.click("#tab-method"); pg.wait_for_timeout(500)
        mt = pg.inner_text("#methodBody")
        notes.append("%s method chars: %d" % (sess, len(mt)))
        if "not today's districts" not in mt and "not today’s districts" not in mt:
            fails.append("%s method tab does not disclose the pre-2022 map" % sess)
        fixes = pg.evaluate("(D.seatFixes||[]).length")
        notes.append("%s seat corrections: %d" % (sess, fixes))
        if fixes < 5:
            fails.append("%s applied only %d seat corrections" % (sess, fixes))
        for who in ("Rothman", "Farry"):
            if who not in mt:
                fails.append("%s method tab omits corrected member %s" % (sess, who))
        pg.click("#tab-bills"); pg.wait_for_timeout(300)

    # 2019-20 specific: Cris Dush sat in the House that session, not SD-25
    pg.goto(PATH, wait_until="load"); pg.wait_for_timeout(1500)
    pg.select_option("#sessionSel", "2019-2020"); pg.wait_for_timeout(2500)
    dush = pg.evaluate("(()=>{const m=M['HD-066']; return m? m.name+'|'+(m.prime.length+m.co.length):'MISSING';})()")
    notes.append("2019-20 HD-066: " + dush)
    if "Dush" not in dush:
        fails.append("2019-20 seat correction failed: HD-066 is %s" % dush)
    if pg.evaluate("!!M['SD-025']"):
        fails.append("2019-20 still files House sponsorships under SD-025")

    # index page
    pg.goto("file:///root/legis/index.html", wait_until="load")
    pg.wait_for_timeout(400)
    cards = pg.eval_on_selector_all(".card h2", "e=>e.map(x=>x.textContent)")
    notes.append("index cards: " + ", ".join(cards))
    if len(cards) != 4:
        fails.append("index has %d cards, expected 4" % len(cards))
    hrefs = pg.eval_on_selector_all(".card .open", "e=>e.map(x=>x.getAttribute('href'))")
    notes.append("index links: " + ", ".join(hrefs))
    if "PA_Legislation_Map.html" not in hrefs:
        fails.append("index does not link to the new sheet")

    b.close()

print("\n".join("  " + n for n in notes))
print()
if fails:
    print("FAIL")
    for f in fails:
        print(" -", f)
    sys.exit(1)
print("PASS - all checks green")
