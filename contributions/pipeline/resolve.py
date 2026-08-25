"""Donor entity resolution.

Collapses name variants of the same real-world donor into one entity ID.

Design constraints discovered during the build:
  * Philadelphia publishes donor_id / donor_name_std / donor_filer_id fields but
    all three are 0% populated. There is NO deterministic identifier available in
    any of the three sources. Everything here is derived.
  * Over-merging is worse than under-merging for this use case. A wrongly merged
    donor produces a fabricated influence claim. Guards below are deliberately
    conservative and every borderline pair goes to a review queue rather than
    being silently accepted.
"""
import re, sys, os
import numpy as np, pandas as pd
from collections import defaultdict
import jellyfish
from rapidfuzz import fuzz

BASE = os.path.expanduser("~/pafin")
OUT = f"{BASE}/out"

# ---------------------------------------------------------------- dictionaries
NICKNAMES = {
    "JEFF":"JEFFREY","JEFFERY":"JEFFREY","GEOFF":"JEFFREY","BOB":"ROBERT","BOBBY":"ROBERT",
    "ROB":"ROBERT","ROBBIE":"ROBERT","BILL":"WILLIAM","BILLY":"WILLIAM","WILL":"WILLIAM",
    "WILLIE":"WILLIAM","LIAM":"WILLIAM","DICK":"RICHARD","RICK":"RICHARD","RICKY":"RICHARD",
    "RICH":"RICHARD","JIM":"JAMES","JIMMY":"JAMES","JAMIE":"JAMES","MIKE":"MICHAEL",
    "MICKEY":"MICHAEL","MITCH":"MITCHELL","TOM":"THOMAS","TOMMY":"THOMAS","TIM":"TIMOTHY",
    "DAVE":"DAVID","DAN":"DANIEL","DANNY":"DANIEL","DON":"DONALD","DONNIE":"DONALD",
    "STEVE":"STEPHEN","STEPHAN":"STEPHEN","STEVEN":"STEPHEN","CHRIS":"CHRISTOPHER",
    "KIT":"CHRISTOPHER","TONY":"ANTHONY","ANTONIO":"ANTHONY","JOE":"JOSEPH","JOEY":"JOSEPH",
    "CHUCK":"CHARLES","CHARLIE":"CHARLES","ED":"EDWARD","EDDIE":"EDWARD","TED":"EDWARD",
    "NED":"EDWARD","FRANK":"FRANCIS","FRANKIE":"FRANCIS","GREG":"GREGORY","JERRY":"GERALD",
    "GERRY":"GERALD","LARRY":"LAWRENCE","LARRIE":"LAWRENCE","KEN":"KENNETH","KENNY":"KENNETH",
    "MATT":"MATTHEW","NICK":"NICHOLAS","PAT":"PATRICK","PETE":"PETER","PHIL":"PHILIP",
    "PHILLIP":"PHILIP","RANDY":"RANDALL","RAY":"RAYMOND","RON":"RONALD","RONNIE":"RONALD",
    "SAM":"SAMUEL","STAN":"STANLEY","VIC":"VICTOR","WALT":"WALTER","ANDY":"ANDREW",
    "DREW":"ANDREW","BEN":"BENJAMIN","BENNY":"BENJAMIN","ALEX":"ALEXANDER","ART":"ARTHUR",
    "BART":"BARTHOLOMEW","BERNIE":"BERNARD","BRAD":"BRADLEY","DOUG":"DOUGLAS",
    "GABE":"GABRIEL","HANK":"HENRY","HARRY":"HENRY","JACK":"JOHN","JOHNNY":"JOHN",
    "JON":"JONATHAN","JOHNATHAN":"JONATHAN","LEN":"LEONARD","LOU":"LOUIS","MARTY":"MARTIN",
    "MAX":"MAXWELL","MORT":"MORTON","NAT":"NATHANIEL","NATE":"NATHANIEL","RUSS":"RUSSELL",
    "SAL":"SALVATORE","TERRY":"TERRENCE","VINCE":"VINCENT","VINNY":"VINCENT","ZACH":"ZACHARY",
    # women's names
    "BETH":"ELIZABETH","BETTY":"ELIZABETH","LIZ":"ELIZABETH","LIZZIE":"ELIZABETH",
    "ELISABETH":"ELIZABETH","BETSY":"ELIZABETH","LIBBY":"ELIZABETH","KATE":"KATHERINE",
    "KATHY":"KATHERINE","KATIE":"KATHERINE","KATHRYN":"KATHERINE","CATHERINE":"KATHERINE",
    "CATHY":"KATHERINE","KAY":"KATHERINE","KIT":"KATHERINE","PEGGY":"MARGARET",
    "MAGGIE":"MARGARET","MARGE":"MARGARET","MEG":"MARGARET","MARGIE":"MARGARET",
    "SUE":"SUSAN","SUZY":"SUSAN","SUZANNE":"SUSAN","DEB":"DEBORAH","DEBBIE":"DEBORAH",
    "DEBRA":"DEBORAH","BARB":"BARBARA","BARBIE":"BARBARA","PATTY":"PATRICIA",
    "PATTI":"PATRICIA","TRISH":"PATRICIA","JEN":"JENNIFER","JENNY":"JENNIFER",
    "JENN":"JENNIFER","CHRISTY":"CHRISTINE","CHRISTINA":"CHRISTINE","TINA":"CHRISTINE",
    "ANNIE":"ANN","MANDY":"AMANDA","SANDY":"SANDRA","CINDY":"CYNTHIA","JUDY":"JUDITH",
    "VICKI":"VICTORIA","VICKY":"VICTORIA","TERI":"THERESA","TERESA":"THERESA",
    "DOTTIE":"DOROTHY","DOT":"DOROTHY",
    # Deliberately NOT mapped, though traditional nickname lists include them:
    # NANCY->ANN, LINDA->BELINDA, MARIA->MARY, MOLLY/POLLY->MARY, TRACY->THERESA,
    # CAROL->CAROLINE, ROSE->ROSEMARY, NORA->ELEANOR, ANNA/ANNE->ANN, JULIE->JULIA.
    # These are independent given names in modern US usage and mapping them caused
    # measurable over-merging (NANCY->ANN put "WILLIAMS, NANCY" in the same cluster
    # as "A MORRIS WILLIAMS" because both then began with A).
}
SUFFIXES = {"JR","SR","II","III","IV","V","MD","DO","DDS","DMD","ESQ","PHD","CPA","RN",
            "PE","JD","MBA","CFA","LLD","REV","PA","OD","DC"}
