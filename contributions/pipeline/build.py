"""Normalize PA state, Philadelphia, and FEC contribution data into one schema."""
import pandas as pd, numpy as np, os, glob
from classify import classify, norm, rollup

OUT = os.path.expanduser("~/pafin/out")
os.makedirs(OUT, exist_ok=True)
BASE = os.path.expanduser("~/pafin")

COLS = ["contribution_id","jurisdiction","report_year","recipient_filer_id","recipient_name",
        "recipient_type","office","district","party","donor_name_raw","donor_name_key",
        "donor_class","donor_class_method","donor_class_conf","donor_bucket","donor_city",
        "donor_state","donor_zip","donor_occupation","donor_employer","contribution_date",
        "amount","contribution_type","report_cycle","source_ref"]

# ---------------------------------------------------------------- PA STATE ----
PA_OFFICE = {"GOV":"Governor","LTG":"Lt. Governor","STH":"PA House","STS":"PA Senate",
             "USC":"U.S. House","USS":"U.S. Senate","ATT":"Attorney General",
             "AUD":"Auditor General","TRE":"Treasurer","SPM":"PA Supreme Court",
             "SPR":"Superior Court","CCJ":"Commonwealth Court","CPJ":"Court of Common Pleas",
             "DSC":"Dem State Committee","RSC":"Rep State Committee"}
PA_FILERTYPE = {"1":"Candidate Committee","2":"Political Committee","3":"Lobbyist"}

def load_pa():
    frames, filer_frames = [], []
    for path in sorted(glob.glob(f"{BASE}/y*/**/filer_*.txt", recursive=True)):
        filer_frames.append(pd.read_csv(path, dtype=str, encoding="latin-1", on_bad_lines="skip"))
    filers = pd.concat(filer_frames, ignore_index=True)
    filers["FILERNAME"] = filers.FILERNAME.fillna("").str.strip()
    # latest record per filer/year wins
    fmap = (filers.sort_values("SubmittedDate")
                  .drop_duplicates(["FILERID","EYEAR"], keep="last")
                  .set_index(["FILERID","EYEAR"]))
    filer_name_keys = set(filers.FILERNAME.map(norm)) - {""}

    for path in sorted(glob.glob(f"{BASE}/y*/**/contrib_*.txt", recursive=True)):
        c = pd.read_csv(path, dtype=str, encoding="latin-1", on_bad_lines="skip")
        for col in ("CONTAMT1","CONTAMT2","CONTAMT3"):
            c[col] = pd.to_numeric(c[col], errors="coerce").fillna(0)
        c["amount"] = c.CONTAMT1 + c.CONTAMT2 + c.CONTAMT3
        c = c[c.amount != 0].copy()
        c["date"] = c.CONTDATE1.where(c.CONTAMT1 != 0, c.CONTDATE2.where(c.CONTAMT2 != 0, c.CONTDATE3))
        key = pd.MultiIndex.from_arrays([c.FilerID, c.EYEAR])
        for src, dst in [("FILERNAME","recipient_name"),("OFFICE","office"),
                         ("DISTRICT","district"),("PARTY","party"),("FILERTYPE","ftype")]:
            c[dst] = fmap[src].reindex(key).values
        frames.append(c)

    c = pd.concat(frames, ignore_index=True)
    cls = [classify(n, schedule_hint=s, employer=e, occupation=o, filer_names=filer_name_keys)
           for n, s, e, o in zip(c.CONTRIBUTOR, c.Section, c.ENAME, c.OCCUPATION)]
    c["donor_class"], c["donor_class_method"], c["donor_class_conf"] = zip(*cls)

    out = pd.DataFrame({
        "contribution_id": "PA-" + c.CampaignFinanceID.astype(str) + "-" + c.index.astype(str),
        "jurisdiction": "PA-STATE",
        "report_year": c.EYEAR,
        "recipient_filer_id": c.FilerID,
        "recipient_name": c.recipient_name.fillna("(unmatched filer)").str.strip(),
        # PA codes a candidate's authorized committee as FILERTYPE 2, same as any
        # PAC. The reliable signal that a filer is a candidate vehicle is that
        # OFFICE is populated. Using FILERTYPE alone undercounted candidate
        # committees by ~1000x (1,480 rows vs the true ~2.4M).
        "recipient_type": np.where(
            c.office.fillna("").str.strip().ne(""), "Candidate Committee",
            c.ftype.map(PA_FILERTYPE).fillna("Unknown")),
        "office": c.office.map(PA_OFFICE).fillna(c.office).fillna(""),
        "district": c.district.fillna(""), "party": c.party.fillna(""),
        "donor_name_raw": c.CONTRIBUTOR.fillna("").str.strip(),
        "donor_name_key": c.CONTRIBUTOR.map(norm),
        "donor_class": c.donor_class, "donor_class_method": c.donor_class_method,
        "donor_class_conf": c.donor_class_conf,
        "donor_bucket": [rollup(x) for x in c.donor_class],
        "donor_city": c.CITY.fillna(""), "donor_state": c.STATE.fillna(""),
        "donor_zip": c.ZIPCODE.fillna(""), "donor_occupation": c.OCCUPATION.fillna(""),
        "donor_employer": c.ENAME.fillna(""),
        "contribution_date": pd.to_datetime(c.date, format="%Y%m%d", errors="coerce"),
        "amount": c.amount,
        "contribution_type": np.where(c.Section.isin(["IIF","IIG"]), "In-Kind", "Monetary"),
        "report_cycle": c.CYCLE, "source_ref": "PA DoS Full Export / Schedule " + c.Section.fillna(""),
    })
    return out[COLS], filers

