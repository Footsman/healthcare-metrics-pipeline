import duckdb, pandas as pd

BASE = r"C:\Users\Footsman\Documents\DATA ENGINEER ACADEMY\Healthcare_project\nursing home data"

pbj  = pd.read_csv(BASE + r"\PBJ_Daily_Nurse_Staffing_Q2_2024.csv",
                   dtype={"PROVNUM": str, "COUNTY_FIPS": str}, encoding="cp1252")
prov = pd.read_csv(BASE + r"\NH_ProviderInfo_Oct2024.csv",
                   dtype=str, encoding="cp1252")

# 1. grain
print(duckdb.sql("""
    SELECT COUNT(*) AS rows,
           COUNT(DISTINCT "CMS Certification Number (CCN)") AS facilities
    FROM prov
"""))

# 2. join coverage
print(duckdb.sql("""
    SELECT COUNT(DISTINCT p.PROVNUM) AS pbj_facilities,
           COUNT(DISTINCT v."CMS Certification Number (CCN)") AS matched
    FROM pbj p
    LEFT JOIN prov v
      ON p.PROVNUM = v."CMS Certification Number (CCN)"
"""))

# 3. examples of what didn't match
print(duckdb.sql("""
    SELECT DISTINCT p.PROVNUM, p.PROVNAME, p.STATE
    FROM pbj p
    LEFT JOIN prov v ON p.PROVNUM = v."CMS Certification Number (CCN)"
    WHERE v."CMS Certification Number (CCN)" IS NULL
    LIMIT 10
"""))

print("pbj PROVNUM sample:", pbj["PROVNUM"].head(3).tolist())
print("prov CCN sample:   ", prov["CMS Certification Number (CCN)"].head(3).tolist())