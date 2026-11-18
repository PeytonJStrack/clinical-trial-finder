from pathlib import Path
import re
import json
import urllib.parse
import pandas as pd
import numpy as np
from rapidfuzz.fuzz import ratio

BASE_DIR = Path(__file__).resolve().parent

TRIAL_FILE = BASE_DIR / "cite_trial_sites.csv"

# Existing files from our previous geocoding work
ENRICHED_FILE = BASE_DIR / "cite_trial_sites_enriched.csv"
FINAL_FILE = BASE_DIR / "cite_trial_sites_final.csv"
FACILITY_CACHE_FILE = BASE_DIR / "facility_geocode_cache.csv"
GENERIC_CACHE_FILE = BASE_DIR / "generic_site_geocode_cache.csv"
LOCATION_CACHE_FILE = BASE_DIR / "clinicaltrials_location_cache.csv"

# Outputs
DISTINCT_LOCATIONS_FILE = BASE_DIR / "distinct_trial_locations.csv"
VERIFIED_LOCATIONS_FILE = BASE_DIR / "verified_trial_locations.csv"
FINAL_SITES_FILE = BASE_DIR / "cite_trial_sites_verified.csv"

def clean_text(value):
    if pd.isna(value):
        return ""

    value = str(value).upper().strip()

    # Normalize common punctuation
    value = value.replace("&", " AND ")

    # Remove punctuation
    value = re.sub(r"[^A-Z0-9]+", " ", value)

    # Collapse whitespace
    value = re.sub(r"\s+", " ", value).strip()

    return value


def clean_zip(value):
    if pd.isna(value):
        return ""

    value = str(value).strip()

    # Handle values such as 12345.0
    value = re.sub(r"\.0$", "", value)

    # Keep first five ZIP digits
    match = re.search(r"\d{5}", value)

    if match:
        return match.group(0)

    return ""


def normalize_facility(value):
    value = clean_text(value)

    # Common facility-name variations
    replacements = {
        "MEDICAL CTR": "MEDICAL CENTER",
        "MED CTR": "MEDICAL CENTER",
        "HOSP": "HOSPITAL",
        "UNIV": "UNIVERSITY",
        "CTR": "CENTER",
        "INST": "INSTITUTE",
        "HLTH": "HEALTH",
        "HEALTHCARE": "HEALTH CARE",
    }

    words = value.split()

    normalized_words = [
        replacements.get(word, word)
        for word in words
    ]

    return " ".join(normalized_words)


def normalize_state(value):
    return clean_text(value)


def normalize_city(value):
    return clean_text(value)

def google_maps_search_url(
    facility,
    address="",
    city="",
    state="",
    zip_code=""
):
    parts = [
        facility,
        address,
        city,
        state,
        zip_code,
    ]

    query = ", ".join(
        str(x).strip()
        for x in parts
        if str(x).strip()
    )

    encoded = urllib.parse.quote_plus(query)

    return (
        "https://www.google.com/maps/search/?api=1"
        f"&query={encoded}"
    )

print("Loading trial-site data...")

sites = pd.read_csv(
    TRIAL_FILE,
    low_memory=False
)

print(f"Original trial-site records: {len(sites):,}")

sites["facility_norm"] = sites["facility"].map(
    normalize_facility
)

sites["city_norm"] = sites["city"].map(
    normalize_city
)

sites["state_norm"] = sites["state"].map(
    normalize_state
)

sites["zip_norm"] = sites["zip"].map(
    clean_zip
)

location_key = [
    "facility_norm",
    "city_norm",
    "state_norm",
    "zip_norm",
]

sites["location_key"] = (
    sites[location_key]
    .astype(str)
    .agg("|".join, axis=1)
)


distinct = (
    sites
    .drop_duplicates("location_key")
    .copy()
)

distinct["location_id"] = np.arange(
    1,
    len(distinct) + 1
)


print(
    f"Distinct normalized locations: "
    f"{len(distinct):,}"
)

print(
    f"Deduplication reduction: "
    f"{len(sites) - len(distinct):,} records"
)

location_counts = (
    sites.groupby("location_key")
    .size()
    .rename("trial_site_record_count")
    .reset_index()
)

distinct = distinct.merge(
    location_counts,
    on="location_key",
    how="left"
)

distinct[
    [
        "location_id",
        "facility",
        "city",
        "state",
        "zip",
        "country",
        "latitude",
        "longitude",
        "county",
        "state_fips",
        "county_fips",
        "facility_norm",
        "city_norm",
        "state_norm",
        "zip_norm",
        "location_key",
        "trial_site_record_count",
    ]
].to_csv(
    DISTINCT_LOCATIONS_FILE,
    index=False
)

