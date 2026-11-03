"""Phase 1, gold: the five metrics, pre-aggregated, with dimensions joined in."""
from pathlib import Path
import pandas as pd

LAKE = Path(__file__).resolve().parents[1] / "lake"
QTR  = "2024Q2"

MIN_DAYS_WITH_HOURS = 80      # of 91; sustained non-reporting
MIN_PLAUSIBLE_HPRD  = 1.0     # below this is a reporting failure, not a staffing level
CMS_TOLERANCE       = 0.01    # per-facility agreement with the published figure
MAX_CMS_OUTLIERS    = 5       # facilities allowed to exceed it (data oddities, not bugs)


def silver(table: str, partitioned: bool = False) -> pd.DataFrame:
    base = LAKE / "silver" / table / (f"cy_qtr={QTR}" if partitioned else "")
    return pd.read_parquet(base / f"{table}.parquet")


def write_gold(df: pd.DataFrame, table: str) -> Path:
    out = LAKE / "gold" / table / f"cy_qtr={QTR}"
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{table}.parquet"
    df.to_parquet(dest, index=False)
    return dest


def ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    """Sum over sum, guarded. Never the mean of per-row ratios."""
    return num / den.where(den > 0)


def build_facility_quarter() -> pd.DataFrame:
    pbj, dim, fact = silver("pbj_daily", True), silver("dim_facility"), silver("fact_outcome")

    rated = pbj[pbj.mdscensus > 0]          # ratio metrics ignore zero-census days
    g, gr = pbj.groupby("provnum"), rated.groupby("provnum")

    m = pd.DataFrame(index=g.size().index)
    m["days_reported"]   = g.size()
    m["days_with_hours"] = g.hrs_direct.apply(lambda s: int((s > 0).sum()))
    m["resident_days"]   = gr.mdscensus.sum()
    m["avg_census"]      = g.mdscensus.mean().round(1)

    # metric 1 - hours per resident day, direct care
    m["hprd_total"] = ratio(gr.hrs_direct.sum(), gr.mdscensus.sum()).round(3)
    for role in ["rn", "lpn", "cna"]:
        m[f"hprd_{role}"] = ratio(gr[f"hrs_{role}"].sum(), gr.mdscensus.sum()).round(3)

    # CMS's own definition: every nursing category. Validation only, not a care metric.
    m["hprd_cms_equiv"] = ratio(
        (gr.hrs_rn.sum() + gr.hrs_rnadmin.sum() + gr.hrs_rndon.sum()
         + gr.hrs_lpn.sum() + gr.hrs_lpnadmin.sum() + gr.hrs_cna.sum()
         + gr.hrs_natrn.sum() + gr.hrs_medaide.sum()),
        gr.mdscensus.sum()).round(5)

    # metric 2 - RN coverage gap
    m["days_no_rn"]     = g.flag_no_rn.sum()
    m["pct_days_no_rn"] = (m.days_no_rn / m.days_reported * 100).round(1)

    # metric 3 - contract reliance
    m["contract_share_pct"] = (ratio(g.hrs_direct_ctr.sum(), g.hrs_direct.sum()) * 100).round(1)

    # metric 4 - weekend gap
    wd, we = rated[~rated.is_weekend].groupby("provnum"), rated[rated.is_weekend].groupby("provnum")
    m["hprd_weekday"] = ratio(wd.hrs_direct.sum(), wd.mdscensus.sum()).round(3)
    m["hprd_weekend"] = ratio(we.hrs_direct.sum(), we.mdscensus.sum()).round(3)
    m["weekend_gap_pct"] = ((1 - m.hprd_weekend / m.hprd_weekday.where(m.hprd_weekday > 0)) * 100).round(1)

    m["days_hprd_over_24"] = g.flag_hprd_over_24.sum()
    m = m.reset_index().rename(columns={"provnum": "ccn"})

    m = m.merge(dim, on="ccn", how="left")
    m = m.merge(fact[["ccn", "adjusted_score", "obs_exp_ratio", "footnote"]]
                    .rename(columns={"adjusted_score": "readmit_adjusted",
                                     "obs_exp_ratio":  "readmit_obs_exp",
                                     "footnote":       "readmit_footnote"}),
                on="ccn", how="left")

    # metric 5 - occupancy, needs certified_beds from the dimension
    m["occupancy"] = ratio(m.avg_census, m.certified_beds).round(3)

    m["reporting_complete"] = ((m.days_with_hours >= MIN_DAYS_WITH_HOURS)
                               & (m.hprd_total >= MIN_PLAUSIBLE_HPRD))
    m["in_provider_info"] = m.certified_beds.notna()
    return m