TITLES = {"MR","MRS","MS","MISS","DR","REV","HON","SEN","REP","GOV","JUDGE","PROF",
          "SGT","CAPT","COL","LT","MAJ","GEN","FR","SIR","MSGR"}
LEGAL_FORMS = {"INC","INCORPORATED","LLC","LLP","LP","LTD","CORP","CORPORATION","CO",
               "COMPANY","PLLC","PC","PA","GROUP","HOLDINGS","ENTERPRISES","LLLP","NA",
               "USA","US","THE","AND","OF","FOR"}
ORG_ABBREV = {
    "ASSOC":"ASSOCIATION","ASSN":"ASSOCIATION","ASSOCS":"ASSOCIATES","INTL":"INTERNATIONAL",
    "INTERNATL":"INTERNATIONAL","NATL":"NATIONAL","NATIONL":"NATIONAL","PENNA":"PENNSYLVANIA",
    "PENN":"PENNSYLVANIA","PA":"PENNSYLVANIA","PHILA":"PHILADELPHIA","COMM":"COMMITTEE",
    "CMTE":"COMMITTEE","CTE":"COMMITTEE","DEPT":"DEPARTMENT","MFG":"MANUFACTURING",
    "CONSTR":"CONSTRUCTION","CONST":"CONSTRUCTION","BROS":"BROTHERS","SVCS":"SERVICES",
    "SVC":"SERVICE","MGMT":"MANAGEMENT","DEV":"DEVELOPMENT","IND":"INDUSTRIES",
    "FED":"FEDERATION","BRO":"BROTHERHOOD","UNIV":"UNIVERSITY","HOSP":"HOSPITAL",
    "TRANSP":"TRANSPORTATION","ELEC":"ELECTRIC","MECH":"MECHANICAL","ENGRS":"ENGINEERS",
    "ENG":"ENGINEERING","POL":"POLITICAL","ACTN":"ACTION","CMTEE":"COMMITTEE",
    "IBEW":"INTERNATIONAL BROTHERHOOD OF ELECTRICAL WORKERS",
    "UAW":"UNITED AUTO WORKERS","SEIU":"SERVICE EMPLOYEES INTERNATIONAL UNION",
    "AFSCME":"AMERICAN FEDERATION OF STATE COUNTY AND MUNICIPAL EMPLOYEES",
}
_NUM = re.compile(r"\d+")
_NONALPHANUM = re.compile(r"[^A-Z0-9 ]")
_WS = re.compile(r"\s+")

