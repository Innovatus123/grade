"""Politician master crosswalk.

Problem: PA re-issues candidate FILERIDs every election year (2026C0421), and a
single politician files under several vehicles at once - a personal candidate
record, one or more "Friends of" committees, a Philadelphia filer, a federal
committee. Nothing links them.

Key structural discovery: PA candidate filers come in two shapes.
  * Rotating IDs (^\\d{4}C...) carry the politician's OWN name as FILERNAME
    ("KENYATTA, MALCOLM", "JORDAN A. HARRIS").
  * Stable IDs carry the committee name ("FRIENDS OF ANGELA GIROL").
Strip the committee wrapper off the second and it matches the first. That is the
spine of the crosswalk.
"""
import re, os, sys
import pandas as pd, numpy as np
from collections import defaultdict
import jellyfish
from rapidfuzz import fuzz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resolve import parse_person, clean, UF

BASE = os.path.expanduser("~/pafin")
OUT = f"{BASE}/out"

# ------------------------------------------------------------- name extraction
PREFIXES = [
    "THE COMMITTEE TO RETAIN JUDGE", "COMMITTEE TO RETAIN JUDGE", "COMMITTEE TO RE ELECT",
    "COMMITTEE TO REELECT", "COMMITTEE TO ELECT", "THE COMMITTEE TO ELECT",
    "THE FRIENDS OF", "FRIENDS OF", "FRIEND OF", "CITIZENS FOR", "CITIZEN FOR",
    "PEOPLE FOR", "SUPPORTERS FOR", "SUPPORTER FOR", "VOLUNTEERS FOR", "NEIGHBORS FOR",
    "COMMITTEE FOR", "COMMITTEE TO SUPPORT", "RE ELECT", "REELECT", "RETAIN",
    "VOTE FOR", "VOTE", "ELECT", "TEAM", "JUDGE",
]
SUFFIXES = [
    "COMMITTEE TO ELECT", "COMMITTEE TO RE ELECT", "COMMITTEE TO REELECT",
    "FRIENDS OF", "FRIEND OF", "CITIZENS FOR", "PEOPLE FOR", "SUPPORTERS FOR",
    "VOLUNTEERS FOR", "COMMITTEE", "CAMPAIGN COMMITTEE", "ELECTION COMMITTEE",
    "FOR STATE REPRESENTATIVE", "FOR STATE REP", "FOR STATE SENATE", "FOR SENATE",
    "FOR CONGRESS", "FOR GOVERNOR", "FOR JUDGE", "FOR MAYOR", "FOR COUNCIL",
    "FOR DISTRICT ATTORNEY", "FOR DA", "FOR PA", "FOR PENNSYLVANIA", "FOR THE HOUSE",
    "FOR STATE HOUSE", "FOR COMMONWEALTH COURT", "FOR SUPERIOR COURT",
    "FOR SUPREME COURT", "FOR AG", "FOR ATTORNEY GENERAL", "FOR PHILLY",
    "FOR THE NORTHEAST", "FOR WEST PHILLY", "FOR THE 23RD DISTRICT",
]
# Trailing administrative noise seen in the PA filer file
NOISE = re.compile(r"\b(C O\b.*|CO TREASURER.*|TREASURER.*|TTEE|TRUSTEE|INC|LLC|PAC|FUND|"
                   r"CAMPAIGN|COMMITTEE|COM|CMTE|ELECTION|ELECTORAL|POLITICAL|"
                   r"ACTION|VICTORY|EXPLORATORY)\b")
_WS = re.compile(r"\s+")
OFFICE_CLASS = {
    "STH": "PA_HOUSE", "STS": "PA_SENATE", "GOV": "STATEWIDE", "LTG": "STATEWIDE",
    "ATT": "STATEWIDE", "AUD": "STATEWIDE", "TRE": "STATEWIDE", "SPM": "COURT",
    "SPR": "COURT", "CCJ": "COURT", "CPJ": "COURT", "CPJA": "COURT", "CPJP": "COURT",
    "USC": "US_HOUSE", "USS": "US_SENATE", "DSC": "PARTY_CTE", "RSC": "PARTY_CTE",
}


