"""PAC sponsor tracing — layer 4 of the contributions pipeline.

Pennsylvania bars direct corporate contributions to candidates (25 P.S. 3253), so
corporate money reaches candidates only through a PAC. Donor names at state level
therefore almost never say "corporation" — the influence is real but invisible
unless each PAC is traced back to the organization or person behind it. This
module does that: it identifies which recipients in the unified dataset are
themselves PACs (not candidates), and assigns each one a sponsor — the company,
union, or person that stands behind it.

Two source tiers, in precedence order:
  1. FEC-declared sponsor (CONNECTED_ORG_NM / ORG_TP on the committee record) —
     the only authoritative sponsor data in any of the three sources, guarded
     against free-text noise (see `fec_seed`).
  2. Derived sponsor — for PACs with no FEC match, strip the PAC wrapper off the
     committee's own name and classify what's left by type and industry.

Inputs (standard pipeline layout):
  ~/pafin/out/contributions_unified.parquet  — from build.py (PA-state + Philadelphia
                                                 + FEC individual/PAC-to-candidate rows)
  ~/pafin/fec/cm.txt                          — FEC committee master (bulk download)
  ~/pafin/fec/itoth.txt                       — FEC "any transaction from one
                                                 committee to another" (bulk download,
                                                 ~1.8 GB uncompressed; this is the "2GB
                                                 FEC download" the pipeline refresh
                                                 notes are timed against)

Output: sponsor_detail.csv, sponsor_totals.csv, sponsor_types_and_QA.csv, all
in ~/pafin/out/. `chains.py` reads sponsor_detail.csv as one of its inputs.
"""
import os, re
import numpy as np, pandas as pd
from classify import norm, classify, rollup

BASE = os.path.expanduser("~/pafin")
OUT = f"{BASE}/out"
FEC = f"{BASE}/fec"

CM_COLS = ["CMTE_ID", "CMTE_NM", "TRES_NM", "CMTE_ST1", "CMTE_ST2", "CMTE_CITY",
           "CMTE_ST", "CMTE_ZIP", "CMTE_DSGN", "CMTE_TP", "CMTE_PTY_AFFILIATION",
           "CMTE_FILING_FREQ", "ORG_TP", "CONNECTED_ORG_NM", "CAND_ID"]
# Same 21-column Schedule A shape build.py's FEC_COLS already documents; itoth.txt
# uses it too — the "other committee" name/ID ride in NAME / OTHER_ID.
ITOTH_COLS = ["CMTE_ID", "AMNDT_IND", "RPT_TP", "TRANSACTION_PGI", "IMAGE_NUM",
              "TRANSACTION_TP", "ENTITY_TP", "NAME", "CITY", "STATE", "ZIP_CODE",
              "EMPLOYER", "OCCUPATION", "TRANSACTION_DT", "TRANSACTION_AMT",
              "OTHER_ID", "TRAN_ID", "FILE_NUM", "MEMO_CD", "MEMO_TEXT", "SUB_ID"]

# ------------------------------------------------------- PAC-name wrapper strip --
# Applied to a committee's OWN name to recover the sponsor when FEC has no
# CONNECTED_ORG_NM on file. Order matters: strip the longest/most specific
# wrappers first so "... STATE & LOCAL FUND" doesn't leave "STATE & LOCAL" stuck
# on the front of the next pass.
PAC_WRAPPERS = [
    r"\bPOLITICAL ACTION (TOGETHER )?(POLITICAL )?COMMITTEE\b", r"\bGOVERNMENT COMMITTEE\b",
    r"\bSTATE (AND|&) LOCAL FUND\b", r"\bFEDERAL (AND|&) STATE FUND\b",
    r"\bSTATE PAC\b", r"\bFEDERAL PAC\b", r"\bLEGISLATIVE (ACTION|IMPROVEMENT) (COMMITTEE|FUND)\b",
    r"\bCOMMITTEE ON POLITICAL EDUCATION\b", r"\bCOPE\b", r"\bGOOD GOVERNMENT (FUND|COMMITTEE)\b",
    r"\(P\.?A\.?C\.?\)", r"\bP\.?A\.?C\.?\b", r"\bPOLITICAL ACTION COMMITTEE\b",
    r"\bPOLITICAL COMMITTEE\b", r"\bPOLITICAL FUND\b", r"\bVICTORY FUND\b",
    r"\bLEADERSHIP FUND\b", r"\bBALLOT (ISSUES?|MEASURE) COMMITTEE\b",
]
_WRAP = re.compile("|".join(PAC_WRAPPERS))
_PAREN = re.compile(r"\([^)]*\)")
_WS = re.compile(r"\s+")
_LEADING_CONNECTOR = re.compile(r"^(OF|FOR|THE|AND)\b\s*")


