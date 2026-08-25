"""Donor entity classifier — shared across PA state, Philadelphia, and FEC sources.

The central problem: NONE of the three jurisdictions reliably publishes a
corporate-vs-individual flag on the contribution record. This module derives it
and stamps every row with the method and confidence used, so downstream analysis
can filter on classification quality.
"""
import re

# --- token dictionaries -------------------------------------------------------

PAC_TOKENS = [
    r"\bPAC\b", r"POLITICAL ACTION", r"\bP\.?A\.?C\.?\b", r"\bCOMMITTEE\b", r"\bCOMM\b",
    r"FRIENDS OF", r"\bFRIENDS\b", r"CITIZENS FOR", r"COMMITTEE TO ELECT", r"\bELECT\b",
    r"\bFOR (CONGRESS|SENATE|HOUSE|GOVERNOR|MAYOR|COUNCIL)\b", r"VICTORY FUND",
    r"LEADERSHIP FUND", r"\bCOPE\b", r"\bDRIVE\b", r"\bABC PAC\b", r"\bFUND\b",
]
PARTY_TOKENS = [
    r"\bDEMOCRATIC\b", r"\bDEMOCRAT\b", r"\bREPUBLICAN\b", r"\bGOP\b", r"\bPARTY\b",
    r"\bWARD\b", r"\bDNC\b", r"\bRNC\b", r"\bDCCC\b", r"\bNRCC\b", r"\bDSCC\b", r"\bNRSC\b",
    r"\bHRCC\b", r"\bHDCC\b", r"\bSRCC\b", r"\bSDCC\b",
]
UNION_TOKENS = [
    r"\bUNION\b", r"\bLOCAL\s*\d", r"\bIBEW\b", r"\bUAW\b", r"\bAFL[- ]?CIO\b", r"\bAFSCME\b",
    r"\bSEIU\b", r"\bTEAMSTERS\b", r"\bLABORERS\b", r"\bCARPENTERS\b", r"\bPLUMBERS\b",
    r"\bSTEAMFITTERS\b", r"\bOPERATING ENGINEERS\b", r"\bBUILDING TRADES\b", r"\bBRICKLAYERS\b",
    r"\bIRONWORKERS\b", r"\bROOFERS\b", r"\bSHEET METAL\b", r"\bPAINTERS\b", r"\bELEVATOR\b",
    r"\bINSULATORS\b", r"\bBOILERMAKERS\b", r"\bLABOR\b", r"\bCOUNCIL\s*\d",
]
CORP_TOKENS = [
    r"\bINC\b", r"\bINC\.", r"\bLLC\b", r"\bL\.L\.C\.", r"\bLLP\b", r"\bLP\b", r"\bL\.P\.",
    r"\bCORP\b", r"\bCORPORATION\b", r"\bCOMPANY\b", r"\bCO\.\b", r"\bLTD\b", r"\bPLLC\b",
    r"\bP\.C\.\b", r"\bHOLDINGS\b", r"\bPARTNERS\b", r"\bPARTNERSHIP\b", r"\bGROUP\b",
    r"\bENTERPRISES\b", r"\bINDUSTRIES\b", r"\bASSOCIATES\b", r"\bASSOCIATION\b", r"\bASSOC\b",
    r"\bSOCIETY\b", r"\bFOUNDATION\b", r"\bINSTITUTE\b", r"\bTRUST\b", r"\bBANK\b",
    r"\bCONSTRUCTION\b", r"\bCONTRACTING\b", r"\bCONTRACTORS\b", r"\bBUILDERS\b",
    r"\bDEVELOPMENT\b", r"\bREALTY\b", r"\bPROPERTIES\b", r"\bINSURANCE\b", r"\bSERVICES\b",
    r"\bSYSTEMS\b", r"\bSOLUTIONS\b", r"\bTECHNOLOG", r"\bHOSPITAL\b", r"\bUNIVERSITY\b",
    r"\bCOLLEGE\b", r"\bLODGE\b", r"\bCLUB\b", r"\bCHAMBER\b", r"\bALLIANCE\b", r"\bCOALITION\b",
    r"\bENERGY\b", r"\bPHARMA", r"\bCAPITAL\b", r"\bEQUITY\b", r"\bMANAGEMENT\b", r"\bELECTRIC\b",
    r"\bMECHANICAL\b", r"\bSUPPLY\b", r"\bMOTORS\b", r"\bFARMS\b", r"\bRESTAURANT\b",
]
# Political-org names that carry no legal-form or PAC token (super PACs, 501c4s,
# advocacy vehicles). Caught in validation: "AMERICAN OPPORTUNITY ACTION" was
# being scored INDIVIDUAL because nothing in its name looked organizational.
ADVOCACY_TOKENS = [
    r"\bACTION\b", r"\bAMERICANS? FOR\b", r"\bPENNSYLVANIANS? FOR\b", r"\bPEOPLE FOR\b",
    r"\bPROSPERITY\b", r"\bGROWTH\b", r"\bFORWARD\b", r"\bPROJECT\b", r"\bNETWORK\b",
    r"\bLEAGUE\b", r"\bVOTERS?\b", r"\bTURNOUT\b", r"\bMAJORITY\b", r"\bVALUES\b",
    r"\bFUTURE\b", r"\bUNITED\b", r"\bADVOCACY\b", r"\bREFORM\b", r"\bLIBERTY\b",
    r"\bFREEDOM\b", r"\bWORKING FAMILIES\b", r"\bCONSERVATIVE\b", r"\bPROGRESS",
]
# Report rollup / placeholder lines that are NOT donors. Excluding these matters:
# they carried ~$49M in the 2024-2026 window and would otherwise be counted as
# individual mega-donors.
AGGREGATE_TOKENS = [
    r"^TOTAL\b", r"\bUNITEMIZED\b", r"\bANONYMOUS\b", r"\bMISCELLANEOUS\b", r"^VARIOUS\b",
    r"^AGGREGATE\b", r"^SEE ATTACHED", r"^N ?/? ?A$", r"^NONE$", r"^UNKNOWN$",
    r"^NO CONTRIBUTIONS", r"^SMALL CONTRIBUTIONS", r"^OTHER CONTRIBUTIONS",
    # Inter-account reporting lines found after entity resolution surfaced them as
    # top-20 "donors". These carried $33.6M and are transfers/summaries, not gifts.
    r"\bNON ?PA ACTIVITY\b", r"\bNON.?PENNSYLVANIA\b", r"\bFROM FEC REPORT\b",
    r"^FEDERAL CONTRIBUTIONS?\b", r"^FEDERAL PAC RECEIPTS\b", r"\bRECEIPTS$",
    r"^TRANSFER\b", r"^CONTRIBUTIONS FROM\b", r"^OTHER RECEIPTS?\b",
    r"^INTEREST\b", r"^REFUND\b", r"^RETURNED\b", r"^ADJUSTMENT\b",
    r"^BEGINNING BALANCE\b", r"^SUBTOTAL\b", r"^GRAND TOTAL\b", r"^PRIOR YEAR\b",
]