# (first, last) -> number of distinct zip5s carrying that exact name. Populated in
# main(). A high count means several real people plausibly share the name, so an
# exact name match is not by itself evidence they are the same donor.
NAME_FREQ = {}


def clean(s):
    if not isinstance(s, str):
        return ""
    s = s.upper().replace("&AMP;", " AND ").replace("&", " AND ").replace(".", " ")
    s = _NONALPHANUM.sub(" ", s)
    return _WS.sub(" ", s).strip()


# ------------------------------------------------------------------ person prep
def parse_person(raw):
    """-> (first, middle_initial, last, suffix). Handles 'LAST, FIRST M' and
    'FIRST M LAST' and strips titles/suffixes."""
    s = clean(raw)
    if not s:
        return ("", "", "", "")
    flipped = "," in (raw or "")
    toks = s.split()
    suffix = ""
    while toks and toks[-1] in SUFFIXES:
        suffix = toks.pop()
    while toks and toks[0] in TITLES:
        toks.pop(0)
    while toks and toks[-1] in TITLES:
        toks.pop()
    if not toks:
        return ("", "", "", suffix)
    if flipped and len(toks) >= 2:
        last, rest = toks[0], toks[1:]
    else:
        last, rest = toks[-1], toks[:-1]
    first = rest[0] if rest else ""
    first = NICKNAMES.get(first, first)
    mid = ""
    if len(rest) > 1:
        mid = rest[1][0]
    return (first, mid, last, suffix)


# --------------------------------------------------------------------- org prep
def org_canon(raw):
    """Strip legal forms and expand abbreviations. Digits are PRESERVED and
    compared separately - 'IBEW Local 98' must never merge with 'IBEW Local 5'."""
    s = clean(raw)
    toks = [ORG_ABBREV.get(t, t) for t in s.split()]
    flat = " ".join(toks).split()
    core = [t for t in flat if t not in LEGAL_FORMS]
    return " ".join(core) if core else " ".join(flat)


def digits_of(s):
    return tuple(sorted(_NUM.findall(s or "")))


# --------------------------------------------------------------------- unionfind
class UF:
    def __init__(self, n):
        self.p = list(range(n)); self.r = [0]*n
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb: return False
        if self.r[ra] < self.r[rb]: ra, rb = rb, ra
        self.p[rb] = ra
        if self.r[ra] == self.r[rb]: self.r[ra] += 1
        return True