def strip_pac_wrapper(name):
    """'DUANE MORRIS GOVERNMENT COMMITTEE STATE & LOCAL FUND' -> 'DUANE MORRIS'."""
    if not isinstance(name, str) or not name.strip():
        return ""
    s = name.upper().strip()
    s = _PAREN.sub(" ", s)
    prev = None
    while prev != s:
        prev = s
        s = _WRAP.sub(" ", s)
    s = _LEADING_CONNECTOR.sub("", _WS.sub(" ", s).strip())
    return s.strip()


# ------------------------------------------------------------- industry rules ---
# Ordered most-specific-first. A committee/sponsor name is tested top to bottom;
# first match wins. Regex uses \S* / explicit plurals rather than a bare \b...\b —
# the pipeline's own validation caught a defect where `\bCARPENTER\b` silently
# failed to match "CARPENTERS" and undercounted an entire industry by 3.7x (see
# README_pac_sponsor_tracing.md, "Defects found in validation" #1). Every trade
# token below is deliberately written to match its own plural.
INDUSTRY_RULES = [
    ("Building trades labor", re.compile(
        r"\bCARPENTERS?\b|\bBUILDING (AND |& )?CONSTRUCTION TRADES?\b|\bIRONWORKERS?\b|"
        r"\bOPERATING ENGINEERS?\b|\bLABORERS?\b|\bPLUMBERS?\b|\bSTEAMFITTERS?\b|"
        r"\bPIPEFITTERS?\b|\bELECTRICAL WORKERS?\b|\bIBEW\b|\bBRICKLAYERS?\b|"
        r"\bROOFERS?\b|\bSHEET ?METAL WORKERS?\b|\bPAINTERS?\b|\bBOILERMAKERS?\b|"
        r"\bINSULATORS?\b|\bELEVATOR CONSTRUCTORS?\b|\bTEAMSTERS?\b|\bUNION LOCAL\b|"
        r"\bBUILDING TRADES\b|\bTRADES COUNCIL\b")),
    ("Public sector labor", re.compile(
        r"\bAFSCME\b|\bSTATE ?,? ?COUNTY (AND|&) MUNICIPAL\b|\bTEACHERS?\b|\bFEDERATION OF TEACHERS?\b|"
        r"\bEDUCATION ASSOCIATION\b|\bPSEA\b|\bPOLICE (BENEVOLENT|OFFICERS?)\b|"
        r"\bFIREFIGHTERS?\b|\bSTATE TROOPERS?\b|\bCORRECTIONS? OFFICERS?\b|\bPUBLIC EMPLOYEES?\b")),
    ("Legal services", re.compile(
        r"\bLAW (FIRM|OFFICES?|GROUP)\b|\bATTORNEYS?\b|\bLLP\b|\bTRIAL LAWYERS?\b|"
        r"\bBAR ASSOCIATION\b|\bJUSTICE (FOR ALL|PAC)\b|\bLEGAL\b")),
    ("Construction contracting", re.compile(
        r"\bCONTRACTORS?\b|\bBUILDERS?\b|\bGENERAL CONTRACT|\bCONSTRUCTION (CO|COMPANY|INC|GROUP|CORP)?\b|"
        r"\bBUILDING CONTRACTORS?\b|\bMASTER BUILDERS?\b|\bABC PAC\b|\bAGC\b")),
    ("Real estate / development", re.compile(
        r"\bREALTORS?\b|\bREAL ESTATE\b|\bREALTY\b|\bDEVELOPERS?\b|\bDEVELOPMENT (CO|GROUP|CORP)\b|"
        r"\bPROPERTY (MANAGEMENT|OWNERS?)\b|\bAPARTMENT ASSOCIATION\b|\bHOME ?BUILDERS?\b")),
    ("Finance / insurance", re.compile(
        r"\bBANK(ERS)?\b|\bINSURANCE\b|\bCREDIT UNION\b|\bFINANCIAL\b|\bSECURITIES\b|"
        r"\bINVESTMENT\b|\bCAPITAL PARTNERS?\b|\bASSET MANAGEMENT\b")),
    ("Healthcare", re.compile(
        r"\bHOSPITAL\b|\bMEDICAL (ASSOCIATION|SOCIETY|CENTER)\b|\bNURSES?\b|\bPHYSICIANS?\b|"
        r"\bDENTAL\b|\bHEALTH ?CARE\b|\bPHARMAC")),
    ("Energy / utilities", re.compile(
        r"\bELECTRIC (COMPANY|POWER|UTILITY)\b|\bENERGY\b|\bGAS (COMPANY|ASSOCIATION)\b|"
        r"\bUTILIT(Y|IES)\b|\bPIPELINE\b|\bOIL (AND|&) GAS\b|\bNUCLEAR\b|\bSOLAR\b")),
    ("Education", re.compile(
        r"\bSCHOOL (BOARD|DISTRICT)\b|\bUNIVERSITY\b|\bCOLLEGE\b|\bSTUDENTS? FIRST\b|"
        r"\bEDUCATION (CHOICE|REFORM|FUND)\b|\bCHARTER SCHOOLS?\b")),
]


