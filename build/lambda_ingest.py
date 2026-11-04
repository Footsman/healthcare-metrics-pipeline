"""Pull PBJ source files from Google Drive into the raw zone.

Runs as an AWS Lambda. Incremental: a file is pulled only when its
md5Checksum differs from the one recorded in DynamoDB.
"""
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import boto3
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

BUCKET    = os.environ["BUCKET"]
SECRET_ID = os.environ["SECRET_ID"]
FOLDER_ID = os.environ["FOLDER_ID"]
MASTER_ID = os.environ["MASTER_ID"]
QTR       = os.environ.get("QTR", "2024Q2")

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

SOURCES = {
    "pbj_daily":      {"file_id": MASTER_ID,
                       "name": "PBJ_Daily_Nurse_Staffing_Q2_2024.csv",
                       "dtype": {"PROVNUM": str, "COUNTY_FIPS": str}},
    "provider_info":  {"name": "NH_ProviderInfo_Oct2024.csv",      "dtype": str},
    "quality_claims": {"name": "NH_QualityMsr_Claims_Oct2024.csv", "dtype": str},
}

FIELDS = "id,name,size,md5Checksum,modifiedTime"

s3        = boto3.client("s3")
sm        = boto3.client("secretsmanager")
watermark = boto3.resource("dynamodb").Table(os.environ["WATERMARK_TABLE"])


def drive():
    """Build a Drive client from the key held in Secrets Manager."""
    raw = sm.get_secret_value(SecretId=SECRET_ID)["SecretString"]
    creds = service_account.Credentials.from_service_account_info(
        json.loads(raw), scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def known_checksum(file_id: str) -> str | None:
    """The md5 we recorded last time this file was ingested, if any."""
    item = watermark.get_item(Key={"file_id": file_id}).get("Item")
    return item["md5Checksum"] if item else None


def record(file_id: str, meta: dict, key: str) -> None:
    """Mark a file ingested. Call this ONLY after the S3 write succeeded."""
    watermark.put_item(Item={
        "file_id":      file_id,
        "name":         meta["name"],
        "md5Checksum":  meta["md5Checksum"],
        "modifiedTime": meta["modifiedTime"],
        "s3_key":       key,
        "ingested_at":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })

def resolve(svc) -> dict:
    """Map each in-scope table to its current Drive metadata."""
    listing = svc.files().list(
        q=f"'{FOLDER_ID}' in parents and trashed=false",
        fields=f"files({FIELDS})", pageSize=200).execute().get("files", [])
    by_name = {f["name"]: f for f in listing}

    out = {}
    for table, cfg in SOURCES.items():
        if "file_id" in cfg:
            out[table] = svc.files().get(fileId=cfg["file_id"], fields=FIELDS).execute()
        elif cfg["name"] in by_name:
            out[table] = by_name[cfg["name"]]
        else:
            raise SystemExit(f"{cfg['name']} not found in the Drive folder")
    return out


def download(svc, file_id: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = svc.files().get_media(fileId=file_id)
    with open(dest, "wb") as fh:
        dl = MediaIoBaseDownload(fh, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            status, done = dl.next_chunk()
            if status:
                print(f"      {int(status.progress() * 100):3d}%", end="\r")
    print("      done   ")

def to_raw(table: str, local_path: Path, meta: dict) -> str:
    """Upload a downloaded file to the raw zone. Returns the S3 key."""
    key = f"lake/raw/{table}/cy_qtr={QTR}/{meta['name']}"
    s3.upload_file(str(local_path), BUCKET, key)
    return key

def lambda_handler(event, context) -> dict:
    svc = drive()
    current = resolve(svc)

    pulled, skipped = [], []
    for table, meta in current.items():
        if known_checksum(meta["id"]) == meta["md5Checksum"]:
            print(f"SKIP  {table:<16} checksum unchanged ({meta['md5Checksum'][:12]}…)")
            skipped.append(table)
            continue

        size_mb = int(meta.get("size", 0)) / 1024 / 1024
        print(f"PULL  {table:<16} {meta['name']}  ({size_mb:,.1f} MB)")

        tmp = Path("/tmp") / meta["name"]
        download(svc, meta["id"], tmp)
        key = to_raw(table, tmp, meta)
        record(meta["id"], meta, key)   # only after the S3 write succeeded
        tmp.unlink()                    # /tmp survives warm invocations

        print(f"      -> s3://{BUCKET}/{key}")
        pulled.append(table)

    print(f"\n{len(pulled)} pulled, {len(skipped)} skipped")
    return {"qtr": QTR, "pulled": pulled, "skipped": skipped}