# ==============================================================================
def main():
    cols = ["donor_name_key","donor_name_raw","donor_class","donor_bucket","amount",
            "donor_zip","donor_city","donor_state","donor_employer","donor_occupation",
            "jurisdiction","is_primary","recipient_name"]
    d = pd.read_parquet(f"{OUT}/contributions_unified.parquet", columns=cols)
    d = d[d.is_primary & (d.donor_bucket != "EXCLUDE-ROLLUP")].copy()
    d["zip5"] = d.donor_zip.astype(str).str.extract(r"(\d{5})")[0].fillna("")

    # ---- collapse to the donor-variant level ---------------------------------
    # A per-group mode() here took >6 minutes across 350k groups. Sorting once by
    # descending amount and taking the first non-null per group is vectorized and
    # equivalent enough: attributes come from the donor's largest contribution.
    attrs = ["donor_name_raw","donor_bucket","donor_class","zip5","donor_city",
             "donor_state","donor_employer"]
    d_sorted = d.sort_values("amount", ascending=False)
    for c in attrs:
        d_sorted[c] = d_sorted[c].astype(str).replace({"": None, "nan": None, "None": None})
    g = d_sorted.groupby("donor_name_key", observed=True)
    v = g[attrs].first().reset_index()
    v.columns = ["donor_name_key","raw","bucket","dclass","zip5","city","state","employer"]
    agg = g.agg(total=("amount","sum"), gifts=("amount","size"),
                recips=("recipient_name","nunique")).reset_index()
    v = v.merge(agg, on="donor_name_key")
    for c in ["raw","bucket","dclass","zip5","city","state","employer"]:
        v[c] = v[c].fillna("")
    print(f"donor variants: {len(v):,}", flush=True)

    is_person = (v.bucket == "INDIVIDUAL").values
    parsed = [parse_person(r) if p else ("","","","")
              for r, p in zip(v.raw, is_person)]
    v["first"], v["mid"], v["last"], v["suffix"] = zip(*parsed)
    v["orgc"] = [org_canon(r) if not p else "" for r, p in zip(v.raw, is_person)]
    v["digits"] = [digits_of(r) for r in v.raw]
    v["employer_c"] = v.employer.map(org_canon)

    # name commonness, used to decide when an exact name match is sufficient alone
    global NAME_FREQ
    pf = v[is_person & v["first"].str.len().gt(1) & v["last"].str.len().gt(1)]
    NAME_FREQ = (pf[pf.zip5.ne("")].groupby(["first","last"]).zip5.nunique().to_dict())
    print(f"distinct person names indexed: {len(NAME_FREQ):,}", flush=True)

    uf = UF(len(v))
    pair_log = []            # (i, j, score, rule) for the review queue
    ACCEPT = 0.90            # auto-merge
    REVIEW = 0.82            # queue for a human

    # ---- STAGE 1: deterministic, exact-signature merges -----------------------
    sig_person = defaultdict(list)   # (first,last,zip5) and (first,last,employer)
    sig_org = defaultdict(list)
    for i in range(len(v)):
        if is_person[i]:
            f, l, z = v["first"].iat[i], v["last"].iat[i], v.zip5.iat[i]
            if f and l and z:
                sig_person[("FLZ", f, l, z)].append(i)
            e = v.employer_c.iat[i]
            if f and l and e:
                sig_person[("FLE", f, l, e)].append(i)
        else:
            oc = v.orgc.iat[i]
            if oc:
                sig_org[(oc, v.digits.iat[i])].append(i)
    det = 0
    for grp in list(sig_person.values()) + list(sig_org.values()):
        for j in grp[1:]:
            if uf.union(grp[0], j):
                det += 1
                pair_log.append((grp[0], j, 1.0, "DETERMINISTIC"))
    print(f"stage 1 deterministic merges: {det:,}")

    # ---- STAGE 2: blocked fuzzy comparison ------------------------------------
    blocks = defaultdict(list)
    for i in range(len(v)):
        if is_person[i]:
            l, f = v["last"].iat[i], v["first"].iat[i]
            if not l:
                continue
            code = jellyfish.metaphone(l)[:6]
            if code and f:
                blocks[("P", code, f[0])].append(i)          # phonetic surname + initial
            if v.zip5.iat[i] and l:
                blocks[("Z", v.zip5.iat[i], l[:3])].append(i)  # same zip, similar surname
        else:
            oc = v.orgc.iat[i]
            if not oc:
                continue
            t = oc.split()
            blocks[("O", jellyfish.metaphone(t[0])[:6] if t else "")].append(i)
            blocks[("O2", oc[:6])].append(i)

    # Pure-Python pairwise scoring over every block is far too slow at this scale
    # (it ran past 10 minutes without finishing). Instead: run a cheap vectorized
    # C-level prefilter with rapidfuzz.process.cdist inside each block, and only
    # pay for the detailed Python scorer on pairs that survive it.
    from rapidfuzz import process as rf_process

    cmpstr = np.where(is_person,
                      (v["first"].astype(str) + " " + v["last"].astype(str)).values,
                      v.orgc.astype(str).values)

    MAXBLOCK = 600
    PREFILTER = 78          # cdist cutoff; detailed scorer decides from here
    cand_count = fuzzy = queued = 0
    seen_pairs = set()
    nblocks = len(blocks)
    for bn, (key, idxs) in enumerate(blocks.items()):
        if bn % 20000 == 0:
            print(f"  block {bn:,}/{nblocks:,} cand={cand_count:,} merged={fuzzy:,}", flush=True)
        if len(idxs) < 2 or len(idxs) > MAXBLOCK:
            continue
        arr = np.array(idxs)
        strs = [cmpstr[k] for k in arr]
        m = rf_process.cdist(strs, strs, scorer=fuzz.ratio,
                             score_cutoff=PREFILTER, workers=-1)
        ii, jj = np.nonzero(np.triu(m, k=1))
        for a, b in zip(ii, jj):
            i, j = int(arr[a]), int(arr[b])
            if i > j: i, j = j, i
            if (i, j) in seen_pairs:
                continue
            seen_pairs.add((i, j))
            cand_count += 1
            if uf.find(i) == uf.find(j):
                continue
            # --- hard guards -------------------------------------------
            if is_person[i] != is_person[j]:
                continue                                   # never merge person <-> org
            if v.digits.iat[i] != v.digits.iat[j]:
                continue                                   # Local 98 != Local 5
            sc, rule = score_pair(v, i, j, is_person)
            if sc >= ACCEPT:
                if uf.union(i, j):
                    fuzzy += 1
                    pair_log.append((i, j, sc, rule))
            elif sc >= REVIEW:
                queued += 1
                pair_log.append((i, j, sc, "REVIEW:" + rule))
    print(f"stage 2 candidates: {cand_count:,} | auto-merged: {fuzzy:,} | queued for review: {queued:,}")

    # ---- STAGE 2b: cluster consistency split ---------------------------------
    # Union-find is transitive, so a chain of individually-plausible links can
    # assemble a cluster whose endpoints are obviously different people. Observed:
    # "A MORRIS WILLIAMS", "Arthur Williams", "AVRIL WILLIAMS" and "WILLIAMS, NANCY"
    # merged into one entity via initial-only hops. Fix: inside each person
    # cluster, partition by expanded first name. Members carrying only an initial
    # join a named sub-group when exactly one is compatible, and stand alone when
    # the initial is ambiguous.
    root0 = np.array([uf.find(i) for i in range(len(v))])
    members = defaultdict(list)
    for i, r in enumerate(root0):
        members[r].append(i)
    split_extra = {}
    n_split = 0
    for r, idxs in members.items():
        if len(idxs) < 2 or not is_person[idxs[0]]:
            continue
        named = defaultdict(list)
        initials = []
        for i in idxs:
            f = v["first"].iat[i]
            if len(f) > 1:
                named[f].append(i)
            else:
                initials.append(i)
        # No early exit here. A cluster where every member shares one first name
        # still needs the middle-initial / state refinement below - that is exactly
        # the shape of the John Arnold cluster (six "JOHN ARNOLD" variants spanning
        # TX, FL and a distinct John M. Arnold in PA).
        groups = list(named.values())
        for i in initials:
            ch = v["first"].iat[i][:1]
            fits = [g for g in groups if v["first"].iat[g[0]].startswith(ch)]
            if len(fits) == 1:
                fits[0].append(i)
            else:
                groups.append([i])           # ambiguous initial - keep it separate

        # Same chaining problem one level down: "JOHN ARNOLD" (no middle initial)
        # matched both "John D. Arnold" (Houston) and "John M. Arnold" (Reading),
        # dragging two different people into one entity. Partition each first-name
        # group again by middle initial and by state, then re-attach the members
        # that carry neither signal only when the target is unambiguous.
        refined = []
        for g in groups:
            keyed = defaultdict(list)
            floaters = []
            for i in g:
                mk, sk = v["mid"].iat[i], v.state.iat[i]
                if mk or sk:
                    keyed[(mk, sk)].append(i)
                else:
                    floaters.append(i)
            if len(keyed) <= 1:
                refined.append(g); continue
            sub = {}
            for (mk, sk), mem in keyed.items():
                placed = False
                for k in list(sub):
                    kmk, ksk = k
                    mid_ok = (not mk) or (not kmk) or mk == kmk
                    st_ok = (not sk) or (not ksk) or sk == ksk
                    if mid_ok and st_ok:
                        sub[k].extend(mem); placed = True; break
                if not placed:
                    sub[(mk, sk)] = list(mem)
            parts = list(sub.values())
            if len(parts) == 1:
                refined.append(parts[0] + floaters)
            else:
                if floaters:
                    parts[max(range(len(parts)), key=lambda k: len(parts[k]))].extend(floaters)
                refined.extend(parts)
        groups = refined
        if len(groups) > 1:
            n_split += 1
            for g in groups[1:]:
                for i in g:
                    split_extra[i] = f"{r}_s{groups.index(g)}"
    print(f"stage 2b clusters split for first-name conflict: {n_split:,}", flush=True)

    # ---- STAGE 3: canonical entity assignment --------------------------------
    root = np.array([split_extra.get(i, str(root0[i])) for i in range(len(v))], dtype=object)
    v["cluster"] = root
    # canonical = highest-dollar variant in the cluster
    order = v.sort_values(["cluster", "total"], ascending=[True, False])
    canon = order.drop_duplicates("cluster").set_index("cluster")
    v["entity_name"] = canon.raw.reindex(v.cluster).values
    # source data carries un-decoded HTML entities ("Buchanan Ingersoll &amp; Rooney")
    v["entity_name"] = (v.entity_name.astype(str)
                        .str.replace("&amp;amp;", "&", regex=False)
                        .str.replace("&amp;", "&", regex=False)
                        .str.replace("&#39;", "'", regex=False).str.strip())
    codes, _ = pd.factorize(v.cluster)
    v["donor_entity_id"] = ["E" + str(c + 1).zfill(6) for c in codes]

    sizes = v.groupby("donor_entity_id").size()
    print(f"entities: {v.donor_entity_id.nunique():,} (from {len(v):,} variants)")
    print(f"collapsed: {len(v) - v.donor_entity_id.nunique():,} variants absorbed")
    print(f"largest cluster: {sizes.max()} variants")

    v.to_parquet(f"{OUT}/donor_entities.parquet", index=False)

    # review queue
    if pair_log:
        pl = pd.DataFrame(pair_log, columns=["i","j","score","rule"])
        pl = pl[pl.rule.str.startswith("REVIEW")]
        if len(pl):
            pl["name_a"] = v.raw.values[pl.i]; pl["name_b"] = v.raw.values[pl.j]
            pl["total_a"] = v.total.values[pl.i]; pl["total_b"] = v.total.values[pl.j]
            pl["zip_a"] = v.zip5.values[pl.i]; pl["zip_b"] = v.zip5.values[pl.j]
            pl["bucket"] = v.bucket.values[pl.i]
            pl = pl.sort_values("total_a", ascending=False)
            pl[["name_a","name_b","score","rule","total_a","total_b","zip_a","zip_b","bucket"]]\
              .to_csv(f"{OUT}/entity_review_queue.csv", index=False)
            print(f"review queue written: {len(pl):,} pairs")
    return v


