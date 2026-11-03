"""Phase 1, ingest: pull the in-scope source files from Google Drive, incrementally."""
from pathlib import Path
from datetime import datetime, timezone
import json
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

PIPELINE = Path(__file__).resolve().parents[1]
LAKE     = PIPELINE / "lake"
KEY      = PIPELINE.parent / "secrets" / "pbj-ingest-key.json"
WATERMARK = LAKE / "watermark.json"
STAGING   = LAKE / "_staging"
QTR = "2024Q2"

FOLDER_ID = "15KqJ1MZ7JcgAkOfqcaWcALWkG0dh3jpE"
MASTER_ID = "1kZMZFGfTLdcwmdhjDPZh2-XE2_gOBRCz"

# only the three files in scope; the other 18 are deliberately not ingested
SOURCES = {
    "pbj_daily":      {"file_id": MASTER_ID,
                       "name": "PBJ_Daily_Nurse_Staffing_Q2_2024.csv",
                       "dtype": {"PROVNUM": str, "COUNTY_FIPS": str}},
    "provider_info":  {"name": "NH_ProviderInfo_Oct2024.csv",      "dtype": str},
    "quality_claims": {"name": "NH_QualityMsr_Claims_Oct2024.csv", "dtype": str},
}

FIELDS = "id,name,size,md5Checksum,modifiedTime"


def drive():
    creds = service_account.Credentials.from_service_account_file(
        KEY, scopes=["https://www.googleapis.com/auth/drive.readonly"])
    return build("drive", "v3", credentials=creds)


def load_watermark() -> dict:
    return json.loads(WATERMARK.read_text()) if WATERMARK.exists() else {}


def save_watermark(wm: dict) -> None:
    WATERMARK.parent.mkdir(parents=True, exist_ok=True)
    WATERMARK.write_text(json.dumps(wm, indent=2, sort_keys=True))


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


def to_bronze(table: str, csv_path: Path, meta: dict) -> int:
    df = pd.read_csv(csv_path, dtype=SOURCES[table]["dtype"], encoding="cp1252")
    df["source_file"] = meta["name"]
    df["drive_file_id"] = meta["id"]
    df["drive_modified_time"] = meta["modifiedTime"]
    df["ingested_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    out = LAKE / "bronze" / table / f"cy_qtr={QTR}"
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / f"{Path(meta['name']).stem}.parquet", index=False)
    return len(df)


def main() -> None:
    svc = drive()
    wm = load_watermark()
    current = resolve(svc)

    pulled = skipped = 0
    for table, meta in current.items():
        known = wm.get(meta["id"], {})
        if known.get("md5Checksum") == meta["md5Checksum"]:
            print(f"SKIP  {table:<16} checksum unchanged ({meta['md5Checksum'][:12]}…)")
            skipped += 1
            continue

        size_mb = int(meta.get("size", 0)) / 1024 / 1024
        print(f"PULL  {table:<16} {meta['name']}  ({size_mb:,.1f} MB)")
        csv_path = STAGING / meta["name"]
        download(svc, meta["id"], csv_path)
        rows = to_bronze(table, csv_path, meta)
        csv_path.unlink()

        # watermark updated only after bronze is written
        wm[meta["id"]] = {"name": meta["name"],
                          "md5Checksum": meta["md5Checksum"],
                          "modifiedTime": meta["modifiedTime"],
                          "rows": rows,
                          "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        save_watermark(wm)
        print(f"      {rows:,} rows -> bronze")

    pulled = len(current) - skipped
    print(f"\n{pulled} pulled, {skipped} skipped")


if __name__ == "__main__":
    main()