def strip_wrapper(name):
    """Pull the politician's name out of a committee name. Returns ('', reason)
    when the name carries no recoverable person."""
    s = keep_comma(name)
    if not s:
        return "", "EMPTY"
    changed = True
    while changed:
        changed = False
        for p in PREFIXES:
            if s.startswith(p + " "):
                s = s[len(p) + 1:]; changed = True; break
        if changed:
            continue
        for x in SUFFIXES:
            if s.endswith(" " + x):
                s = s[: -(len(x) + 1)]; changed = True; break
    s = NOISE.sub(" ", s)
    # "WECHT 2025" was surviving as a politician name; drop bare election-year and
    # district-number tokens so the surname can fall through to the stage-3 match.
    s = re.sub(r"\b(19|20)\d{2}\b", " ", s)
    s = re.sub(r"\b\d+(ST|ND|RD|TH)?\b", " ", s)
    s = _WS.sub(" ", s).strip()
    if not s:
        return "", "WRAPPER_ONLY"
    toks = s.split()
    # a single token is a surname or a slogan - not enough to identify a person
    if len(toks) < 2:
        return s, "SINGLE_TOKEN"
    return s, "OK"


def keep_comma(s):
    """Normalize but PRESERVE the comma. parse_person() uses the comma to decide
    whether a name is 'LAST, FIRST' or 'FIRST LAST'. Running the comma-stripping
    clean() first silently reversed every FEC name - "FITZPATRICK, BRIAN" parsed
    as first=FITZPATRICK, last=BRIAN, so federal records never matched their PA
    counterparts."""
    if not isinstance(s, str):
        return ""
    t = s.upper().replace("&AMP;", " AND ").replace("&", " AND ").replace(".", " ")
    t = re.sub(r"[^A-Z0-9 ,\-]", " ", t)
    return _WS.sub(" ", t).strip().strip(",").strip()


def office_class(o):
    return OFFICE_CLASS.get(str(o).strip().upper(), "OTHER")


# ==============================================================================
def load_pa():
    f = pd.read_csv(f"{OUT}/pa_filer_master.csv", dtype=str)
    f["OFFICE"] = f.OFFICE.fillna("").str.strip()
    cand = f[f.OFFICE.ne("")].copy()
    cand["FILERNAME"] = cand.FILERNAME.fillna("").str.strip()
    cand["rotating"] = cand.FILERID.str.match(r"^\d{4}[Cc]", na=False)
    ext = [strip_wrapper(n) for n in cand.FILERNAME]
    cand["pol_name_raw"], cand["extract_status"] = zip(*ext)
    # Rotating-ID records USUALLY carry the bare politician name, but not always:
    # 2024C0510 is "CITIZENS FOR JORDAN A. HARRIS". Assuming otherwise forked Jordan
    # Harris into a second politician, so strip_wrapper runs on every record and the
    # rotating flag now only labels provenance.
    cand.loc[cand.rotating, "extract_status"] = np.where(
        cand.loc[cand.rotating, "extract_status"].eq("OK"), "DIRECT",
        cand.loc[cand.rotating, "extract_status"])
    agg = (cand.sort_values("EYEAR")
           .groupby("FILERID")
           .agg(filer_name=("FILERNAME", "last"), pol_name_raw=("pol_name_raw", "last"),
                extract_status=("extract_status", "last"), office=("OFFICE", "last"),
                district=("DISTRICT", "last"), party=("PARTY", "last"),
                county=("COUNTY", "last"), rotating=("rotating", "last"),
                years=("EYEAR", lambda s: ",".join(sorted(set(s)))))
           .reset_index())
    agg["jurisdiction"] = "PA-STATE"
    return agg


def load_phl():
    d = pd.concat([pd.read_csv(f"{BASE}/phl/phl_contrib_{y}.csv", dtype=str, low_memory=False,
                               usecols=["filer_id", "filer_name", "filer_candidate_name",
                                        "candidate_office", "candidate_district_num",
                                        "candidate_party", "office_level", "report_year"])
                   for y in (2024, 2025, 2026)], ignore_index=True)
    d = d[d.filer_candidate_name.notna() | d.candidate_office.notna()]
    if not len(d):
        return pd.DataFrame()
    g = (d.sort_values("report_year").groupby("filer_id")
         .agg(filer_name=("filer_name", "last"),
              cand_name=("filer_candidate_name", "last"),
              office=("candidate_office", "last"),
              district=("candidate_district_num", "last"),
              party=("candidate_party", "last"),
              years=("report_year", lambda s: ",".join(sorted(set(s.dropna())))))
         .reset_index().rename(columns={"filer_id": "FILERID"}))
    nm = g.cand_name.fillna("").str.strip()
    fallback = [strip_wrapper(n)[0] for n in g.filer_name.fillna("")]
    g["pol_name_raw"] = np.where(nm.ne(""), nm.map(lambda s: _WS.sub(" ", keep_comma(s)).strip()),
                                 fallback)
    g["extract_status"] = np.where(nm.ne(""), "PHL_CAND_FIELD", "PHL_WRAPPER")
    g["county"] = "51"; g["rotating"] = False; g["jurisdiction"] = "PHILADELPHIA"
    return g[["FILERID", "filer_name", "pol_name_raw", "extract_status", "office",
              "district", "party", "county", "rotating", "years", "jurisdiction"]]