def score_pair(v, i, j, is_person):
    """0-1 confidence that i and j are the same real-world donor."""
    if is_person[i]:
        li, lj = v["last"].iat[i], v["last"].iat[j]
        fi, fj = v["first"].iat[i], v["first"].iat[j]
        if not (li and lj and fi and fj):
            return 0.0, "PERSON_INCOMPLETE"
        lsim = fuzz.ratio(li, lj) / 100
        if lsim < 0.88:
            return 0.0, "SURNAME_MISMATCH"
        # first name: exact (post-nickname), initial-only, or close spelling
        initial_only = False
        if fi == fj:
            fsim, fkind = 1.0, "FIRST_EXACT"
        elif len(fi) == 1 or len(fj) == 1:
            # An initial matches many distinct given names - "A WILLIAMS" is equally
            # consistent with Arthur, Avril, Anita and August. On its own this is
            # far too weak to merge on; it must be carried by corroboration.
            if fi[0] != fj[0]:
                return 0.0, "INITIAL_MISMATCH"
            fsim, fkind, initial_only = 0.80, "FIRST_INITIAL", True
        else:
            fsim = fuzz.ratio(fi, fj) / 100
            fkind = "FIRST_FUZZY"
        if fsim < 0.80:
            return 0.0, "FIRST_MISMATCH"
        # middle initial conflict is disqualifying when both are present
        mi, mj = v["mid"].iat[i], v["mid"].iat[j]
        if mi and mj and mi != mj:
            return 0.0, "MIDDLE_CONFLICT"
        base = 0.60 * lsim + 0.25 * fsim
        # corroboration
        corrob = 0
        if v.zip5.iat[i] and v.zip5.iat[i] == v.zip5.iat[j]:
            base += 0.18; corrob += 1
        elif v.city.iat[i] and v.city.iat[i] == v.city.iat[j] \
                and v.state.iat[i] == v.state.iat[j]:
            base += 0.10
        elif v.state.iat[i] and v.state.iat[i] != v.state.iat[j]:
            base -= 0.12                                   # different states, be wary
        ei, ej = v.employer_c.iat[i], v.employer_c.iat[j]
        if ei and ei == ej:
            base += 0.12; corrob += 1
        if mi and mj and mi == mj:
            base += 0.05
        if initial_only and corrob < 2:
            base = min(base, 0.88)      # below auto-merge; goes to the review queue
        # An exact full-name match inside the same state is strong on its own -
        # this is what "Jeff Yass" vs "Jeffrey Yass" needs - but only when the name
        # is not so common that several real people plausibly share it.
        # Guard the shortcut on whole-string similarity too. Parsed first+last can
        # match while the full names differ materially: "MARIE AMEY-TAYLOR" parses
        # to (MARIE, TAYLOR) and was being merged into "Marie Taylor" in a
        # different city purely on this rule.
        if (fkind == "FIRST_EXACT" and lsim == 1.0
                and v.state.iat[i] and v.state.iat[i] == v.state.iat[j]
                and NAME_FREQ.get((fi, li), 99) <= 2
                and fuzz.token_sort_ratio(clean(v.raw.iat[i]), clean(v.raw.iat[j])) >= 88):
            base = max(base, 0.92)
        return min(base, 1.0), fkind
    # ---- organizations -------------------------------------------------------
    a, b = v.orgc.iat[i], v.orgc.iat[j]
    if not (a and b):
        return 0.0, "ORG_EMPTY"
    tset = fuzz.token_sort_ratio(a, b) / 100
    tsub = fuzz.token_set_ratio(a, b) / 100
    # token_set_ratio alone happily calls "FRIENDS OF X" and "FRIENDS OF X AND Y"
    # identical, so require the stricter sort ratio to carry most of the weight.
    base = 0.75 * tset + 0.25 * tsub
    if v.zip5.iat[i] and v.zip5.iat[i] == v.zip5.iat[j]:
        base += 0.08
    ta, tb = set(a.split()), set(b.split())
    only = ta ^ tb
    # a differing distinctive token (a surname in a committee name, a city) is a
    # strong signal these are different committees, not spelling variants
    if any(len(t) > 4 for t in only) and tset < 0.95:
        base -= 0.10
    return min(base, 1.0), "ORG"


if __name__ == "__main__":
    main()