def build_facility_month() -> pd.DataFrame:
    pbj = silver("pbj_daily", True)
    rated = pbj[pbj.mdscensus > 0]
    g, gr = pbj.groupby(["provnum", "month"]), rated.groupby(["provnum", "month"])

    m = pd.DataFrame(index=g.size().index)
    m["days_reported"]      = g.size()
    m["resident_days"]      = gr.mdscensus.sum()
    m["avg_census"]         = g.mdscensus.mean().round(1)
    m["hprd_total"]         = ratio(gr.hrs_direct.sum(), gr.mdscensus.sum()).round(3)
    m["days_no_rn"]         = g.flag_no_rn.sum()
    m["contract_share_pct"] = (ratio(g.hrs_direct_ctr.sum(), g.hrs_direct.sum()) * 100).round(1)
    return m.reset_index().rename(columns={"provnum": "ccn"})


def check(label: str, got, want) -> bool:
    ok = got == want
    print(f"{'OK  ' if ok else 'FAIL'} {label:<46} {got:>12,} / {want:>12,}")
    return ok


def check_max(label: str, got: float, limit: float) -> bool:
    ok = got <= limit
    print(f"{'OK  ' if ok else 'FAIL'} {label:<46} {got:>12.5f} <= {limit:>9.5f}")
    return ok


def main() -> None:
    q  = build_facility_quarter()
    mo = build_facility_month()

    v = q.dropna(subset=["hprd_cms_equiv", "reported_total_nurse_hprd"])
    delta = (v.hprd_cms_equiv - v.reported_total_nurse_hprd).abs()

    checks = [
        check("facility_quarter grain (ccn)", q.ccn.nunique(), len(q)),
        check("facility_month   grain (ccn, month)",
              len(mo.drop_duplicates(["ccn", "month"])), len(mo)),
        check("facility_quarter rows",        len(q),  14_564),
        check("facility_month   rows",        len(mo), 43_692),

        # the gate: our CMS-equivalent HPRD must reproduce CMS's published figure.
        # Thresholds catch systematic breakage without failing on isolated oddities.
        check_max("CMS HPRD mean abs difference",  float(delta.mean()),          0.001),
        check_max("CMS HPRD p99.9 abs difference", float(delta.quantile(0.999)), CMS_TOLERANCE),
        check_max("CMS HPRD facilities over tol",  float((delta > CMS_TOLERANCE).sum()),
                  MAX_CMS_OUTLIERS),
    ]
    print(f"     validated against {len(v):,} facilities with a published CMS figure")

    if not all(checks):
        raise SystemExit("\ngold build failed its checks - nothing written")

    print()
    for df, table in [(q, "metrics_facility_quarter"), (mo, "metrics_facility_month")]:
        dest = write_gold(df, table)
        print(f"wrote {table:<26} {len(df):>8,} rows -> {dest.relative_to(LAKE.parent)}")

    print(f"\nreporting_complete: {int(q.reporting_complete.sum()):,} of {len(q):,}"
          f"  ({int((~q.reporting_complete).sum())} flagged as non-reporters)")


if __name__ == "__main__":
    main()