def load_fec():
    cand = pd.read_csv(f"{BASE}/fec/pa_candidates.csv", dtype=str)
    g = (cand.sort_values("CAND_ELECTION_YR").groupby("CAND_ID")
         .agg(filer_name=("CAND_NAME", "last"), office=("CAND_OFFICE", "last"),
              district=("CAND_OFFICE_DISTRICT", "last"),
              party=("CAND_PTY_AFFILIATION", "last"),
              years=("CAND_ELECTION_YR", lambda s: ",".join(sorted(set(s)))))
         .reset_index().rename(columns={"CAND_ID": "FILERID"}))
    g["office"] = g.office.map({"H": "USC", "S": "USS", "P": "PRE"}).fillna(g.office)
    g["pol_name_raw"] = g.filer_name.map(lambda s: _WS.sub(" ", NOISE.sub(" ", keep_comma(s))).strip())
    g["extract_status"] = "FEC_CAND_NAME"
    g["county"] = ""; g["rotating"] = False; g["jurisdiction"] = "FEDERAL"
    return g[["FILERID", "filer_name", "pol_name_raw", "extract_status", "office",
              "district", "party", "county", "rotating", "years", "jurisdiction"]]


PARTY_NORM = {"DEM": "DEM", "D": "DEM", "DEMOCRATIC": "DEM", "DEMOCRAT": "DEM",
              "REP": "REP", "R": "REP", "REPUBLICAN": "REP", "GOP": "REP"}