PERSON_SUFFIX = r"(,\s*(JR|SR|II|III|IV|MD|DO|DDS|ESQ|PHD|CPA|RN|PE|JD)\.?)$"

_PAC = re.compile("|".join(PAC_TOKENS))
_PARTY = re.compile("|".join(PARTY_TOKENS))
_UNION = re.compile("|".join(UNION_TOKENS))
_CORP = re.compile("|".join(CORP_TOKENS))
_ADVOCACY = re.compile("|".join(ADVOCACY_TOKENS))
_AGG = re.compile("|".join(AGGREGATE_TOKENS))
_SUFFIX = re.compile(PERSON_SUFFIX)
_NONALPHA = re.compile(r"[^A-Z0-9 ]")
_WS = re.compile(r"\s+")

CLASSES = ["INDIVIDUAL", "CORPORATE_ENTITY", "PAC_COMMITTEE", "UNION", "PARTY",
           "CANDIDATE_SELF", "OTHER", "AGGREGATE_ROLLUP", "UNRESOLVED"]


def norm(name):
    """Normalized donor key for cross-jurisdiction matching."""
    if not isinstance(name, str):
        return ""
    s = name.upper().replace("&AMP;", "&").strip()
    s = _NONALPHA.sub(" ", s)
    return _WS.sub(" ", s).strip()


def looks_like_person(raw):
    """Heuristic: does this string read as a natural person's name?"""
    if not isinstance(raw, str) or not raw.strip():
        return False
    s = raw.upper().strip()
    if _SUFFIX.search(s):
        return True
    core = _NONALPHA.sub(" ", s)
    toks = [t for t in core.split() if t]
    if not (2 <= len(toks) <= 4):
        return False
    if any(len(t) == 1 for t in toks):   # middle initial
        return True
    if "," in s and len(toks) <= 3:      # "LAST, FIRST"
        return True
    return len(toks) in (2, 3)


