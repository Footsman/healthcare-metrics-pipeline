import duckdb, pandas as pd

BASE = r"C:\Users\Footsman\Documents\DATA ENGINEER ACADEMY\Healthcare_project\nursing home data"
CCN  = '"CMS Certification Number (CCN)"'

pbj = pd.read_csv(BASE + r"\PBJ_Daily_Nurse_Staffing_Q2_2024.csv",
                  dtype={"PROVNUM": str, "COUNTY_FIPS": str}, encoding="cp1252")
qm  = pd.read_csv(BASE + r"\NH_QualityMsr_Claims_Oct2024.csv",  dtype=str, encoding="cp1252")
vbp = pd.read_csv(BASE + r"\FY_2024_SNF_VBP_Facility_Performance.csv", dtype=str, encoding="cp1252")

print("\n=== A. QualityMsr: what's actually in it ===")
print(duckdb.sql(f"""
    SELECT "Measure Code", "Resident type", "Measure Period",
           COUNT(*) AS rows,
           COUNT(DISTINCT {CCN}) AS facilities
    FROM qm
    GROUP BY 1,2,3
    ORDER BY 1,2
"""))

print("\n=== B. QualityMsr: key test ===")
print(duckdb.sql(f"""
    SELECT COUNT(*) AS rows,
           COUNT(DISTINCT {CCN}) AS facilities,
           COUNT(DISTINCT ({CCN}, "Measure Code", "Resident type")) AS candidate_key
    FROM qm
"""))

print("\n=== C. QualityMsr: suppression ===")
print(duckdb.sql(f"""
    SELECT "Footnote for Score",
           COUNT(*) AS rows,
           SUM(CASE WHEN "Adjusted Score" IS NULL OR "Adjusted Score" = '' THEN 1 ELSE 0 END) AS blank_scores
    FROM qm
    GROUP BY 1
    ORDER BY rows DESC
"""))

print("\n=== D. QualityMsr: coverage vs PBJ ===")
print(duckdb.sql(f"""
    SELECT COUNT(DISTINCT p.PROVNUM) AS pbj_facilities,
           COUNT(DISTINCT q.{CCN}) AS matched
    FROM pbj p
    LEFT JOIN (SELECT DISTINCT {CCN} FROM qm) q
      ON p.PROVNUM = q.{CCN}
"""))

print("\n=== E. VBP: grain and coverage ===")
print(duckdb.sql(f"""
    SELECT COUNT(*) AS rows, COUNT(DISTINCT {CCN}) AS facilities FROM vbp
"""))
print(duckdb.sql(f"""
    SELECT COUNT(DISTINCT p.PROVNUM) AS pbj_facilities,
           COUNT(DISTINCT v.{CCN}) AS matched
    FROM pbj p
    LEFT JOIN vbp v ON p.PROVNUM = v.{CCN}
"""))

print(duckdb.sql(f"""
    SELECT "Measure Code", "Resident type", "Measure Description",
           COUNT(*) AS facilities,
           SUM(CASE WHEN "Footnote for Score" IS NULL THEN 1 ELSE 0 END) AS usable,
           ROUND(100.0 * SUM(CASE WHEN "Footnote for Score" IS NULL THEN 1 ELSE 0 END)
                 / COUNT(*), 1) AS pct_usable
    FROM qm
    GROUP BY 1,2,3
    ORDER BY 1
"""))

print(duckdb.sql(f"""
    SELECT COUNT(DISTINCT p.PROVNUM) AS analysis_sample
    FROM pbj p
    JOIN qm q
      ON p.PROVNUM = q.{CCN}
    WHERE q."Measure Code" = '521'
      AND q."Footnote for Score" IS NULL
"""))