# ------------------------------------------------------------- PHILADELPHIA ---
def load_phl():
    d = pd.concat([pd.read_csv(p, dtype=str, low_memory=False)
                   for p in sorted(glob.glob(f"{BASE}/phl/phl_contrib_*.csv"))], ignore_index=True)
    d["amount"] = pd.to_numeric(d.transaction_amount, errors="coerce").fillna(0)
    d = d[d.amount != 0].copy()
    cls = [classify(n, source_flag=sf, employer=e, occupation=o)
           for n, sf, e, o in zip(d.donor_name, d.donor_type,
                                  d.donor_employer_name, d.donor_occupation)]
    d["donor_class"], d["donor_class_method"], d["donor_class_conf"] = zip(*cls)

    out = pd.DataFrame({
        "contribution_id": "PHL-" + d.transaction_id.astype(str),
        "jurisdiction": "PHILADELPHIA",
        "report_year": d.report_year,
        "recipient_filer_id": d.filer_id,
        "recipient_name": d.filer_name.fillna("").str.strip(),
        "recipient_type": d.filer_type.fillna("Unknown"),
        "office": d.candidate_office.fillna(""),
        "district": d.candidate_district_name.fillna(d.candidate_district_num).fillna(""),
        "party": d.candidate_party.fillna(""),
        "donor_name_raw": d.donor_name.fillna("").str.strip(),
        "donor_name_key": d.donor_name.map(norm),
        "donor_class": d.donor_class, "donor_class_method": d.donor_class_method,
        "donor_class_conf": d.donor_class_conf,
        "donor_bucket": [rollup(x) for x in d.donor_class],
        "donor_city": d.donor_city.fillna(""), "donor_state": d.donor_state.fillna(""),
        "donor_zip": d.donor_zip.fillna(""), "donor_occupation": d.donor_occupation.fillna(""),
        "donor_employer": d.donor_employer_name.fillna(""),
        "contribution_date": pd.to_datetime(d.transaction_date, errors="coerce", utc=True).dt.tz_localize(None),
        "amount": d.amount,
        "contribution_type": d.transaction_type.fillna(""),
        "report_cycle": d.report_cycle_name.fillna(""),
        "source_ref": d.report_url.fillna("phila.gov campfin_contributions"),
    })
    return out[COLS]

# -------------------------------------------------------------------- FEC -----
FEC_OFFICE = {"H":"U.S. House","S":"U.S. Senate","P":"President"}
FEC_COLS = ["CMTE_ID","AMNDT_IND","RPT_TP","TRANSACTION_PGI","IMAGE_NUM","TRANSACTION_TP",
            "ENTITY_TP","NAME","CITY","STATE","ZIP_CODE","EMPLOYER","OCCUPATION",
            "TRANSACTION_DT","TRANSACTION_AMT","OTHER_ID","TRAN_ID","FILE_NUM","MEMO_CD",
            "MEMO_TEXT","SUB_ID"]

