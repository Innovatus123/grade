"""Assemble a PA legislation dataset for Sheet LT-04. One session per run.

    python assemble.py 2025-2026
    python assemble.py 2023-2024
    python assemble.py --all

Inputs  : <raw>/list_page_*.jsonl, <raw>/fix_page_*.jsonl   (bill inventory)
          <raw>/sponsors_*.jsonl                            (sponsor rosters)
          rosters/PA_House_Roster.csv, PA_Senate_Roster.csv (LT-01 snapshot)
Output  : work/legislation_<session>.json                   (sheet payload)
          work/bills_<session>.csv, work/bill_sponsors_<session>.csv
"""
import json, glob, re, csv, os, sys, collections, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
W = os.path.join(ROOT, "work")
os.makedirs(W, exist_ok=True)

# --------------------------------------------------------------- sessions
SESSIONS = {
    "2025-2026": {
        "raw": "raw", "year": "2025", "closed": False,
        "label": "2025-2026 Regular Session (209th and 210th General Assembly)",
        # District numbers under the map in force since 2022-12-01.
        "map_era": "post-2022",
        "inventory_note": "collision",
        # LegiScan reports each member's CURRENT seat. For the sitting session
        # that is also the session seat, so the LT-01 roster is authoritative.
        "roster_is_authoritative": True,
    },
    "2023-2024": {
        "raw": "raw23", "year": "2023", "closed": True,
        "label": "2023-2024 Regular Session (207th and 208th General Assembly)",
        "map_era": "post-2022",
        "inventory_note": "clean",
        "roster_is_authoritative": False,
    },
    "2021-2022": {
        "raw": "raw21", "year": "2021", "closed": True,
        "label": "2021-2022 Regular Session (205th and 206th General Assembly)",
        # Pre-redistricting numbers. The same number describes different ground
        # than it does today, so the current roster's county geography must not
        # be joined onto it.
        "map_era": "pre-2022",
        "inventory_note": "clean",
        "roster_is_authoritative": False,
    },
    "2019-2020": {
        "raw": "raw19", "year": "2019", "closed": True,
        "label": "2019-2020 Regular Session (203rd and 204th General Assembly)",
        "map_era": "pre-2022",
        "inventory_note": "clean",
        "roster_is_authoritative": False,
    },
}

# LegiScan stamps a sponsor with the seat they hold NOW, not the seat they held
# during the session being harvested. For members who changed chamber since, that
# silently misfiles their historical sponsorships under the wrong district.
#
# The tell is a sponsor whose chamber does not match the bill's chamber - in
# Pennsylvania, sponsors and cosponsors are always same-chamber. Where that
# happens, substitute the seat the member actually held during the session.
#
# Verified against Wikipedia and the PA General Assembly member pages:
#   Nick Pisciottano      HD-038  2021-01-05 - 2024-11-30, then SD-45 from 2025-01-07
#   Patty Kim             HD-103  2013 - 2025,             then SD-15 from 2025
#   Dawn Keefer           HD-092  2017 - 2024,             then SD-31 from 2025
#   Lynda Schlegel Culver HD-108  2011 - 2023-02-28,       then SD-27 from 2023-02-28
# Culver moved mid-session, so her 2023-2024 record spans both seats. The bill's
# own chamber resolves which one applies, which is exactly what this rule keys on.
#   Greg Rothman         HD-087  2015 - 2022-11-30,       then SD-34 from 2022-12-01
#   Rosemary M. Brown     HD-189  2011 - 2022-11-30,       then SD-40 from 2022-12-01
#   Frank Farry           HD-142  2009 - 2022-11-30,       then SD-06 from 2022-12-01
#   Tracy Pennycuick      HD-147  2021-01-05 - 2022-11-30, then SD-24 from 2022-12-01
#   Cris Dush             HD-066  2015 - 2020-11-30,       then SD-25 from 2020-12-01
#   Carolyn Comitta       HD-156  2017 - 2020-11-30,       then SD-19 from 2020-12-01
#   Martin Flynn          HD-113  2013 - 2021-06-09,       then SD-22 from 2021-06-09
# Flynn moved mid-2021-22 on a special election, so that session spans both seats;
# again the bill's own chamber resolves which seat applies.
# Districts are pre-2022-redistricting numbers for the 2019-20 and 2021-22 sessions;
# Pennsylvania's new legislative map took effect only for terms beginning 2022-12-01,
# so no number in this table changed between those two sessions.
SEAT_OVERRIDES = {
    "2023-2024": {
        "nick pisciottano": "HD-038",
        "patty kim": "HD-103",
        "dawn keefer": "HD-092",
        "lynda schlegel culver": "HD-108",
    },
    "2021-2022": {
        "nick pisciottano": "HD-038",
        "patty kim": "HD-103",
        "dawn keefer": "HD-092",
        "lynda schlegel culver": "HD-108",
        "greg rothman": "HD-087",
        "rosemary brown": "HD-189",
        "rosemary m. brown": "HD-189",
        "frank farry": "HD-142",
        "tracy pennycuick": "HD-147",
        "martin flynn": "HD-113",
        "marty flynn": "HD-113",
    },
    "2019-2020": {
        "patty kim": "HD-103",
        "dawn keefer": "HD-092",
        "lynda schlegel culver": "HD-108",
        "greg rothman": "HD-087",
        "rosemary brown": "HD-189",
        "rosemary m. brown": "HD-189",
        "frank farry": "HD-142",
        "cris dush": "HD-066",
        "carolyn comitta": "HD-156",
        "martin flynn": "HD-113",
        "marty flynn": "HD-113",
    },
}

