"""Phase 1, silver: typed, cleaned tables at a declarted grain"""
from pathlib import Path
import pandas as pd

LAKE = Path(__file__).resolve().parents[1] / "lake"
QTR = "2024Q2" 

def bronze(table: str) -> pd.DataFrame:
    src = LAKE / "bronze" / table / f"cy_qtr={QTR}"
    return pd.read_parquet(next(src.glob("*.parquet")))

def write(df: pd.DataFrame, table: str, partitioned: bool = True) -> Path:
    out = LAKE / "silver" / table / (f"cy_qtr={QTR}" if partitioned else "")
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{table}.parquet"
    df.to_parquet(dest, index=False)
    return dest

def build_pbj_daily() -> pd.DataFrame:
    df = bronze("pbj_daily")

    out = pd.DataFrame()
    out["provnum"]      = df["PROVNUM"].str.zfill(6)
    out["work_date"]    = pd.to_datetime(df["WorkDate"], format="%Y%m%d")
    out["month"]        = out["work_date"].dt.to_period("M").astype(str)
    out["is_weekend"]   = out["work_date"].dt.weekday >= 5
    out["state"]        = df["STATE"]
    out["county_name"]  = df["COUNTY_NAME"]
    out["mdscensus"]    = df["MDScensus"].astype("int32")

    hrs = [c for c in df.columns if c.startswith("Hrs_")]
    for c in hrs:
        out[c.lower()] = pd.to_numeric(df[c], errors="coerce").astype("float32")

    out["hrs_direct"]       = out[["hrs_rn", "hrs_lpn", "hrs_cna"]].sum(axis=1)
    out["hrs_direct_ctr"]   = out[["hrs_rn_ctr", "hrs_lpn_ctr", "hrs_cna_ctr"]].sum(axis=1)

    hprd = out["hrs_direct"] / out["mdscensus"].where(out["mdscensus"] > 0)

    out["flag_zero_census"] = out["mdscensus"].eq(0)
    out["flag_zero_direct"] = out["hrs_direct"].eq(0)
    out["flag_no_rn"]       = out["hrs_rn"].eq(0)
    out["flag_hprd_over_24"] = hprd.gt(24).fillna(False)

    return out

def build_dim_facility() -> pd.DataFrame:
    df = bronze("provider_info")

    out = pd.DataFrame()
    out["ccn"]            = df["CMS Certification Number (CCN)"].str.zfill(6)
    out["provider_name"]  = df["Provider Name"]
    out["state"]          = df["State"]
    out["county"]         = df["County/Parish"]
    out["ownership_type"] = df["Ownership Type"]
    out["provider_type"]  = df["Provider Type"]

    numeric = {
        "certified_beds":            "Number of Certified Beds",
        "avg_residents_per_day":     "Average Number of Residents per Day",
        "reported_total_nurse_hprd": "Reported Total Nurse Staffing Hours per Resident per Day",
        "nursing_case_mix_index":    "Nursing Case-Mix Index",
    }
    for target, source in numeric.items():
        out[target] = pd.to_numeric(df[source], errors="coerce").astype("float64")

    ratings = {
        "overall_rating":  "Overall Rating",
        "staffing_rating": "Staffing Rating",
    }
    for target, source in ratings.items():
        out[target] = pd.to_numeric(df[source], errors="coerce").astype("Int64")

    return out

def build_fact_outcome() -> pd.DataFrame:
    df = bronze("quality_claims")
    df = df[df["Measure Code"] == "521"].reset_index(drop=True)

    out = pd.DataFrame()
    out["ccn"]            = df["CMS Certification Number (CCN)"].str.zfill(6)
    out["measure_code"]   = df["Measure Code"]
    out["measure_period"] = df["Measure Period"]
    out["footnote"]       = df["Footnote for Score"]

    for target, source in {
        "adjusted_score": "Adjusted Score",
        "observed_score": "Observed Score",
        "expected_score": "Expected Score",
    }.items():
        out[target] = pd.to_numeric(df[source], errors="coerce").astype("float64")

    out["obs_exp_ratio"] = (
        out["observed_score"] / out["expected_score"].where(out["expected_score"] > 0)
    )
    return out


def check(label: str, got: int, want: int) -> bool:
    ok = got == want
    print(f"{'OK  ' if ok else 'FAIL'} {label:<44} {got:>10,} / {want:>10,}")
    return ok


def main() -> None:
    pbj  = build_pbj_daily()
    dim  = build_dim_facility()
    fact = build_fact_outcome()

    checks = [
        # grain — must hold for any quarter, any volume
        check("pbj_daily    grain (provnum, work_date)",
              len(pbj.drop_duplicates(["provnum", "work_date"])), len(pbj)),
        check("dim_facility grain (ccn)",  dim.ccn.nunique(),  len(dim)),
        check("fact_outcome grain (ccn)",  fact.ccn.nunique(), len(fact)),

        # volume — specific to Q2 2024; update these when the quarter changes
        check("pbj_daily    rows",              len(pbj),   1_325_324),
        check("dim_facility rows",              len(dim),      14_814),
        check("fact_outcome rows",              len(fact),     14_814),
        check("fact_outcome scored facilities",
              int(fact.adjusted_score.notna().sum()),          11_928),
    ]

    if not all(checks):
        raise SystemExit("\nsilver build failed its checks — nothing written")

    print()
    for df, table, partitioned in [(pbj,  "pbj_daily",    True),
                                   (dim,  "dim_facility", False),
                                   (fact, "fact_outcome", False)]:
        dest = write(df, table, partitioned=partitioned)
        print(f"wrote {table:<14} {len(df):>10,} rows -> {dest.relative_to(LAKE.parent)}")


if __name__ == "__main__":
    main()