def load_fec():
    F = f"{BASE}/fec"
    cand = pd.read_csv(f"{F}/pa_candidates.csv", dtype=str)
    link = pd.read_csv(f"{F}/pa_cand_cmte.csv", dtype=str)
    cmte2cand = link.drop_duplicates("CMTE_ID").set_index("CMTE_ID").CAND_ID
    cinfo = cand.drop_duplicates("CAND_ID").set_index("CAND_ID")

    ind = pd.read_csv(f"{F}/pa_indiv_2026.txt", sep="|", header=None, names=FEC_COLS,
                      dtype=str, encoding="latin-1", on_bad_lines="skip")
    ind["CAND_ID"] = ind.CMTE_ID.map(cmte2cand)

    pas = pd.read_csv(f"{F}/pa_pac_to_cand_2026.csv", dtype=str)
    pas = pas.rename(columns={"NAME":"NAME"})
    pas["CMTE_ID_RECIP"] = pas.CMTE_ID  # filer is the *donor* committee in pas2
    keep = ["CMTE_ID","ENTITY_TP","NAME","CITY","STATE","ZIP_CODE","EMPLOYER","OCCUPATION",
            "TRANSACTION_DT","TRANSACTION_AMT","CAND_ID","SUB_ID","TRANSACTION_TP","RPT_TP"]
    both = pd.concat([ind[keep].assign(_src="indiv"), pas[keep].assign(_src="pas2")],
                     ignore_index=True)
    both["amount"] = pd.to_numeric(both.TRANSACTION_AMT, errors="coerce").fillna(0)
    both = both[both.amount != 0].copy()

    cls = [classify(n, entity_tp=et, employer=e, occupation=o)
           for n, et, e, o in zip(both.NAME, both.ENTITY_TP, both.EMPLOYER, both.OCCUPATION)]
    both["donor_class"], both["donor_class_method"], both["donor_class_conf"] = zip(*cls)
    ci = cinfo.reindex(both.CAND_ID)

    out = pd.DataFrame({
        "contribution_id": "FEC-" + both.SUB_ID.astype(str),
        "jurisdiction": "FEDERAL",
        "report_year": pd.to_datetime(both.TRANSACTION_DT, format="%m%d%Y", errors="coerce").dt.year.astype("Int64").astype(str),
        "recipient_filer_id": both.CAND_ID.fillna(both.CMTE_ID),
        "recipient_name": ci.CAND_NAME.values,
        "recipient_type": "Federal Candidate",
        "office": pd.Series(ci.CAND_OFFICE.values).map(FEC_OFFICE).fillna("").values,
        "district": ci.CAND_OFFICE_DISTRICT.values,
        "party": ci.CAND_PTY_AFFILIATION.values,
        "donor_name_raw": both.NAME.fillna("").str.strip(),
        "donor_name_key": both.NAME.map(norm),
        "donor_class": both.donor_class, "donor_class_method": both.donor_class_method,
        "donor_class_conf": both.donor_class_conf,
        "donor_bucket": [rollup(x) for x in both.donor_class],
        "donor_city": both.CITY.fillna(""), "donor_state": both.STATE.fillna(""),
        "donor_zip": both.ZIP_CODE.fillna(""), "donor_occupation": both.OCCUPATION.fillna(""),
        "donor_employer": both.EMPLOYER.fillna(""),
        "contribution_date": pd.to_datetime(both.TRANSACTION_DT, format="%m%d%Y", errors="coerce"),
        "amount": both.amount,
        "contribution_type": "Monetary",
        "report_cycle": both.RPT_TP.fillna(""),
        "source_ref": "FEC bulk " + both._src + " 2026 cycle",
    })
    out["recipient_name"] = out.recipient_name.fillna("(unlinked committee)")
    return out[COLS]


# ------------------------------------------------------------- DEDUPLICATION --
def dedupe(df):
    """Philadelphia's dataset and the PA state export both carry the same
    contributions for committees that dual-file. Validation measured 47% of
    Philadelphia dollars duplicating a PA-STATE row. Rows are kept but flagged so
    totals can be taken on is_primary without losing the audit trail."""
    # Hash the composite key to uint64 rather than materializing 3.2M long
    # strings — the string version OOMs a 7GB box.
    key_parts = pd.DataFrame({
        "d": df.donor_name_key.fillna("").values,
        "a": df.amount.round(2).values,
        "t": df.contribution_date.values.astype("datetime64[D]").astype(str),
        "r": df.recipient_name.fillna("").str.upper().str.replace(r"[^A-Z0-9 ]", " ", regex=True)
               .str.replace(r"\s+", " ", regex=True).str.strip().values,
    })
    key = pd.util.hash_pandas_object(key_parts, index=False).values
    del key_parts

    # Philadelphia wins on ties: richer record (donor_id, NAICS, incumbency, outcome).
    rank = df.jurisdiction.map({"PHILADELPHIA": 0, "FEDERAL": 1, "PA-STATE": 2}).fillna(9).values
    order = np.lexsort((rank, key))          # sort indices only, not the frame
    ks = key[order]
    is_dup_sorted = np.empty(len(ks), dtype=bool)
    is_dup_sorted[0] = False
    is_dup_sorted[1:] = ks[1:] == ks[:-1]    # every repeat after the best-ranked one
    dup = np.empty(len(ks), dtype=bool)
    dup[order] = is_dup_sorted
    dup &= df.donor_name_key.fillna("").str.len().gt(2).values   # never dedupe blank donors

    df = df.copy()
    df["dedupe_key"] = key
    df["is_primary"] = ~dup
    df["dup_reason"] = np.where(dup, "cross-jurisdiction duplicate", "")
    return df


