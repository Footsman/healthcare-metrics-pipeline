"""Bronze: raw CSV -> typed Parquet with provenance.

AWS Glue Python Shell job. Reads lake/raw/, writes lake/bronze/.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pandas as pd
import pyarrow.parquet as pq


def arg(name: str, default=None) -> str:
    """Read a Glue job parameter, passed in sys.argv as --name value."""
    key = f"--{name}"
    return sys.argv[sys.argv.index(key) + 1] if key in sys.argv else default


BUCKET = arg("BUCKET")
QTR    = arg("QTR", "2024Q2")
TMP    = Path("/tmp")

SOURCES = {
    "pbj_daily":      {"name": "PBJ_Daily_Nurse_Staffing_Q2_2024.csv",
                       "dtype": {"PROVNUM": str, "COUNTY_FIPS": str}},
    "provider_info":  {"name": "NH_ProviderInfo_Oct2024.csv",      "dtype": str},
    "quality_claims": {"name": "NH_QualityMsr_Claims_Oct2024.csv", "dtype": str},
}

s3 = boto3.client("s3")

ddb = boto3.resource("dynamodb").Table(arg("WATERMARK_TABLE", "pbj_ingest_watermark"))


def drive_meta() -> dict:
    """Filename -> the Drive metadata the ingest Lambda recorded."""
    items = ddb.scan(ProjectionExpression="file_id, #n, modifiedTime",
                     ExpressionAttributeNames={"#n": "name"})["Items"]
    return {i["name"]: i for i in items}

def build(table: str, cfg: dict, meta: dict) -> int:
    raw_key = f"lake/raw/{table}/cy_qtr={QTR}/{cfg['name']}"
    local   = TMP / cfg["name"]
    s3.download_file(BUCKET, raw_key, str(local))

    df = pd.read_csv(local, encoding="cp1252", dtype=cfg["dtype"], low_memory=False)
    df["source_file"]         = cfg["name"]
    df["drive_file_id"]       = meta["file_id"]
    df["drive_modified_time"] = meta["modifiedTime"]
    df["ingested_at"]         = datetime.now(timezone.utc).isoformat(timespec="seconds")

    out = TMP / f"{Path(cfg['name']).stem}.parquet"
    df.to_parquet(out, index=False)
    rows = pq.ParquetFile(out).metadata.num_rows

    dest_key = f"lake/bronze/{table}/cy_qtr={QTR}/{out.name}"
    s3.upload_file(str(out), BUCKET, dest_key)

    local.unlink()
    out.unlink()
    print(f"{table:<16} {rows:>9,} rows -> s3://{BUCKET}/{dest_key}")
    return rows


def main():
    meta = drive_meta()
    total = sum(build(t, c, meta[c["name"]]) for t, c in SOURCES.items())
    print(f"\nbronze complete: {total:,} rows across {len(SOURCES)} tables")


if __name__ == "__main__":
    main()