print(
    f"Saved distinct locations to "
    f"{DISTINCT_LOCATIONS_FILE.name}"
)

def load_if_exists(path):
    if not path.exists():
        return pd.DataFrame()

    print(f"Loading {path.name}...")

    return pd.read_csv(
        path,
        low_memory=False
    )


enriched = load_if_exists(ENRICHED_FILE)
final = load_if_exists(FINAL_FILE)
facility_cache = load_if_exists(FACILITY_CACHE_FILE)
generic_cache = load_if_exists(GENERIC_CACHE_FILE)

geocode_results = []


def add_geocode_dataframe(
    frame,
    address_column,
    lat_column,
    lon_column,
    source_column=None,
    confidence_column=None,
    match_score_column=None,
):
    if frame.empty:
        return

    required = [
        "facility",
        "city",
        "state",
        "zip",
        lat_column,
        lon_column,
    ]

    if not all(c in frame.columns for c in required):
        return

    temp = frame.copy()

    temp["facility_norm"] = temp["facility"].map(
        normalize_facility
    )

    temp["city_norm"] = temp["city"].map(
        normalize_city
    )

    temp["state_norm"] = temp["state"].map(
        normalize_state
    )

    temp["zip_norm"] = temp["zip"].map(
        clean_zip
    )

    temp["location_key"] = (
        temp[
            [
                "facility_norm",
                "city_norm",
                "state_norm",
                "zip_norm",
            ]
        ]
        .astype(str)
        .agg("|".join, axis=1)
    )

    output = pd.DataFrame({
        "location_key": temp["location_key"],
        "facility_address": (
            temp[address_column]
            if address_column in temp.columns
            else ""
        ),
        "resolved_latitude": pd.to_numeric(
            temp[lat_column],
            errors="coerce"
        ),
        "resolved_longitude": pd.to_numeric(
            temp[lon_column],
            errors="coerce"
        ),
    })

    if source_column and source_column in temp.columns:
        output["coordinate_source"] = (
            temp[source_column]
        )
    else:
        output["coordinate_source"] = ""

    if confidence_column and confidence_column in temp.columns:
        output["coordinate_confidence"] = (
            temp[confidence_column]
        )
    else:
        output["coordinate_confidence"] = ""

    if match_score_column and match_score_column in temp.columns:
        output["facility_match_score"] = pd.to_numeric(
            temp[match_score_column],
            errors="coerce"
        )
    else:
        output["facility_match_score"] = np.nan

    geocode_results.append(output)


# Existing enriched/final data
add_geocode_dataframe(
    enriched,
    "facility_address",
    "resolved_latitude",
    "resolved_longitude",
    "coordinate_source",
    "coordinate_confidence",
    "facility_match_score",
)

add_geocode_dataframe(
    final,
    "facility_address",
    "resolved_latitude",
    "resolved_longitude",
    "coordinate_source",
    "coordinate_confidence",
    "facility_match_score",
)

# Facility cache
add_geocode_dataframe(
    facility_cache,
    "facility_address",
    "facility_latitude",
    "facility_longitude",
    "facility_geocode_source",
    "facility_geocode_confidence",
    "facility_match_score",
)

# Generic cache
add_geocode_dataframe(
    generic_cache,
    "address",
    "latitude",
    "longitude",
    "status",
)

if geocode_results:

    geocodes = pd.concat(
        geocode_results,
        ignore_index=True
    )

    # Prefer rows with coordinates
    geocodes["has_coordinates"] = (
        geocodes["resolved_latitude"].notna()
        & geocodes["resolved_longitude"].notna()
    )

    # Prefer high-confidence records
    confidence_rank = {
        "HIGH": 3,
        "MEDIUM": 2,
        "LOW": 1,
        "": 0,
    }

    geocodes["confidence_rank"] = (
        geocodes["coordinate_confidence"]
        .fillna("")
        .astype(str)
        .str.upper()
        .map(confidence_rank)
        .fillna(0)
    )

    geocodes = geocodes.sort_values(
        [
            "location_key",
            "has_coordinates",
            "confidence_rank",
            "facility_match_score",
        ],
        ascending=[
            True,
            False,
            False,
            False,
        ],
        na_position="last",
    )

    geocodes = geocodes.drop_duplicates(
        "location_key",
        keep="first"
    )

else:

    geocodes = pd.DataFrame(
        columns=[
            "location_key",
            "facility_address",
            "resolved_latitude",
            "resolved_longitude",
            "coordinate_source",
            "coordinate_confidence",
            "facility_match_score",
        ]
    )

verified = distinct.merge(
    geocodes,
    on="location_key",
    how="left"
)

def normalize_confidence(value):
    value = str(value).upper().strip()

    if value in {"HIGH", "MEDIUM", "LOW"}:
        return value

    return ""


