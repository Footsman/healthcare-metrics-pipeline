"""Look at one facility's quarter in silver."""
from pathlib import Path
import pandas as pd

LAKE = Path(__file__).resolve().parents[1] / "lake"
PROVNUM = "015009"

pbj = pd.read_parquet(LAKE / "silver" / "pbj_daily" / "cy_qtr=2024Q2" / "pbj_daily.parquet")
f = pbj[pbj.provnum == PROVNUM].sort_values("work_date")

view = f[["work_date", "is_weekend", "mdscensus",
          "hrs_rn", "hrs_lpn", "hrs_cna", "hrs_direct", "flag_no_rn"]].copy()
view["hprd"] = (view.hrs_direct / view.mdscensus).round(2)

print(view.to_string(index=False))
print("\nweekday mean HPRD:", round(view.loc[~view.is_weekend, "hprd"].mean(), 2))
print("weekend mean HPRD:", round(view.loc[view.is_weekend, "hprd"].mean(), 2))
print("days with no RN  :", int(view.flag_no_rn.sum()), "of", len(view))