def build_workbook(d, path):
    """Aggregated Excel layer. The 3.2M-row detail stays in CSV/Parquet; Excel
    carries only what a human reads."""
    live = d[d.is_primary & (d.donor_bucket != "EXCLUDE-ROLLUP")]
    piv = (live.pivot_table(index=["jurisdiction","office","recipient_name","party"],
                            columns="donor_bucket", values="amount",
                            aggfunc="sum", fill_value=0).reset_index())
    for col in ("INDIVIDUAL","ORGANIZATIONAL","OTHER/UNRESOLVED"):
        if col not in piv: piv[col] = 0.0
    piv["TOTAL"] = piv.INDIVIDUAL + piv.ORGANIZATIONAL + piv["OTHER/UNRESOLVED"]
    piv["ORG_SHARE"] = (piv.ORGANIZATIONAL / piv.TOTAL).round(3)
    piv = piv.sort_values("TOTAL", ascending=False)

    detail = (live.pivot_table(index=["jurisdiction","recipient_name"], columns="donor_class",
                               values="amount", aggfunc="sum", fill_value=0).reset_index())
    top_org = (live[live.donor_bucket=="ORGANIZATIONAL"]
               .groupby(["donor_name_raw","donor_class"], as_index=False)
               .agg(total=("amount","sum"), gifts=("amount","size"),
                    recipients=("recipient_name","nunique"))
               .nlargest(500,"total"))
    top_ind = (live[live.donor_bucket=="INDIVIDUAL"]
               .groupby(["donor_name_raw","donor_employer"], as_index=False)
               .agg(total=("amount","sum"), gifts=("amount","size"),
                    recipients=("recipient_name","nunique"))
               .nlargest(500,"total"))
    qa = pd.DataFrame({
        "metric": ["Total rows ingested","Primary (deduped) rows","Cross-jurisdiction duplicates",
                   "Rollup/unitemized rows excluded","Total $ (primary, ex-rollup)",
                   "Individual $","Organizational $","Unresolved $",
                   "Rows classified at confidence < 0.70","$ classified at confidence < 0.70"],
        "value": [len(d), int(d.is_primary.sum()), int((~d.is_primary).sum()),
                  int((d.donor_bucket=="EXCLUDE-ROLLUP").sum()), live.amount.sum(),
                  live.loc[live.donor_bucket=="INDIVIDUAL","amount"].sum(),
                  live.loc[live.donor_bucket=="ORGANIZATIONAL","amount"].sum(),
                  live.loc[live.donor_bucket=="OTHER/UNRESOLVED","amount"].sum(),
                  int((live.donor_class_conf<0.7).sum()),
                  live.loc[live.donor_class_conf<0.7,"amount"].sum()]})
    method = (live.groupby("donor_class_method")
                  .agg(rows=("amount","size"), dollars=("amount","sum"))
                  .sort_values("dollars", ascending=False).reset_index())

    with pd.ExcelWriter(path, engine="openpyxl") as w:
        qa.to_excel(w, sheet_name="00_QA_Control", index=False)
        piv.to_excel(w, sheet_name="01_Recipient_Corp_vs_Indiv", index=False)
        detail.to_excel(w, sheet_name="02_Recipient_By_DonorClass", index=False)
        top_org.to_excel(w, sheet_name="03_Top_Org_Donors", index=False)
        top_ind.to_excel(w, sheet_name="04_Top_Individual_Donors", index=False)
        method.to_excel(w, sheet_name="05_Classification_Method", index=False)
    return qa


if __name__ == "__main__":
    pa, filers = load_pa();  print("PA-STATE     ", f"{len(pa):>9,}")
    phl = load_phl();        print("PHILADELPHIA ", f"{len(phl):>9,}")
    fec = load_fec();        print("FEDERAL      ", f"{len(fec):>9,}")
    all_ = pd.concat([pa, phl, fec], ignore_index=True)
    del pa, phl, fec
    all_["report_year"] = all_.report_year.astype(str).str.extract(r"(\d{4})")[0]
    for c in ("jurisdiction","recipient_type","office","party","donor_class",
              "donor_class_method","donor_bucket","contribution_type","report_year"):
        all_[c] = all_[c].astype("category")
    all_ = dedupe(all_)
    all_.to_parquet(f"{OUT}/contributions_unified.parquet", index=False)
    for j, g in all_.groupby("jurisdiction"):
        for y, gy in g.groupby("report_year"):
            gy.to_csv(f"{OUT}/contributions_{j}_{y}.csv", index=False)
    filers.to_csv(f"{OUT}/pa_filer_master.csv", index=False)
    qa = build_workbook(all_, f"{OUT}/PA_Political_Contributions_Tracker.xlsx")
    print(); print(qa.to_string(index=False))
