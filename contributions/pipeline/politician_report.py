"""Attach politician_id to transactions and build the cross-year politician views."""
import pandas as pd, numpy as np, os
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

OUT = os.path.expanduser("~/pafin/out")
XL = f"{OUT}/PA_Political_Contributions_Tracker.xlsx"

d = pd.read_parquet(f"{OUT}/contributions_unified.parquet")
pv = pd.read_parquet(f"{OUT}/politician_vehicles.parquet")

pmap = pv.drop_duplicates("FILERID").set_index("FILERID")[
    ["politician_id", "politician_name", "oclass"]]
d = d.drop(columns=[c for c in ("politician_id", "politician_name", "oclass") if c in d.columns])
d["_fid"] = d.recipient_filer_id.astype(str)
d = d.join(pmap, on="_fid")
d["politician_id"] = d.politician_id.fillna("")
d["politician_name"] = d.politician_name.fillna("")
d = d.drop(columns="_fid")
d.to_parquet(f"{OUT}/contributions_unified.parquet", index=False)
for j, g in d.groupby("jurisdiction", observed=True):
    for y, gy in g.groupby("report_year", observed=True):
        gy.to_csv(f"{OUT}/contributions_{j}_{y}.csv", index=False)

live = d[d.is_primary & (d.donor_bucket != "EXCLUDE-ROLLUP")].copy()
pol = live[live.politician_id.ne("")].copy()

# Coverage must compare like with like: mapped candidate dollars against ALL
# candidate dollars. An earlier version divided mapped $ (any recipient reachable
# through a candidate filer) by a narrower recipient_type filter and reported 170%.
cand_mask = live.recipient_type.astype(str).str.contains("Candidate|Federal", na=False)
cand_total = live[cand_mask].amount.sum()
mapped_cand = live[cand_mask & live.politician_id.ne("")].amount.sum()
UNMAPPED_CAND_ = live[cand_mask & live.politician_id.eq("")].amount.sum()
UNMAPPED_CAND_DOLLARS = float(UNMAPPED_CAND_)
COVERAGE_STR = f"{mapped_cand / cand_total:.1%}" if cand_total else "n/a"

cov = pd.DataFrame({
    "metric": ["Candidate filing vehicles", "Distinct politicians",
               "Politicians with >1 vehicle", "Politicians spanning >1 jurisdiction",
               "Max vehicles for one politician",
               "Contributions mapped to a politician", "$ mapped to a politician (all recipients)",
               "$ to candidate recipients NOT mapped", "Coverage of candidate $"],
    "value": [len(pv), pv.politician_id.nunique(),
              int((pv.groupby("politician_id").size() > 1).sum()),
              int((pv.groupby("politician_id").jurisdiction.nunique() > 1).sum()),
              int(pv.groupby("politician_id").size().max()),
              len(pol), pol.amount.sum(),
              UNMAPPED_CAND_DOLLARS,
              COVERAGE_STR]})

# ---- cross-year, cross-vehicle politician totals ----------------------------
by_pol = (pol.groupby(["politician_id", "politician_name"], observed=True)
          .agg(total=("amount", "sum"), gifts=("amount", "size"),
               donors=("donor_entity_id", "nunique"),
               vehicles=("recipient_filer_id", "nunique"),
               jurisdictions=("jurisdiction", "nunique"),
               first_gift=("contribution_date", "min"),
               last_gift=("contribution_date", "max")).reset_index())
buckets = (pol.pivot_table(index="politician_id", columns="donor_bucket", values="amount",
                           aggfunc="sum", fill_value=0, observed=True))
for c in ("INDIVIDUAL", "ORGANIZATIONAL", "OTHER/UNRESOLVED"):
    if c not in buckets: buckets[c] = 0.0
by_pol = by_pol.merge(buckets.reset_index(), on="politician_id", how="left")
by_pol["ORG_SHARE"] = (by_pol.ORGANIZATIONAL / by_pol.total.replace(0, np.nan)).round(3)
meta = pv.groupby("politician_id").agg(
    offices=("office", lambda s: ",".join(sorted(set(str(x) for x in s if str(x).strip())))),
    party=("party_n", lambda s: ",".join(sorted(set(str(x) for x in s if str(x).strip())))),
    districts=("district", lambda s: ",".join(sorted(set(
        str(x) for x in s if str(x) not in ("", "nan", "-1"))))))
by_pol = by_pol.merge(meta, on="politician_id", how="left").sort_values("total", ascending=False)

# ---- by politician x year (the thing that was impossible before) ------------
pol["yr"] = pol.contribution_date.dt.year
by_year = (pol[pol.yr.notna()]
           .pivot_table(index=["politician_id", "politician_name"], columns="yr",
                        values="amount", aggfunc="sum", fill_value=0, observed=True)
           .reset_index())
ycols = [c for c in by_year.columns if isinstance(c, (int, float))]
by_year["TOTAL"] = by_year[ycols].sum(axis=1)
by_year.columns = [str(int(c)) if isinstance(c, (int, float)) else c for c in by_year.columns]
by_year = by_year.sort_values("TOTAL", ascending=False)