def classify_industry(name):
    n = (name or "").upper()
    for label, rx in INDUSTRY_RULES:
        if rx.search(n):
            return label
    return "Unclassified"


# ------------------------------------------------------------------- FEC seed ---
def fec_seed():
    """FEC committee master -> {CMTE_ID: (connected_org, org_tp)} after the
    coherence guard.

    FEC filers sometimes use CONNECTED_ORG_NM as free text rather than a true
    sponsor — validation caught a state party listing "PROTECT THE HOUSE 2024" as
    its connected org, which misattributed a real committee's money to a sponsor
    named "DEATON". The field is trusted only when ORG_TP is populated (a
    declared SSF) or the sponsor name shares a substantive (len > 3) token with
    the committee's own name.
    """
    rows = []
    with open(f"{FEC}/cm.txt", encoding="latin-1") as f:
        for line in f:
            rows.append(dict(zip(CM_COLS, line.rstrip("\n").split("|"))))
    cm = pd.DataFrame(rows)

    org = cm.CONNECTED_ORG_NM.fillna("").str.strip()
    org_tp_ok = cm.ORG_TP.fillna("").str.strip().ne("")

    def shares_token(a, b):
        ta = {t for t in re.split(r"[^A-Z0-9]+", a.upper()) if len(t) > 3}
        tb = {t for t in re.split(r"[^A-Z0-9]+", b.upper()) if len(t) > 3}
        return bool(ta & tb)

    name_ok = [shares_token(o, n) for o, n in zip(org, cm.CMTE_NM.fillna(""))]
    coherent = org_tp_ok | pd.Series(name_ok, index=cm.index)
    rejected = int((org.ne("") & ~coherent).sum())
    print(f"FEC seed: {int((org.ne('') & coherent).sum()):,} committees with a coherent "
          f"CONNECTED_ORG_NM, {rejected:,} rejected by the coherence guard")

    cm["sponsor"] = np.where(org.ne("") & coherent, org, "")
    cm["sponsor_industry"] = [classify_industry(o) if o else "" for o in cm.sponsor]
    return cm.set_index("CMTE_ID")[["CMTE_NM", "CMTE_ST", "CMTE_TP", "ORG_TP", "sponsor",
                                     "sponsor_industry"]]