TYPE = {"HB": ("House", "Bill"), "SB": ("Senate", "Bill"),
        "HR": ("House", "Resolution"), "SR": ("Senate", "Resolution")}

GBCA_KW = re.compile(
    r"construct|contractor|prevailing wage|procure|public works|mechanics'? lien|"
    r"building code|infrastructur|apprentice|labor|workforce|occupational|"
    r"workers'? compensation|unemployment compensation|bidding|project labor|"
    r"architect|engineer|surety|zoning|municipalities planning|land development|"
    r"building permit|highway|bridge|turnpike|capital budget|school building|"
    r"eminent domain|redevelopment|right-to-know", re.I)


def bill_key(b):
    m = re.match(r"^([A-Z]+)(\d+)$", b)
    return (m.group(1), int(m.group(2)))


def norm_district(chamber, d):
    if not d:
        return ""
    m = re.search(r"(\d+)", str(d))
    if not m:
        return ""
    n = int(m.group(1))
    return ("HD-%03d" % n) if chamber == "House" else ("SD-%02d" % n)


def norm_status(s):
    """2025-26 uses 'Intro 25%'; a closed session uses 'Intro Sine Die', and the
    listing sometimes wraps it in markdown emphasis. Reduce to one vocabulary."""
    s = (s or "").replace("*", "").strip()
    for stem in ("Veto", "Pass", "Engross", "Intro", "N/A"):
        if s.startswith(stem):
            return stem
    return s or "N/A"


# A vetoed measure cleared both chambers, so it ranks with Pass for coverage.
STATUS_RANK = {"N/A": 0, "Intro": 1, "Engross": 2, "Veto": 3, "Pass": 3}


def outcome(status, last_action, closed):
    if re.search(r"Act No\.", last_action or "", re.I):
        return "Enacted"
    if status == "Veto":
        return "Vetoed"
    if status == "Pass":
        return "Adopted" if re.search(r"Adopted", last_action or "", re.I) else "Passed"
    if status == "Engross":
        return "Died after one chamber" if closed else "Passed one chamber"
    if status == "Intro":
        return "Died in committee" if closed else "In committee"
    return "No action"


def committee(last_action):
    m = re.search(r"To (?:House|Senate) (.+?) Committee", last_action or "")
    return m.group(1).strip() if m else ""


