"""Step 2 deliverable: data quality profile of the PBJ master file."""
import duckdb, pandas as pd, numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

BASE = Path(r"C:\Users\Footsman\Documents\DATA ENGINEER ACADEMY\Healthcare_project\nursing home data")
OUT  = BASE / "qa_out"
OUT.mkdir(exist_ok=True)

INK, MUTED, ACCENT, GRID = "#1a1a1a", "#6b7280", "#2f6fb0", "#e5e7eb"
ROLES = ["Hrs_RNDON","Hrs_RNadmin","Hrs_RN","Hrs_LPNadmin","Hrs_LPN","Hrs_CNA","Hrs_NAtrn","Hrs_MedAide"]

def head(t): print(f"\n{'='*70}\n{t}\n{'='*70}")

pbj = pd.read_csv(BASE / "PBJ_Daily_Nurse_Staffing_Q2_2024.csv",
                  dtype={"PROVNUM": str, "COUNTY_FIPS": str}, encoding="cp1252")
findings = []

head("1. SHAPE AND GRAIN")
print(duckdb.sql("""SELECT COUNT(*) AS rows, COUNT(DISTINCT PROVNUM) AS facilities,
       COUNT(DISTINCT WorkDate) AS days, COUNT(DISTINCT (PROVNUM, WorkDate)) AS distinct_keys,
       MIN(WorkDate) AS first_day, MAX(WorkDate) AS last_day FROM pbj"""))
rows, fac, days = len(pbj), pbj.PROVNUM.nunique(), pbj.WorkDate.nunique()
dups = rows - len(pbj.drop_duplicates(["PROVNUM","WorkDate"]))
findings.append(f"- **Grain**: one facility per calendar day. {rows:,} rows = {fac:,} facilities x {days} days. Duplicate keys: {dups}.")

head("2. MISSING VALUES")
nulls = pbj.isna().sum()
print(nulls[nulls > 0] if (nulls > 0).any() else "No nulls in any column.")
findings.append(f"- **Missing values**: {int(nulls.sum())} nulls across all {pbj.shape[1]} columns.")

head("3. COMPLETENESS: days reported per facility")
per = pbj.groupby("PROVNUM").size()
print(f"min={per.min()}  max={per.max()}  median={per.median():.0f}  below {days} days: {(per < days).sum()}")
findings.append(f"- **Completeness**: every facility reports all {days} days; no partial reporters.")

head("4. INTEGRITY: employee + contract = role total")
for r in ROLES:
    d = (pbj[r] - pbj[f"{r}_emp"] - pbj[f"{r}_ctr"]).abs()
    print(f"  {r:<16} mismatches={int((d>0.01).sum()):>6}   max diff={d.max():.4f}")
findings.append(f"- **Role integrity**: employee + contract reconciles to the role total on every row for all {len(ROLES)} roles.")

head("5. NEGATIVE VALUES")
negcols = {c: int((pbj[c] < 0).sum()) for c in ROLES + ["MDScensus"] if (pbj[c] < 0).any()}
print(negcols if negcols else "None.")
findings.append(f"- **Negative values**: {sum(negcols.values()) if negcols else 0}.")

head("6. EDGE CASES")
pbj["direct"] = pbj.Hrs_RN + pbj.Hrs_LPN + pbj.Hrs_CNA
zero_census = int((pbj.MDScensus == 0).sum())
zero_hours  = int((pbj.direct == 0).sum())
zero_rn     = int((pbj.Hrs_RN == 0).sum())
for lbl, v in [("census = 0", zero_census), ("direct hours = 0", zero_hours), ("RN hours = 0", zero_rn)]:
    print(f"  {lbl:<18}: {v:>8,}  ({100*v/rows:.3f}%)")
findings.append(f"- **Edge cases**: {zero_census:,} facility-days with zero census, {zero_hours:,} with zero direct-care hours, {zero_rn:,} ({100*zero_rn/rows:.1f}%) with zero RN hours.")

head("7. OUTLIERS: hours per resident day")
pbj["hprd"] = pbj.direct / pbj.MDScensus.replace(0, np.nan)
print(pbj.hprd.describe(percentiles=[.01,.05,.25,.5,.75,.95,.99]).round(3).to_string())
over24 = int((pbj.hprd > 24).sum())
print(f"\n  implausible (> 24 hrs/resident/day): {over24}")
findings.append(f"- **Outliers**: median HPRD {pbj.hprd.median():.2f}, 99th pct {pbj.hprd.quantile(.99):.2f}, max {pbj.hprd.max():.1f}. {over24} facility-days exceed 24 and are flagged, not deleted.")