# ---- donor -> politician edges, the influence map --------------------------
edges = (pol.groupby(["donor_entity_id", "entity_name", "politician_id", "politician_name"],
                     observed=True)
         .agg(total=("amount", "sum"), gifts=("amount", "size"),
              years=("yr", lambda s: ",".join(sorted(set(str(int(x)) for x in s.dropna())))))
         .reset_index().nlargest(3000, "total"))

multi_vehicle = (pv[pv.politician_id.isin(
    pv.groupby("politician_id").filter(lambda g: len(g) > 1).politician_id)]
    [["politician_id", "politician_name", "FILERID", "filer_name", "jurisdiction",
      "office", "district", "party_n", "years", "extract_status"]]
    .sort_values(["politician_id", "jurisdiction"]))

unmapped = (live[live.recipient_type.astype(str).str.contains("Candidate|Federal", na=False)
                 & live.politician_id.eq("")]
            .groupby(["jurisdiction", "recipient_filer_id", "recipient_name"], observed=True)
            .amount.sum().reset_index().nlargest(500, "amount"))

existing = pd.read_excel(XL, sheet_name=None)
readme = existing["00_README_and_Rules"]
add = pd.DataFrame({"Item": ["", "POLITICIAN CROSSWALK"] + ["POLITICIAN CROSSWALK"] * 6,
 "Detail": ["",
  f"Added 2026-08-04. {len(pv):,} candidate filing vehicles resolved to {pv.politician_id.nunique():,} politicians. Every contribution to a candidate now carries politician_id, so a politician can be tracked across years, vehicles and jurisdictions.",
  "The problem: PA re-issues candidate FILERIDs every election year (2026C0421), and one politician files under several vehicles at once - a personal record, one or more 'Friends of' committees, a Philadelphia filer, a federal committee.",
  "The key: PA candidate filers come in two shapes. Rotating IDs (2026C....) usually carry the politician's OWN name as the filer name ('KENYATTA, MALCOLM'). Stable IDs carry the committee name ('FRIENDS OF ANGELA GIROL'). Strip the committee wrapper off the second and it matches the first.",
  "Caveat found in validation: rotating IDs do NOT always carry a bare name - 2024C0510 is 'CITIZENS FOR JORDAN A. HARRIS'. Assuming otherwise forked Jordan Harris into two politicians, so wrapper stripping now runs on every record.",
  "Committee names that reduce to a bare surname ('Shapiro for Pennsylvania' -> SHAPIRO) attach to a named politician only when exactly one candidate shares that surname and office class. 54 linked, 5 left ambiguous.",
  "Guards: a party conflict, or the same office class in the same year with a different district, blocks a link. Distinct politicians sharing a surname (Jordan, Gregory and Keith Harris) stay separate.",
  "Sheet 15 lists every politician with more than one vehicle so the mapping can be audited. Sheet 16 lists candidate recipients that could NOT be mapped."]})
readme = pd.concat([readme, add], ignore_index=True)

sheets = dict(existing)
sheets["00_README_and_Rules"] = readme
sheets["12_Crosswalk_QA"] = cov
sheets["13_Politician_Totals"] = by_pol.head(2000)
sheets["14_Politician_By_Year"] = by_year.head(2000)
sheets["15_Politician_Vehicles"] = multi_vehicle
sheets["16_Unmapped_Candidates"] = unmapped
sheets["17_Donor_to_Politician"] = edges

order = ["00_README_and_Rules", "01_QA_Control", "02_Entity_Resolution_QA", "12_Crosswalk_QA",
         "13_Politician_Totals", "14_Politician_By_Year", "17_Donor_to_Politician",
         "03_Candidates_Corp_vs_Indiv", "04_All_Recipients", "05_Top_Org_Entities",
         "06_Top_Indiv_Entities", "07_Merged_Entities", "08_Multi_Recipient_Entities",
         "09_Recipient_By_DonorClass", "10_Classification_Method", "15_Politician_Vehicles",
         "16_Unmapped_Candidates", "11_Entity_Review_Queue"]
with pd.ExcelWriter(XL, engine="openpyxl") as w:
    for name in order:
        if name in sheets:
            sheets[name].to_excel(w, sheet_name=name, index=False)

wb = load_workbook(XL)
HDR = PatternFill("solid", fgColor="1F3864")
for ws in wb.worksheets:
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.fill = HDR
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col in ws.iter_cols(min_row=1, max_row=1):
        h = str(col[0].value or "")
        ws.column_dimensions[get_column_letter(col[0].column)].width = \
            70 if h == "Detail" else min(max(len(h) + 4, 14), 42)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                h = str(ws.cell(1, cell.column).value or "")
                cell.number_format = ("0.0%" if "SHARE" in h.upper() else
                                      "0.000" if h == "score" else
                                      "#,##0" if abs(cell.value) >= 1000 else "#,##0.00")
wb.save(XL)
by_pol.to_csv(f"{OUT}/politician_totals.csv", index=False)
print(cov.to_string(index=False))
print("\nsheets:", len(wb.sheetnames))
print("\n=== Top 15 politicians, all vehicles and years combined ===")
print(by_pol.head(15)[["politician_name", "offices", "party", "total", "INDIVIDUAL",
                       "ORGANIZATIONAL", "ORG_SHARE", "vehicles", "donors"]].to_string(index=False))
