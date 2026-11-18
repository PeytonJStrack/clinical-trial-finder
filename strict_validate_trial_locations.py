import re
import urllib.parse
import pandas as pd
import numpy as np

# ============================================================
# STRICT FINAL LOCATION VALIDATION
# ============================================================
#
# Purpose:
#   1. Do NOT trust the previous "VERIFIED" flag blindly.
#   2. Keep only locations that pass strict checks for Transit.
#   3. Downgrade questionable matches to NEEDS_VALIDATION.
#   4. Give every location a Google Maps fallback.
#   5. Update the 143,630-row trial-site file.
#
# This script DOES NOT make new web/API requests.
# It is intentionally safe to run immediately.
# ============================================================

LOCATIONS_FILE = "consolidated_trial_locations.csv"
TRIALS_FILE = "cite_trial_sites_consolidated.csv"

OUTPUT_LOCATIONS = "final_trial_locations.csv"
OUTPUT_TRIALS = "cite_trial_sites_final.csv"
OUTPUT_REVIEW = "location_validation_queue.csv"

# Strict thresholds.
# A location is transit-ready only when:
#   - facility is not generic
#   - facility match score >= 90
#   - resolved address contains a 5-digit ZIP
#   - resolved ZIP exactly matches source ZIP
#   - coordinates are valid
MIN_MATCH_SCORE = 90


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def normalize_zip(value):
    if pd.isna(value):
        return ""
    value = str(value).strip()
    if value.endswith(".0"):
        value = value[:-2]
    digits = re.sub(r"\D", "", value)
    return digits[:5]


def is_generic_facility(value):
    name = clean_text(value).upper()

    generic_exact = {
        "CLINICAL TRIAL SITE",
        "CLINICAL SITE",
        "STUDY SITE",
        "TRIAL SITE",
        "RESEARCH SITE",
        "INVESTIGATIONAL SITE",
        "LOCAL SITE",
        "SITE",
        "UNKNOWN",
        "UNKNOWN SITE",
        "UNKNOWN LOCATION",
        "UNNAMED SITE",
        "UNNAMED FACILITY",
        "NOT APPLICABLE",
        "N A",
        "N/A",
        "NA",
        "NONE",
        "NULL",
    }

    if name in generic_exact:
        return True

    if re.match(r"^LOCAL INSTITUTION(?:[- ]?\d*)?$", name):
        return True

    return False


def extract_zip(address):
    """
    Pull the last US ZIP-like value from the resolved address.
    """
    if pd.isna(address):
        return ""

    matches = re.findall(
        r"\b(\d{5})(?:-\d{4})?\b",
        str(address)
    )

    if not matches:
        return ""

    return matches[-1]


def has_street_address(address):
    """
    Require an actual street-number component somewhere in the
    resolved address. This rejects city-only/postcode-only results.
    """
    if pd.isna(address):
        return False

    text = str(address)

    # Examples:
    # 2946, South Pierpont Drive
    # 130 South Bryn Mawr Avenue
    # 1 Hoag Drive
    return bool(
        re.search(
            r"(?:^|,\s*)\d{1,6}[A-Za-z]?(?:-\d{1,6})?(?:,\s|\s)",
            text
        )
    )


def valid_coordinates(lat, lon):
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False

    if not np.isfinite(lat) or not np.isfinite(lon):
        return False

    return -90 <= lat <= 90 and -180 <= lon <= 180


def build_google_maps_url(row):
    pieces = [
        clean_text(row.get("facility", "")),
        clean_text(row.get("city", "")),
        clean_text(row.get("state", "")),
        normalize_zip(row.get("zip", "")),
    ]

    pieces = [x for x in pieces if x]

    query = ", ".join(pieces)

    return (
        "https://www.google.com/maps/search/"
        "?api=1&query="
        + urllib.parse.quote_plus(query)
    )


# ============================================================
# LOAD
# ============================================================

print("=" * 70)
print("STRICT LOCATION VALIDATION")
print("=" * 70)

print("\nLoading consolidated location file...")
locations = pd.read_csv(LOCATIONS_FILE)

print(f"Locations loaded: {len(locations):,}")

print("\nLoading consolidated trial-site file...")
trials = pd.read_csv(TRIALS_FILE)

print(f"Trial-site rows loaded: {len(trials):,}")


# ============================================================
# NORMALIZE
# ============================================================

for col in ["facility", "city", "state", "facility_address"]:
    if col in locations.columns:
        locations[col] = locations[col].apply(clean_text)

locations["source_zip"] = locations["zip"].apply(normalize_zip)

locations["resolved_zip"] = locations["facility_address"].apply(
    extract_zip
)


# ============================================================
# STRICT VALIDATION
# ============================================================

locations["generic_facility"] = locations["facility"].apply(
    is_generic_facility
)

locations["score_pass"] = (
    pd.to_numeric(
        locations["facility_match_score"],
        errors="coerce"
    ).fillna(-1)
    >= MIN_MATCH_SCORE
)

locations["zip_pass"] = (
    locations["source_zip"].ne("")
    & locations["resolved_zip"].ne("")
    & locations["source_zip"].eq(locations["resolved_zip"])
)

locations["address_pass"] = locations["facility_address"].apply(
    has_street_address
)

locations["coordinate_pass"] = [
    valid_coordinates(lat, lon)
    for lat, lon in zip(
        locations["resolved_latitude"],
        locations["resolved_longitude"]
    )
]