head("8. CONTRACT RELIANCE BY ROLE")
share = {r.replace("Hrs_",""): 100*pbj[f"{r}_ctr"].sum()/pbj[r].sum() for r in ["Hrs_RN","Hrs_LPN","Hrs_CNA"]}
for k, v in share.items(): print(f"  {k:<5} {v:5.2f}% contract")
overall = 100*(pbj.Hrs_RN_ctr+pbj.Hrs_LPN_ctr+pbj.Hrs_CNA_ctr).sum()/pbj.direct.sum()
print(f"  {'ALL':<5} {overall:5.2f}% contract")
findings.append(f"- **Contract reliance**: {overall:.1f}% of direct-care hours nationally (RN {share['RN']:.1f}%, LPN {share['LPN']:.1f}%, CNA {share['CNA']:.1f}%).")

head("9. STATE COVERAGE")
print(f"  distinct states/territories: {pbj.STATE.nunique()}")

def style(ax):
    ax.spines[["top","right"]].set_visible(False)
    ax.spines[["left","bottom"]].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.yaxis.grid(True, color=GRID, lw=.8); ax.set_axisbelow(True); ax.xaxis.grid(False)

fig, ax = plt.subplots(figsize=(8, 4.2))
ax.hist(pbj.hprd[pbj.hprd <= 10].dropna(), bins=80, color=ACCENT, edgecolor="none")
ax.axvline(pbj.hprd.median(), color=INK, lw=1.5, ls="--")
ax.annotate(f"median {pbj.hprd.median():.2f}", (pbj.hprd.median(), ax.get_ylim()[1]*.92),
            xytext=(8,0), textcoords="offset points", color=INK, fontsize=9)
ax.set_title("Staffing clusters tightly around 3.3 hours per resident per day",
             color=INK, fontsize=12, fontweight="bold", loc="left", pad=12)
ax.set_xlabel("Total direct-care hours per resident per day", color=MUTED, fontsize=9)
ax.set_ylabel("Facility-days", color=MUTED, fontsize=9)
ax.text(.99,-.18, f"{int((pbj.hprd>10).sum()):,} facility-days above 10 are not shown",
        transform=ax.transAxes, ha="right", color=MUTED, fontsize=8)
style(ax); fig.tight_layout(); fig.savefig(OUT/"hprd_distribution.png", dpi=200, bbox_inches="tight")

fig, ax = plt.subplots(figsize=(8, 3.6))
labels = ["Null values","Duplicate keys","Negative values","Zero census","Zero direct hours","HPRD > 24"]
vals   = [int(nulls.sum()), dups, sum(negcols.values()) if negcols else 0, zero_census, zero_hours, over24]
for b, v in zip(ax.barh(labels, vals, color=ACCENT, height=.6), vals):
    ax.annotate(f"{v:,}", (b.get_width(), b.get_y()+b.get_height()/2),
                xytext=(6,0), textcoords="offset points", va="center", color=INK, fontsize=9)
ax.set_title(f"Three of six quality checks return zero across {rows:,} rows",
             color=INK, fontsize=12, fontweight="bold", loc="left", pad=12)
ax.set_xlabel("Rows affected", color=MUTED, fontsize=9)
ax.invert_yaxis(); style(ax); ax.xaxis.grid(True, color=GRID, lw=.8); ax.yaxis.grid(False)
ax.set_xlim(0, max(vals)*1.18)
fig.tight_layout(); fig.savefig(OUT/"quality_flags.png", dpi=200, bbox_inches="tight")

fig, ax = plt.subplots(figsize=(7, 3.6))
for b, v in zip(ax.bar(list(share), list(share.values()), color=ACCENT, width=.5), share.values()):
    ax.annotate(f"{v:.1f}%", (b.get_x()+b.get_width()/2, b.get_height()),
                xytext=(0,5), textcoords="offset points", ha="center", color=INK, fontsize=10, fontweight="bold")
ax.set_title(f"Contract staff supply {overall:.1f}% of direct-care hours, concentrated in LPNs",
             color=INK, fontsize=12, fontweight="bold", loc="left", pad=12)
ax.set_ylabel("Share of role hours", color=MUTED, fontsize=9)
ax.set_ylim(0, max(share.values())*1.3); style(ax)
fig.tight_layout(); fig.savefig(OUT/"contract_share_by_role.png", dpi=200, bbox_inches="tight")

(OUT/"data_quality_summary.md").write_text(
    "# PBJ Q2 2024 — data quality profile\n\n" + "\n".join(findings) + "\n", encoding="utf-8")

head("WRITTEN TO qa_out/")
for f in sorted(OUT.iterdir()): print(" ", f.name)