def act_no(last_action):
    m = re.search(r"Act No\.\s*([0-9A-Za-z]+)\s*of\s*(\d{4})", last_action or "")
    return f"Act {m.group(1)} of {m.group(2)}" if m else ""


def load_roster():
    """LT-01 snapshot. Geography (counties) is keyed to the district and is stable
    across both sessions - PA's current map took effect in 2022. The *person* in a
    seat is not stable, so name/party/leadership are only trusted for the session
    the roster describes."""
    geo, people = {}, {}
    for path, chamber in ((os.path.join(ROOT, "rosters/PA_House_Roster.csv"), "House"),
                          (os.path.join(ROOT, "rosters/PA_Senate_Roster.csv"), "Senate")):
        if not os.path.exists(path):
            continue
        for row in csv.DictReader(open(path, encoding="utf-8-sig")):
            key = norm_district(chamber, row["district"])
            geo[key] = {"counties": row.get("counties", ""),
                        "residence": row.get("residence", "")}
            people[key] = row
    return geo, people


def build(session):
    cfg = SESSIONS[session]
    raw = os.path.join(ROOT, cfg["raw"])
    closed = cfg["closed"]
    overrides = SEAT_OVERRIDES.get(session, {})
    geo, roster = load_roster()

    # ---------------------------------------------------------- inventory
    bills = {}
    for f in sorted(glob.glob(os.path.join(raw, "list_page_*.jsonl"))) + \
             sorted(glob.glob(os.path.join(raw, "fix_page_*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            b = str(r.get("bill", "")).replace(" ", "").upper()
            if not re.match(r"^(HB|SB|HR|SR)\d+$", b):
                continue
            r["bill"] = b
            prev = bills.get(b)
            if prev is None or len(r.get("title", "")) > len(prev.get("title", "")):
                bills[b] = r

    # ---------------------------------------------------------- sponsors
    sponsors = {}
    for f in sorted(glob.glob(os.path.join(raw, "sponsors_*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if not r.get("ok"):
                continue
            b = str(r.get("bill", "")).replace(" ", "").upper()
            if not re.match(r"^(HB|SB|HR|SR)\d+$", b):
                continue
            # Later harvest waves omit the redundant "chamber" field and carry the
            # chamber only in the district prefix. Normalise so resolve() can rely
            # on it - without this every SD-## sponsor would read as a House member
            # and the mid-session seat correction would never fire.
            for sp in r.get("sponsors", []):
                if not sp.get("chamber"):
                    d = str(sp.get("district", "") or "")
                    sp["chamber"] = "Senate" if d.upper().startswith("S") else "House"
            prev = sponsors.get(b)
            if prev is None or len(r.get("sponsors", [])) > len(prev.get("sponsors", [])):
                sponsors[b] = r

    for b, r in sponsors.items():
        if b not in bills:
            bills[b] = {"bill": b, "status": "", "title": r.get("title", ""),
                        "last_action_date": "", "last_action": "",
                        "recovered_from": "sponsor_page"}

    # ---------------------------------------------------------- join
    members, edges = {}, []
    seat_fix_pairs = set()
    unmatched = collections.Counter()

    def resolve(bill_id, s):
        """Return (district_key, chamber, name, party) with the mid-session seat
        correction applied."""
        bill_chamber = TYPE[bill_key(bill_id)[0]][0]
        rep_chamber = "Senate" if (s.get("chamber") or "").lower().startswith("s") else "House"
        name = (s.get("name") or "").strip()
        party = (s.get("party") or "").strip()[:1].upper()
        key = norm_district(rep_chamber, s.get("district", ""))
        if rep_chamber != bill_chamber:
            fixed = overrides.get(name.lower())
            if fixed:
                # resolve() runs once for the member index and once for the bill
                # index, so count distinct (bill, member) pairs, not calls.
                seat_fix_pairs.add((bill_id, name))
                return fixed, bill_chamber, name, party
            # Chamber conflict with no known override - do not guess a district.
            unmatched[f"{name} (chamber conflict on {bill_id})"] += 1
            return "", bill_chamber, name, party
        return key, rep_chamber, name, party

    PARTY_LONG = {"D": "Democratic", "R": "Republican", "I": "Independent"}

    for b in sorted(sponsors, key=bill_key):
        for s in sponsors[b].get("sponsors", []):
            key, chamber, name, party = resolve(b, s)
            if not key:
                continue
            m = members.get(key)
            if m is None:
                m = members[key] = {
                    "key": key, "chamber": chamber,
                    "district": int(re.search(r"(\d+)", key).group(1)),
                    "name": name, "party": PARTY_LONG.get(party, party),
                    "leadership": "",
                    "counties": (geo.get(key, {}).get("counties", "")
                                 if cfg.get("map_era") != "pre-2022" else ""),
                    "residence": "", "ballot2026": "", "seat_id": "", "person_id": "",
                    "inRoster": False, "prime": [], "co": [],
                    "_names": collections.Counter(),
                }
            m["_names"][name] += 1
            role = "prime" if str(s.get("role", "")).upper().startswith("PRI") else "co"
            m[role].append(b)
            edges.append((b, key, role, name, ""))

    # For the sitting session the LT-01 roster is authoritative; seed every seat
    # from it so members with no sponsorships still appear, and prefer its names.
    if cfg["roster_is_authoritative"]:
        for key, row in roster.items():
            m = members.setdefault(key, {
                "key": key, "chamber": "House" if key.startswith("HD") else "Senate",
                "district": int(re.search(r"(\d+)", key).group(1)),
                "name": "", "party": "", "leadership": "", "counties": "",
                "residence": "", "ballot2026": "", "seat_id": "", "person_id": "",
                "inRoster": False, "prime": [], "co": [], "_names": collections.Counter(),
            })
            m.update({
                "name": row["full_name"], "party": row["party"],
                "leadership": row.get("leadership_role", ""),
                "counties": row.get("counties", ""),
                "residence": row.get("residence", ""),
                "ballot2026": row.get("incumbent_2026_status", ""),
                "seat_id": row.get("seat_id", ""), "person_id": row.get("person_id", ""),
                "inRoster": True,
            })
    else:
        # Historical session: the person comes from the bill record. Take the most
        # frequent spelling seen, and note whether that seat is held by the same
        # person today.
        for key, m in members.items():
            if m["_names"]:
                ranked = m["_names"].most_common()
                m["name"] = ranked[0][0]
                # A seat can change hands mid-session - a resignation and special
                # election, or a member moving to the other chamber. Keying members
                # by seat then folds two people into one row. Rather than hide that,
                # name everyone who sponsored from this seat during the session.
                if len(ranked) > 1:
                    m["sharedSeat"] = [{"name": n, "sponsorships": c} for n, c in ranked]
            # "Who holds this seat now" is only a meaningful statement when the
            # district number still describes the same ground. Under the pre-2022
            # map it does not, so the comparison is suppressed rather than made
            # misleadingly.
            row = roster.get(key) if cfg.get("map_era") != "pre-2022" else None
            m["heldNowBy"] = row["full_name"] if row and row["full_name"] != m["name"] else ""

    for m in members.values():
        m.pop("_names", None)
        m["prime"] = sorted(set(m["prime"]), key=bill_key)
        m["co"] = sorted(set(m["co"]), key=bill_key)

    # ---------------------------------------------------------- shape bills
    out = []
    for b in sorted(bills, key=bill_key):
        rec = bills[b]
        pref, num = bill_key(b)
        chamber, kind = TYPE[pref]
        sp = sponsors.get(b)
        prime, cos = [], []
        if sp:
            for s in sp["sponsors"]:
                key, _c, _n, _p = resolve(b, s)
                if not key:
                    continue
                (prime if str(s.get("role", "")).upper().startswith("PRI") else cos).append(key)
        title = (sp.get("title") if sp and len(sp.get("title", "")) > len(rec.get("title", ""))
                 else rec.get("title", "")) or ""
        st = norm_status(rec.get("status", ""))
        la = rec.get("last_action", "") or ""
        out.append({
            "id": b, "pref": pref, "num": num, "chamber": chamber, "kind": kind,
            "title": title.strip(), "status": st, "rank": STATUS_RANK.get(st, 0),
            "outcome": outcome(st, la, closed), "act": act_no(la),
            "committee": committee(la),
            "lastDate": rec.get("last_action_date", "") or "", "lastAction": la,
            "prime": sorted(set(prime)), "co": sorted(set(cos)),
            "loaded": bool(sp), "gbca": bool(GBCA_KW.search(title)),
            "pa": "https://www.palegis.us/legislation/bills/%s/%s" % (cfg["year"], b.lower()),
            "ls": "https://legiscan.com/PA/bill/%s/%s" % (b, cfg["year"]),
        })

    loaded = sum(1 for x in out if x["loaded"])
    payload = {
        "session": session, "sessionLabel": cfg["label"], "closed": closed,
        "generated": datetime.date.today().isoformat(),
        "rosterIsCurrent": cfg["roster_is_authoritative"],
        "mapEra": cfg.get("map_era", "post-2022"),
        "inventoryNote": cfg.get("inventory_note", "clean"),
        "seatFixes": [{"name": n, "seat": overrides[n.lower()], "n": c}
                      for n, c in collections.Counter(
                          n for _b, n in seat_fix_pairs).most_common()],
        "counts": {
            "bills": len(out), "loaded": loaded, "edges": len(edges),
            "members": len(members),
            "enacted": sum(1 for x in out if x["outcome"] in ("Enacted", "Adopted")),
            "acts": sum(1 for x in out if x["outcome"] == "Enacted"),
            "gbca": sum(1 for x in out if x["gbca"]),
        },
        "bills": out,
        "members": sorted(members.values(), key=lambda m: (m["chamber"], m["district"])),
    }

    json.dump(payload, open(os.path.join(W, "legislation_%s.json" % session), "w"),
              separators=(",", ":"))

    with open(os.path.join(W, "bills_%s.csv" % session), "w", newline="",
              encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["session", "bill", "chamber", "kind", "title", "status", "outcome",
                     "act", "committee", "last_action_date", "last_action",
                     "prime_sponsor_districts", "cosponsor_count", "sponsors_loaded",
                     "gbca_relevant", "pa_url", "legiscan_url"])
        for x in out:
            wr.writerow([session, x["id"], x["chamber"], x["kind"], x["title"], x["status"],
                         x["outcome"], x["act"], x["committee"], x["lastDate"],
                         x["lastAction"], ";".join(x["prime"]), len(x["co"]),
                         x["loaded"], x["gbca"], x["pa"], x["ls"]])

    with open(os.path.join(W, "bill_sponsors_%s.csv" % session), "w", newline="",
              encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["session", "bill", "district_key", "role", "name_on_bill"])
        for e in edges:
            wr.writerow([session, e[0], e[1], e[2], e[3]])

    print(f"--- {session} ---")
    print("  bills          ", len(out))
    print("  sponsors loaded", loaded)
    print("  edges          ", len(edges))
    print("  members        ", len(members))
    print("  enacted/adopted", payload["counts"]["enacted"], " of which Acts:", payload["counts"]["acts"])
    print("  gbca-relevant  ", payload["counts"]["gbca"])
    if payload["seatFixes"]:
        print("  mid-session seat corrections applied:")
        for f in payload["seatFixes"]:
            print(f"     {f['name']}: {f['n']} sponsorships -> {f['seat']}")
    if unmatched:
        print("  UNRESOLVED chamber conflicts:", sum(unmatched.values()))
        for n, c in unmatched.most_common(8):
            print("     ", n, c)
    return payload


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    todo = list(SESSIONS) if ("--all" in sys.argv or not args) else args
    for s in todo:
        if s not in SESSIONS:
            raise SystemExit(f"unknown session {s}; known: {list(SESSIONS)}")
        build(s)
