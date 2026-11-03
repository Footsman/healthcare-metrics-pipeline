from google.oauth2 import service_account
from googleapiclient.discovery import build

KEY = r"C:\Users\Footsman\Documents\DATA ENGINEER ACADEMY\Healthcare_project\secrets\pbj-ingest-key.json"
creds = service_account.Credentials.from_service_account_file(
    KEY, scopes=["https://www.googleapis.com/auth/drive.readonly"])
svc = build("drive", "v3", credentials=creds)

# the folder
res = svc.files().list(
    q="'15KqJ1MZ7JcgAkOfqcaWcALWkG0dh3jpE' in parents and trashed=false",
    fields="files(id,name,size,md5Checksum,modifiedTime)", pageSize=100).execute()
print(len(res.get("files", [])), "files in folder")
for f in res.get("files", []):
    print(" ", f["name"], f.get("size"), f.get("md5Checksum"))

# the single file
meta = svc.files().get(fileId="1kZMZFGfTLdcwmdhjDPZh2-XE2_gOBRCz",
                       fields="id,name,size,md5Checksum,modifiedTime").execute()
print("\nmaster:", meta)