locations["non_generic_pass"] = ~locations["generic_facility"]


locations["strict_transit_ready"] = (
    locations["score_pass"]
    & locations["zip_pass"]
    & locations["address_pass"]
    & locations["coordinate_pass"]
    & locations["non_generic_pass"]
)


# ============================================================
# FINAL STATUS
# ============================================================

locations["previous_status"] = locations["location_status"]

locations["location_status"] = np.where(
    locations["strict_transit_ready"],
    "VERIFIED",
    "NEEDS_VALIDATION"
)

locations["transit_ready"] = locations[
    "strict_transit_ready"
]


# ============================================================
# WHY DID A LOCATION FAIL?
# ============================================================

def failure_reason(row):

    reasons = []

    if row["generic_facility"]:
        reasons.append("GENERIC_FACILITY")

    if not row["score_pass"]:
        reasons.append("LOW_OR_MISSING_MATCH_SCORE")

    if not row["zip_pass"]:
        reasons.append("ZIP_MISMATCH_OR_MISSING")

    if not row["address_pass"]:
        reasons.append("NO_STREET_ADDRESS")

    if not row["coordinate_pass"]:
        reasons.append("INVALID_OR_MISSING_COORDINATES")

    if not reasons:
        return "PASS"

    return ";".join(reasons)


locations["validation_reason"] = locations.apply(
    failure_reason,
    axis=1
)


# ============================================================
# GOOGLE MAPS FALLBACK
# ============================================================

locations["google_maps_url"] = locations.apply(
    build_google_maps_url,
    axis=1
)


# ============================================================
# USER-FACING TRANSIT LABEL
# ============================================================

locations["location_action"] = np.where(
    locations["strict_transit_ready"],
    "Find Transit Directions",
    "Search in Google Maps"
)


# ============================================================
# CREATE REVIEW QUEUE
# ============================================================

review_columns = [
    "location_id",
    "facility",
    "source_facility_names",
    "city",
    "state",
    "zip",
    "facility_address",
    "resolved_latitude",
    "resolved_longitude",
    "facility_match_score",
    "previous_status",
    "location_status",
    "validation_reason",
    "google_maps_url",
    "source_location_count",
    "trial_site_record_count",
]

review = locations[
    ~locations["strict_transit_ready"]
].copy()

review = review[
    [c for c in review_columns if c in review.columns]
]

review.to_csv(
    OUTPUT_REVIEW,
    index=False
)


# ============================================================
# MERGE FINAL LOCATION DATA BACK TO ALL TRIAL RECORDS
# ============================================================

location_lookup_columns = [
    "location_id",
    "facility",
    "facility_address",
    "resolved_latitude",
    "resolved_longitude",
    "coordinate_source",
    "coordinate_confidence",
    "facility_match_score",
    "location_status",
    "transit_ready",
    "google_maps_url",
    "location_action",
    "validation_reason",
]

location_lookup = locations[
    [c for c in location_lookup_columns if c in locations.columns]
].copy()

# Avoid duplicate column names during merge.
for col in location_lookup.columns:
    if col != "location_id" and col in trials.columns:
        trials = trials.drop(columns=[col])

trials = trials.merge(
    location_lookup,
    on="location_id",
    how="left",
    suffixes=("", "_final")
)


# ============================================================
# SAVE
# ============================================================

# Remove internal helper columns from final location file.
internal_columns = [
    "source_zip",
    "resolved_zip",
    "generic_facility",
    "score_pass",
    "zip_pass",
    "address_pass",
    "coordinate_pass",
    "non_generic_pass",
    "strict_transit_ready",
    "previous_status",
]

final_locations = locations.drop(
    columns=[
        c for c in internal_columns
        if c in locations.columns
    ]
)

final_locations.to_csv(
    OUTPUT_LOCATIONS,
    index=False
)

trials.to_csv(
    OUTPUT_TRIALS,
    index=False
)


# ============================================================
# REPORT
# ============================================================

print("\n" + "=" * 70)
print("STRICT VALIDATION COMPLETE")
print("=" * 70)

print(
    f"Original consolidated locations: "
    f"{len(locations):,}"
)

print(
    f"Transit-ready / VERIFIED: "
    f"{locations['strict_transit_ready'].sum():,}"
)

print(
    f"Needs validation / Google Maps fallback: "
    f"{(~locations['strict_transit_ready']).sum():,}"
)

print(
    f"Generic facilities rejected: "
    f"{locations['generic_facility'].sum():,}"
)

print(
    f"ZIP mismatch/missing: "
    f"{(~locations['zip_pass']).sum():,}"
)

print(
    f"Low/missing match score: "
    f"{(~locations['score_pass']).sum():,}"
)

print(
    f"No usable street address: "
    f"{(~locations['address_pass']).sum():,}"
)

print(
    f"Invalid/missing coordinates: "
    f"{(~locations['coordinate_pass']).sum():,}"
)

print("\nFinal status:")
print(
    locations["location_status"]
    .value_counts()
)

print("\nFinal action:")
print(
    locations["location_action"]
    .value_counts()
)

print("\nOutputs:")
print(f"  {OUTPUT_LOCATIONS}")
print(f"  {OUTPUT_TRIALS}")
print(f"  {OUTPUT_REVIEW}")

print("=" * 70)