def main():
    parts = [load_pa(), load_phl(), load_fec()]
    v = pd.concat([p for p in parts if len(p)], ignore_index=True)
    print(f"candidate filer vehicles: {len(v):,}")
    print(v.extract_status.value_counts().to_string())

    for c in ("office","district","party","county","years","filer_name","pol_name_raw"):  # noqa
        v[c] = v[c].astype(str).replace({"nan": "", "None": ""}).fillna("")
    p = [parse_person(n) for n in v.pol_name_raw]
    v["first"], v["mid"], v["last"], v["suffix"] = zip(*p)
    v["oclass"] = v.office.map(office_class)
    v["party_n"] = v.party.fillna("").str.upper().str.strip().map(PARTY_NORM).fillna("")
    v["yr_list"] = v.years.fillna("").map(lambda s: set(re.findall(r"\d{4}", s)))

    usable = v["first"].str.len().gt(1) & v["last"].str.len().gt(1)
    print(f"\nvehicles with a usable person name: {usable.sum():,} / {len(v):,} "
          f"({usable.mean():.1%})")

    uf = UF(len(v))
    # ---- Stage 1: exact (first, last) --------------------------------------
    sig = defaultdict(list)
    for i in np.where(usable.values)[0]:
        sig[(v["first"].iat[i], v["last"].iat[i])].append(i)
    det = 0
    for grp in sig.values():
        for j in grp[1:]:
            if uf.union(grp[0], j):
                det += 1
    print(f"stage 1 exact-name links: {det:,}")

    # ---- Stage 2: fuzzy within surname blocks ------------------------------
    blocks = defaultdict(list)
    for i in np.where(usable.values)[0]:
        code = jellyfish.metaphone(v["last"].iat[i])[:6]
        if code:
            blocks[code].append(i)
    fz = 0
    conflicts = []
    for idxs in blocks.values():
        if len(idxs) < 2 or len(idxs) > 300:
            continue
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                if uf.find(i) == uf.find(j):
                    continue
                li, lj = v["last"].iat[i], v["last"].iat[j]
                fi, fj = v["first"].iat[i], v["first"].iat[j]
                if fuzz.ratio(li, lj) < 90:
                    continue
                fsim = 100 if fi == fj else (
                    85 if (len(fi) == 1 or len(fj) == 1) and fi[0] == fj[0]
                    else fuzz.ratio(fi, fj))
                if fsim < 88:
                    continue
                mi, mj = v["mid"].iat[i], v["mid"].iat[j]
                if mi and mj and mi != mj:
                    continue
                pi, pj = v.party_n.iat[i], v.party_n.iat[j]
                if pi and pj and pi != pj:
                    conflicts.append((i, j, "PARTY_CONFLICT")); continue
                # same office class in the SAME year with a different district is
                # two different people, not one politician
                oi, oj = v.oclass.iat[i], v.oclass.iat[j]
                di, dj = str(v.district.iat[i]), str(v.district.iat[j])
                shared_yrs = v.yr_list.iat[i] & v.yr_list.iat[j]
                if oi == oj and shared_yrs and di not in ("", "nan", "-1") \
                        and dj not in ("", "nan", "-1") and di != dj:
                    conflicts.append((i, j, "DISTRICT_CONFLICT")); continue
                if uf.union(i, j):
                    fz += 1
    print(f"stage 2 fuzzy links: {fz:,} | blocked by conflict guard: {len(conflicts):,}")

    # ---- Stage 3: single-surname vehicles ----------------------------------
    # "Shapiro for Pennsylvania" and "FITZPATRICK FOR JUDGE" strip down to a bare
    # surname, which stage 1 cannot use. Attach them to a named politician only when
    # exactly one candidate shares that surname AND office class - otherwise leave
    # them standing alone rather than guess.
    named_by = defaultdict(set)
    for i in np.where(usable.values)[0]:
        named_by[(v["last"].iat[i], v.oclass.iat[i])].add(uf.find(i))
    surname_only = (~usable.values) & v.pol_name_raw.str.strip().str.len().gt(1).values
    s3 = amb = 0
    for i in np.where(surname_only)[0]:
        toks = [t for t in re.sub(r"[^A-Z ]", " ", v.pol_name_raw.iat[i].upper()).split() if t]
        if len(toks) != 1:
            continue
        cands = named_by.get((toks[0], v.oclass.iat[i]), set())
        if len(cands) == 1:
            if uf.union(next(iter(cands)), i):
                s3 += 1
        elif len(cands) > 1:
            amb += 1
    print(f"stage 3 surname-only links: {s3:,} | left ambiguous: {amb:,}")

    root = np.array([uf.find(i) for i in range(len(v))])
    v["cluster"] = root
    order = v.assign(_r=v.rotating.astype(int)).sort_values(
        ["cluster", "_r", "pol_name_raw"], ascending=[True, False, True])
    canon = order.drop_duplicates("cluster").set_index("cluster")
    v["politician_name"] = canon.pol_name_raw.reindex(v.cluster).values
    codes, _ = pd.factorize(v.cluster)
    v["politician_id"] = ["P" + str(c + 1).zfill(5) for c in codes]

    print(f"\npoliticians: {v.politician_id.nunique():,} from {len(v):,} filing vehicles")
    multi = v.groupby("politician_id").size()
    print(f"politicians with >1 vehicle: {(multi > 1).sum():,} | max vehicles: {multi.max()}")
    xj = v.groupby("politician_id").jurisdiction.nunique()
    print(f"politicians spanning >1 jurisdiction: {(xj > 1).sum():,}")

    v.to_parquet(f"{OUT}/politician_vehicles.parquet", index=False)

    master = (v.groupby("politician_id")
              .agg(politician_name=("politician_name", "first"),
                   vehicles=("FILERID", "size"),
                   filer_ids=("FILERID", lambda s: " | ".join(sorted(set(str(x) for x in s)))),
                   offices=("office", lambda s: ",".join(sorted(set(str(x) for x in s if str(x).strip())))),
                   office_class=("oclass", lambda s: ",".join(sorted(set(str(x) for x in s)))),
                   districts=("district", lambda s: ",".join(sorted(set(
                       str(x) for x in s if str(x) not in ("", "nan", "-1"))))),
                   party=("party_n", lambda s: ",".join(sorted(set(str(x) for x in s if str(x).strip())))),
                   jurisdictions=("jurisdiction", lambda s: ",".join(sorted(set(str(x) for x in s)))),
                   years=("years", lambda s: ",".join(sorted(set(
                       y for x in s for y in re.findall(r"\d{4}", str(x)))))))
              .reset_index())
    master.to_csv(f"{OUT}/politician_master.csv", index=False)
    cf = pd.DataFrame(conflicts, columns=["i", "j", "reason"])
    if len(cf):
        ia = cf.i.to_numpy(dtype=int); ja = cf.j.to_numpy(dtype=int)
        nm = v.pol_name_raw.to_numpy(); of = v.office.to_numpy(); pt = v.party.to_numpy()
        cf["name_a"], cf["name_b"] = nm[ia], nm[ja]
        cf["office_a"], cf["office_b"] = of[ia], of[ja]
        cf["party_a"], cf["party_b"] = pt[ia], pt[ja]
        cf = cf[["name_a","name_b","reason","office_a","office_b","party_a","party_b"]]
    cf.to_csv(f"{OUT}/politician_conflicts.csv", index=False)
    return v, master


if __name__ == "__main__":
    main()