# -------------------------------------------------- PAC universe + own receipts --
def pac_receipts_from_unified():
    """Rows of the unified dataset whose RECIPIENT is a PAC, not a candidate —
    i.e. contributions_unified.parquet filtered the other way from every other
    layer in this pipeline. Every other script asks "who did this PAC give to";
    this asks "who gave to this PAC"."""
    path = f"{OUT}/contributions_unified.parquet"
    if not os.path.exists(path):
        print(f"(no {path} — skipping the PA-state/Philadelphia layer; "
              "FEC-only sponsor tracing will still run)")
        return pd.DataFrame(columns=["recipient_key", "recipient_name", "jurisdiction",
                                      "donor_name_raw", "donor_class", "amount"])
    cols = ["recipient_filer_id", "recipient_name", "recipient_type", "jurisdiction",
            "donor_name_raw", "donor_class", "donor_bucket", "amount", "is_primary"]
    d = pd.read_parquet(path, columns=cols)
    # Report rollup/placeholder lines ("UNITEMIZED MONETARY CONTRIBUTIONS", "NON
    # PENNSYLVANIA RECEIPTS", "TRANSFER") are not donors — build.py's own
    # README documents these carrying $83.1M and reads as fabricated mega-donors
    # if left in. classify.py already stamps them donor_bucket=EXCLUDE-ROLLUP;
    # the sponsor/chain layer must honor that exclusion same as every other layer.
    d = d[d.is_primary & (d.donor_bucket != "EXCLUDE-ROLLUP") & d.recipient_type.isin(
        ["Political Committee", "Other PAC", "Union", "Unknown"])].copy()
    d["recipient_key"] = d.jurisdiction.astype(str) + ":" + d.recipient_filer_id.astype(str)
    return d[["recipient_key", "recipient_name", "jurisdiction", "donor_name_raw",
              "donor_class", "amount"]]


def pac_receipts_from_fec_oth(cm):
    """FEC itoth.txt — committee-to-committee (and org-to-committee) receipts.
    Not part of build.py's load_fec(), which only loads individual and
    PAC-to-candidate rows; this is the piece that makes federal PAC funding
    chains visible at all."""
    path = f"{FEC}/itoth.txt"
    if not os.path.exists(path):
        print(f"(no {path} — skipping the FEC committee-to-committee layer)")
        return pd.DataFrame(columns=["recipient_key", "recipient_name", "jurisdiction",
                                      "donor_name_raw", "donor_class", "amount"])
    d = pd.read_csv(path, sep="|", header=None, names=ITOTH_COLS, dtype=str,
                     encoding="latin-1", on_bad_lines="skip")
    d["amount"] = pd.to_numeric(d.TRANSACTION_AMT, errors="coerce").fillna(0)
    d = d[d.amount > 0].copy()
    d["recipient_name"] = cm.CMTE_NM.reindex(d.CMTE_ID).fillna(d.CMTE_ID).values
    cls = [classify(n, entity_tp=et) for n, et in zip(d.NAME, d.ENTITY_TP)]
    d["donor_class"] = [c[0] for c in cls]
    d = d[[rollup(c) != "EXCLUDE-ROLLUP" for c in d.donor_class]]
    d["recipient_key"] = "FEDERAL:" + d.CMTE_ID
    d["jurisdiction"] = "FEDERAL"
    d["donor_name_raw"] = d.NAME.fillna("").str.strip()
    return d[["recipient_key", "recipient_name", "jurisdiction", "donor_name_raw",
              "donor_class", "amount"]]


