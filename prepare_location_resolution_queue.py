import pandas as pd
import urllib.parse
import re

INPUT = "location_validation_queue.csv"
OUTPUT = "location_resolution_queue.csv"

def clean(v):
    if pd.isna(v):
        return ""
    return re.sub(r"\s+", " ", str(v).strip())

def zip5(v):
    s = clean(v)
    if s.endswith(".0"):
        s = s[:-2]
    return re.sub(r"\D", "", s)[:5]

def generic(name):
    n = clean(name).upper()
    exact = {
        "CLINICAL TRIAL SITE", "CLINICAL SITE", "STUDY SITE",
        "TRIAL SITE", "RESEARCH SITE", "INVESTIGATIONAL SITE",
        "LOCAL SITE", "SITE", "UNKNOWN", "UNKNOWN SITE",
        "UNKNOWN LOCATION", "UNNAMED SITE", "UNNAMED FACILITY",
        "NOT APPLICABLE", "N A", "N/A", "NA", "NONE", "NULL"
    }
    return n in exact or bool(re.match(r"^LOCAL INSTITUTION(?:[- ]?\d*)?$", n))

def maps_url(row):
    parts = [
        clean(row.get("facility", "")),
        clean(row.get("city", "")),
        clean(row.get("state", "")),
        zip5(row.get("zip", ""))
    ]
    q = ", ".join(x for x in parts if x)
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote_plus(q)

print("=" * 70)
print("TRIAL LOCATION RESOLUTION QUEUE")
print("=" * 70)

df = pd.read_csv(INPUT)
print(f"Locations loaded: {len(df):,}")

df["facility"] = df["facility"].apply(clean)
df["city"] = df["city"].apply(clean)
df["state"] = df["state"].apply(clean)
df["zip"] = df["zip"].apply(zip5)

df["generic_facility"] = df["facility"].apply(generic)
df["google_maps_url"] = df.apply(maps_url, axis=1)

has_facility = df["facility"].ne("") & ~df["generic_facility"]
has_city = df["city"].ne("")
has_state = df["state"].ne("")
has_zip = df["zip"].ne("")

df["resolution_priority"] = 3
df.loc[has_facility & has_city & has_state, "resolution_priority"] = 2
df.loc[has_facility & has_city & has_state & has_zip, "resolution_priority"] = 1

df["resolution_category"] = df["resolution_priority"].map({
    1: "HIGH_PRIORITY_NAMED_FACILITY",
    2: "NAMED_FACILITY_MISSING_ZIP",
    3: "GENERIC_OR_INCOMPLETE"
})

# Put the most useful records first.
df = df.sort_values(
    ["resolution_priority", "state", "city", "facility"],
    ascending=[True, True, True, True]
)

df.to_csv(OUTPUT, index=False)

print("\nResolution categories:")
print(df["resolution_category"].value_counts())

print("\nOutput:")
print(f"  {OUTPUT}")
print("\nGoogle Maps URLs were generated for every row.")
print("=" * 70)