verified["coordinate_confidence"] = (
    verified["coordinate_confidence"]
    .fillna("")
    .map(normalize_confidence)
)


verified["coordinate_source"] = (
    verified["coordinate_source"]
    .fillna("")
    .astype(str)
    .str.strip()
)

verified["original_latitude"] = pd.to_numeric(
    verified["latitude"],
    errors="coerce"
)

verified["original_longitude"] = pd.to_numeric(
    verified["longitude"],
    errors="coerce"
)


has_verified_coordinates = (
    verified["resolved_latitude"].notna()
    & verified["resolved_longitude"].notna()
)


has_original_coordinates = (
    verified["original_latitude"].notna()
    & verified["original_longitude"].notna()
)

verified["location_status"] = "UNRESOLVED"

verified.loc[
    has_original_coordinates,
    "location_status"
] = "APPROXIMATE"

verified.loc[
    has_verified_coordinates,
    "location_status"
] = "VERIFIED"

verified["transit_ready"] = (
    verified["location_status"] == "VERIFIED"
)

verified["map_latitude"] = np.where(
    has_verified_coordinates,
    verified["resolved_latitude"],
    verified["original_latitude"],
)

verified["map_longitude"] = np.where(
    has_verified_coordinates,
    verified["resolved_longitude"],
    verified["original_longitude"],
)

verified["google_maps_url"] = verified.apply(
    lambda row: google_maps_search_url(
        facility=row["facility"],
        address=(
            row["facility_address"]
            if pd.notna(row["facility_address"])
            else ""
        ),
        city=row["city"],
        state=row["state"],
        zip_code=row["zip"],
    ),
    axis=1,
)

def build_location_label(row):
    parts = []

    if pd.notna(row.get("facility_address")):
        address = str(
            row["facility_address"]
        ).strip()

        if address:
            parts.append(address)

    city = str(row.get("city", "")).strip()
    state = str(row.get("state", "")).strip()
    zip_code = str(row.get("zip", "")).strip()

    city_state_zip = ", ".join(
        x for x in [
            city,
            state,
        ]
        if x
    )

    if zip_code:
        city_state_zip = (
            f"{city_state_zip} {zip_code}"
            if city_state_zip
            else zip_code
        )

    if city_state_zip:
        parts.append(city_state_zip)

    return ", ".join(parts)


verified["location_label"] = verified.apply(
    build_location_label,
    axis=1,
)

verified_columns = [
    "location_id",
    "facility",
    "city",
    "state",
    "zip",
    "country",

    "facility_address",

    "original_latitude",
    "original_longitude",

    "resolved_latitude",
    "resolved_longitude",

    "map_latitude",
    "map_longitude",

    "coordinate_source",
    "coordinate_confidence",
    "facility_match_score",

    "location_status",
    "transit_ready",

    "google_maps_url",
    "location_label",

    "trial_site_record_count",

    "facility_norm",
    "city_norm",
    "state_norm",
    "zip_norm",
    "location_key",
]

verified[
    verified_columns
].to_csv(
    VERIFIED_LOCATIONS_FILE,
    index=False
)

location_columns = [
    "location_id",
    "facility_address",
    "resolved_latitude",
    "resolved_longitude",
    "map_latitude",
    "map_longitude",
    "coordinate_source",
    "coordinate_confidence",
    "facility_match_score",
    "location_status",
    "transit_ready",
    "google_maps_url",
    "location_label",
]

sites_final = sites.merge(
    verified[
        [
            "location_key",
            *location_columns,
        ]
    ],
    on="location_key",
    how="left",
)

sites_final.to_csv(
    FINAL_SITES_FILE,
    index=False
)

print()
print("=" * 60)
print("LOCATION PROCESSING COMPLETE")
print("=" * 60)

print(
    f"Original trial-site records: "
    f"{len(sites):,}"
)

print(
    f"Distinct normalized locations: "
    f"{len(verified):,}"
)

print(
    f"Reduction in location records: "
    f"{len(sites) - len(verified):,}"
)

print()

print("Location status:")

print(
    verified["location_status"]
    .value_counts(dropna=False)
)

print()

print("Transit-ready locations:")

print(
    verified["transit_ready"]
    .value_counts(dropna=False)
)

print()

print("Coordinate sources:")

print(
    verified["coordinate_source"]
    .replace("", "UNSPECIFIED")
    .value_counts()
    .head(20)
)

print()

print("Output files:")
print(
    f"  {DISTINCT_LOCATIONS_FILE}"
)
print(
    f"  {VERIFIED_LOCATIONS_FILE}"
)
print(
    f"  {FINAL_SITES_FILE}"
)

print("=" * 60)