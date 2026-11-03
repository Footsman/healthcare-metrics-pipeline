"""Find facilities that exhibit each phenomenon, rather than picking at random."""
from pathlib import Path
import pandas as pd

LAKE = Path(__file__).resolve().parents[1] / "lake"
pbj = pd.read_parquet(LAKE / "silver" / "pbj_daily" / "cy_qtr=2024Q2" / "pbj_daily.parquet")
dim = pd.read_parquet(LAKE / "silver" / "dim_facility" / "dim_facility.parquet")

g = pbj.groupby("provnum")
a = pd.DataFrame({
    "days_no_rn":    g.flag_no_rn.sum(),
    "resident_days": g.mdscensus.sum(),
    "direct_hours":  g.hrs_direct.sum(),
    "ctr_hours":     g.hrs_direct_ctr.sum(),
    "over24":        g.flag_hprd_over_24.sum(),
})
a["hprd"]      = (a.direct_hours / a.resident_days).round(2)
a["ctr_share"] = (a.ctr_hours / a.direct_hours * 100).round(1)

wk = (pbj.groupby(["provnum", "is_weekend"])
         .apply(lambda d: d.hrs_direct.sum() / max(d.mdscensus.sum(), 1), include_groups=False)
         .unstack())
a["wkday_hprd"]    = wk[False].round(2)
a["wkend_hprd"]    = wk[True].round(2)
a["wkend_gap_pct"] = ((1 - wk[True] / wk[False]) * 100).round(1)

a = a[a.resident_days > 3000].join(dim.set_index("ccn")[["provider_name", "state"]])

def show(title, df, cols):
    print(f"\n== {title}")
    print(df[cols].head(3).to_string())

show("most days with no RN",     a.sort_values("days_no_rn", ascending=False),    ["provider_name","state","days_no_rn","hprd"])
show("largest weekend gap",      a.sort_values("wkend_gap_pct", ascending=False), ["provider_name","state","wkday_hprd","wkend_hprd","wkend_gap_pct"])
show("highest contract share",   a.sort_values("ctr_share", ascending=False),     ["provider_name","state","ctr_share","hprd"])
show("lowest HPRD",              a.sort_values("hprd"),                            ["provider_name","state","hprd","days_no_rn"])
show("implausible HPRD days",    a[a.over24 > 0].sort_values("over24", ascending=False), ["provider_name","state","over24","hprd"])