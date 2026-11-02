"""Phase 1, bronze: land the three source CSVs as Parquet, unchanged."""
from pathlib import Path
from datetime import datetime, timezone
import duckdb, pandas as pd

DATA = Path(r"C:\Users\Footsman\Documents\DATA ENGINEER ACADEMY\Healthcare_project\nursing home data")
LAKE = Path(__file__).resolve().parents[1] / "lake"
QTR  = "2024Q2"

SOURCES = {
    "pbj_daily":      ("PBJ_Daily_Nurse_Staffing_Q2_2024.csv", {"PROVNUM": str, "COUNTY_FIPS": str}),
    "provider_info":  ("NH_ProviderInfo_Oct2024.csv",          str),
    "quality_claims": ("NH_QualityMsr_Claims_Oct2024.csv",     str),
}

def main():
    ingested = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for table, (fname, dt) in SOURCES.items():
        src = DATA / fname
        df = pd.read_csv(src, dtype=dt, encoding="cp1252")
        rows_in = len(df)

        df["source_file"] = fname
        df["ingested_at"] = ingested

        out = LAKE / "bronze" / table / f"cy_qtr={QTR}"
        out.mkdir(parents=True, exist_ok=True)
        dest = out / f"{src.stem}.parquet"

        duckdb.sql(f"COPY df TO '{dest.as_posix()}' (FORMAT PARQUET)")
        back = duckdb.sql(f"SELECT COUNT(*) FROM '{dest.as_posix()}'").fetchall()[0][0]

        flag = "OK " if back == rows_in else "FAIL"
        print(f"{flag} {table:<16} {rows_in:>9,} rows in, {back:>9,} out  ->  {dest.name}")

if __name__ == "__main__":
    main()