def classify(name, *, source_flag=None, schedule_hint=None, entity_tp=None,
             employer=None, occupation=None, filer_names=None):
    """Return (donor_class, method, confidence 0-1).

    Precedence: explicit source flag > FEC entity type > registered-filer match
    > organizational name tokens > schedule hint > employer/occupation presence
    > name shape > UNRESOLVED.
    """
    n = norm(name)
    if not n:
        return "UNRESOLVED", "NO_NAME", 0.0

    # 0. Report rollup lines are not donors at all — screen them out first.
    if _AGG.search(n):
        return "AGGREGATE_ROLLUP", "ROLLUP_LINE", 0.95

    # 1. Source-provided flag (Philadelphia donor_type)
    if source_flag and str(source_flag).strip().lower() not in ("", "nan", "not specified"):
        f = str(source_flag).strip().upper()
        mapped = {"INDIVIDUAL": "INDIVIDUAL", "COMPANY": "CORPORATE_ENTITY",
                  "COMMITTEE": "PAC_COMMITTEE", "OTHER": "OTHER"}.get(f)
        if mapped:
            return mapped, "SOURCE_FLAG", 0.98

    # 2. FEC entity type code
    if entity_tp:
        e = str(entity_tp).strip().upper()
        mapped = {"IND": "INDIVIDUAL", "CAN": "CANDIDATE_SELF", "CCM": "PAC_COMMITTEE",
                  "PAC": "PAC_COMMITTEE", "COM": "PAC_COMMITTEE", "PTY": "PARTY",
                  "ORG": "CORPORATE_ENTITY"}.get(e)
        if mapped:
            return mapped, "FEC_ENTITY_TP", 0.95

    # 3. Donor name matches a registered committee filer
    if filer_names and n in filer_names:
        return "PAC_COMMITTEE", "FILER_MATCH", 0.92

    # 4. Organizational name tokens
    if _UNION.search(n):
        return "UNION", "NAME_RULE", 0.88
    if _PARTY.search(n):
        return "PARTY", "NAME_RULE", 0.85
    if _PAC.search(n):
        return "PAC_COMMITTEE", "NAME_RULE", 0.85
    if _CORP.search(n):
        return "CORPORATE_ENTITY", "NAME_RULE", 0.85
    # Advocacy-org names carry no legal-form or PAC token, so they need their own
    # rule. Guarding it with looks_like_person() did not work - that helper returns
    # True for ANY 3-token name, so "AMERICAN OPPORTUNITY ACTION" was vetoed and
    # scored as an individual. Guard instead on the shape signals that actually
    # distinguish a person: a middle initial, or a populated employer/occupation.
    if _ADVOCACY.search(n):
        toks = n.split()
        has_initial = any(len(t) == 1 for t in toks)
        has_person_fields = (isinstance(employer, str) and employer.strip()) or \
                            (isinstance(occupation, str) and occupation.strip())
        if len(toks) >= 3 and not has_initial and not has_person_fields:
            return "PAC_COMMITTEE", "ADVOCACY_NAME_RULE", 0.75

    # 5. PA report schedule (empirically: IA/IC organizational, IB/ID individual)
    if schedule_hint:
        s = str(schedule_hint).strip().upper()
        if s in ("IA", "IC", "IIG"):
            return "PAC_COMMITTEE", "PA_SCHEDULE", 0.70
        if s in ("IB", "ID", "IIF"):
            return "INDIVIDUAL", "PA_SCHEDULE", 0.75

    # 6. Employer or occupation present -> almost certainly a natural person
    if (isinstance(employer, str) and employer.strip()) or \
       (isinstance(occupation, str) and occupation.strip()):
        return "INDIVIDUAL", "EMPLOYER_PRESENT", 0.80

    # 7. Name shape
    if looks_like_person(name):
        return "INDIVIDUAL", "NAME_SHAPE", 0.60

    return "UNRESOLVED", "NO_SIGNAL", 0.30


def rollup(donor_class):
    """Two-bucket view for the corporate-vs-individual split Jelani asked for."""
    if donor_class == "INDIVIDUAL":
        return "INDIVIDUAL"
    if donor_class in ("CORPORATE_ENTITY", "PAC_COMMITTEE", "UNION", "PARTY"):
        return "ORGANIZATIONAL"
    if donor_class == "AGGREGATE_ROLLUP":
        return "EXCLUDE-ROLLUP"
    return "OTHER/UNRESOLVED"