def main():
    cm = fec_seed()
    receipts = pd.concat(
        [pac_receipts_from_unified(), pac_receipts_from_fec_oth(cm)], ignore_index=True)
    receipts = receipts[receipts.donor_name_raw.str.len() > 0]
    print(f"PAC receipt rows: {len(receipts):,} across "
          f"{receipts.recipient_key.nunique():,} recipient committees")

    pacs = (receipts.groupby(["recipient_key", "recipient_name", "jurisdiction"],
                              as_index=False).amount.sum()
                     .rename(columns={"amount": "total_receipts"}))
    pacs["fec_id"] = pacs.recipient_key.where(pacs.jurisdiction == "FEDERAL", "").str.replace(
        "FEDERAL:", "", regex=False)
    seed = cm[["sponsor", "sponsor_industry", "ORG_TP"]]
    pacs = pacs.merge(seed, left_on="fec_id", right_index=True, how="left")
    pacs["sponsor"] = pacs.sponsor.fillna("")
    pacs["sponsor_industry"] = pacs.sponsor_industry.fillna("")

    # ---- derived sponsor for everything the FEC seed didn't cover -------------
    no_fec = pacs.sponsor.eq("")
    derived = pacs.loc[no_fec, "recipient_name"].map(strip_pac_wrapper)
    # A stripped name that collapsed to nothing, or didn't change at all (no PAC
    # wrapper token present), is not a usable derived sponsor — leave it UNKNOWN
    # rather than emit noise ("PA ALLIANCE ACTION" style names deliberately land
    # here, not misclassified as a trade association — see classify.py's own
    # ADVOCACY_NAME_RULE ordering note for the sibling bug this mirrors).
    same_as_original = derived.str.upper() == pacs.loc[no_fec, "recipient_name"].str.upper()
    derived = derived.where(~same_as_original & derived.str.len().gt(2), "")
    pacs.loc[no_fec, "sponsor"] = derived
    pacs.loc[no_fec, "sponsor_industry"] = derived.map(
        lambda s: classify_industry(s) if s else "")

    pacs["sponsor_source"] = np.select(
        [~no_fec, no_fec & pacs.sponsor.ne("")],
        ["FEC_CONNECTED_ORG", "DERIVED_NAME_STRIP"], default="UNKNOWN")
    pacs["sponsor_type"] = np.where(pacs.sponsor.eq(""), "UNKNOWN", "SPONSORED")

    n_sponsored = int(pacs.sponsor.ne("").sum())
    print(f"PACs with a resolved sponsor: {n_sponsored:,} / {len(pacs):,} "
          f"(${pacs.loc[pacs.sponsor.ne(''), 'total_receipts'].sum():,.0f})")

    detail = receipts.merge(
        pacs[["recipient_key", "sponsor", "sponsor_industry", "sponsor_source",
              "sponsor_type"]], on="recipient_key", how="left")
    detail = detail.rename(columns={"recipient_name": "pac_name"})

    totals = (pacs[pacs.sponsor.ne("")]
              .groupby("sponsor", as_index=False)
              .agg(pacs_sponsored=("recipient_key", "nunique"),
                   total_given=("total_receipts", "sum"))
              .sort_values("total_given", ascending=False))

    qa = pd.DataFrame({
        "metric": ["PAC receipt rows", "Recipient committees", "Committees with FEC-seeded sponsor",
                   "Committees with derived sponsor", "Committees with unknown sponsor",
                   "Total $ with a resolved sponsor"],
        "value": [len(receipts), len(pacs), int((pacs.sponsor_source == "FEC_CONNECTED_ORG").sum()),
                  int((pacs.sponsor_source == "DERIVED_NAME_STRIP").sum()),
                  int((pacs.sponsor_source == "UNKNOWN").sum()),
                  pacs.loc[pacs.sponsor.ne(""), "total_receipts"].sum()],
    })

    os.makedirs(OUT, exist_ok=True)
    detail.to_csv(f"{OUT}/sponsor_detail.csv", index=False)
    totals.to_csv(f"{OUT}/sponsor_totals.csv", index=False)
    qa.to_csv(f"{OUT}/sponsor_types_and_QA.csv", index=False)
    pacs.to_parquet(f"{OUT}/pac_sponsors.parquet", index=False)  # chains.py's input
    print(qa.to_string(index=False))
    return pacs, detail


if __name__ == "__main__":
    main()
