import os
import re
import time

import pandas as pd
import requests
from rapidfuzz import fuzz, process

INPUT_FILE = "cite_trial_sites.csv"
OUTPUT_FILE = "cite_trial_sites_enriched.csv"
CACHE_FILE = "facility_geocode_cache.csv"

HEADERS = {
    "User-Agent": "CITE-County-Explorer/1.0"
}

NOMINATIM_URL = (
    "https://nominatim.openstreetmap.org/search"
)

OVERPASS_CACHE = "dc_osm_candidates.csv"


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_name(value):
    if pd.isna(value):
        return ""

    value = str(value).lower()

    value = re.sub(
        r"\(?\s*site\s*(number|no\.?)?\s*[:#-]?\s*\w+\s*\)?",
        " ",
        value,
    )

    value = re.sub(r"\([^)]*\)", " ", value)

    value = re.sub(
        r",?\s*(washington|district of columbia|dc)\s*$",
        " ",
        value,
    )

    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9\s]", " ", value)

    replacements = {
        "medstar": "med star",
        "med ctr": "medical center",
        "med center": "medical center",
        "hosp": "hospital",
        "univ": "university",
        "ctr": "center",
        "mwhc": "",
        "cnh": "",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    removable = [
        "clinical research institute",
        "clinical research center",
        "clinical research site",
        "investigational trial site",
        "investigational site",
        "trial site",
        "research site",
    ]

    for phrase in removable:
        value = value.replace(phrase, " ")

    value = re.sub(r"\s+", " ", value).strip()

    return value


# ============================================================
# DIRECT NOMINATIM LOOKUP
# ============================================================

def direct_lookup(
    facility,
    city,
    state,
):
    if not facility:
        return None

    query = f"{facility}, {city}, {state}"

    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 5,
        "addressdetails": 1,
    }

    try:
        response = requests.get(
            NOMINATIM_URL,
            params=params,
            headers=HEADERS,
            timeout=30,
        )

        response.raise_for_status()

        results = response.json()

    except Exception as error:
        print(f"    Nominatim error: {error}")
        return None

    if not results:
        return None

    target = normalize_name(facility)

    # Score the returned candidates.
    scored = []

    for result in results:
        display_name = result.get(
            "display_name",
            "",
        )

        result_name = result.get(
            "name",
            "",
        )

        candidate = normalize_name(
            result_name or display_name
        )

        if not candidate:
            continue

        score = max(
            fuzz.token_set_ratio(
                target,
                candidate,
            ),
            fuzz.ratio(
                target,
                candidate,
            ),
        )

        result["match_score"] = score
        scored.append(result)

    if not scored:
        return None

    scored.sort(
        key=lambda x: x["match_score"],
        reverse=True,
    )

    best = scored[0]

    # Do not accept weak direct matches.
    if best["match_score"] < 75:
        return None

    return {
        "facility_latitude": float(best["lat"]),
        "facility_longitude": float(best["lon"]),
        "facility_address": best.get(
            "display_name",
            "",
        ),
        "facility_geocode_source": "Nominatim",
        "facility_geocode_confidence": (
            "HIGH"
            if best["match_score"] >= 90
            else "MEDIUM"
        ),
        "facility_match_score": round(
            best["match_score"],
            1,
        ),
    }


# ============================================================
# LOAD DATA
# ============================================================

print("=" * 70)
print("CITE FACILITY GEOCODING / ENRICHMENT")
print("=" * 70)

print()
print("Loading trial-site data...")

trial_sites = pd.read_csv(INPUT_FILE)

print(
    f"Trial-site records: {len(trial_sites):,}"
)

unique_facilities = (
    trial_sites[
        [
            "facility",
            "city",
            "state",
            "zip",
        ]
    ]
    .dropna(subset=["facility"])
    .drop_duplicates()
    .reset_index(drop=True)
)

print(
    "Unique facility/location combinations: "
    f"{len(unique_facilities):,}"
)


# ============================================================
# LOAD CACHE
# ============================================================

if os.path.exists(CACHE_FILE):

    print()
    print(
        f"Loading existing cache: {CACHE_FILE}"
    )

    cache = pd.read_csv(CACHE_FILE)

    print(
        f"Cached facilities: {len(cache):,}"
    )

else:

    cache = pd.DataFrame(
        columns=[
            "facility",
            "city",
            "state",
            "zip",
            "facility_latitude",
            "facility_longitude",
            "facility_address",
            "facility_geocode_source",
            "facility_geocode_confidence",
            "facility_match_score",
        ]
    )

    print()
    print("No existing cache found.")


cached_keys = set(
    zip(
        cache["facility"].fillna("").astype(str),
        cache["city"].fillna("").astype(str),
        cache["state"].fillna("").astype(str),
        cache["zip"].fillna("").astype(str),
    )
)


# ============================================================
# DIRECT FACILITY RESOLUTION
# ============================================================

new_results = []

total = len(unique_facilities)

print()
print(
    "Resolving facilities with direct OSM lookup..."
)
print()

for i, row in unique_facilities.iterrows():

    facility = str(row["facility"])

    city = (
        ""
        if pd.isna(row["city"])
        else str(row["city"])
    )

    state = (
        ""
        if pd.isna(row["state"])
        else str(row["state"])
    )

    zip_code = (
        ""
        if pd.isna(row["zip"])
        else str(row["zip"])
    )

    key = (
        facility,
        city,
        state,
        zip_code,
    )

    if key in cached_keys:
        continue

    result = direct_lookup(
        facility,
        city,
        state,
    )

    if result is None:

        result = {
            "facility_latitude": None,
            "facility_longitude": None,
            "facility_address": "",
            "facility_geocode_source": "unresolved",
            "facility_geocode_confidence": "LOW",
            "facility_match_score": None,
        }

    result.update(
        {
            "facility": facility,
            "city": city,
            "state": state,
            "zip": zip_code,
        }
    )

    new_results.append(result)

    if len(new_results) % 25 == 0:

        print(
            f"  Resolved "
            f"{i + 1:,} / {total:,} "
            f"facilities"
        )

        # Save progress.
        progress = pd.concat(
            [
                cache,
                pd.DataFrame(new_results),
            ],
            ignore_index=True,
        )

        progress.to_csv(
            CACHE_FILE,
            index=False,
        )

        print(
            f"  Cache saved: "
            f"{len(progress):,}"
        )

        time.sleep(1)


# Save final cache.

if new_results:

    cache = pd.concat(
        [
            cache,
            pd.DataFrame(new_results),
        ],
        ignore_index=True,
    )

cache.to_csv(
    CACHE_FILE,
    index=False,
)

print()
print(
    f"Final facility cache: "
    f"{len(cache):,}"
)


# ============================================================
# MERGE BACK TO ALL TRIAL-SITE RECORDS
# ============================================================

print()
print("Merging resolved coordinates back into trial sites...")

lookup_columns = [
    "facility",
    "city",
    "state",
    "zip",
    "facility_latitude",
    "facility_longitude",
    "facility_address",
    "facility_geocode_source",
    "facility_geocode_confidence",
    "facility_match_score",
]

facility_lookup = cache[
    lookup_columns
].drop_duplicates(
    subset=[
        "facility",
        "city",
        "state",
        "zip",
    ],
    keep="last",
)

enriched = trial_sites.merge(
    facility_lookup,
    on=[
        "facility",
        "city",
        "state",
        "zip",
    ],
    how="left",
)


# ============================================================
# FALLBACK TO ORIGINAL COORDINATES
# ============================================================

enriched["resolved_latitude"] = (
    enriched["facility_latitude"]
    .fillna(enriched["latitude"])
)

enriched["resolved_longitude"] = (
    enriched["facility_longitude"]
    .fillna(enriched["longitude"])
)

enriched["coordinate_source"] = (
    enriched["facility_geocode_source"]
    .fillna("ClinicalTrials.gov")
)

enriched["coordinate_confidence"] = (
    enriched["facility_geocode_confidence"]
    .fillna("ORIGINAL")
)


# ============================================================
# SAVE
# ============================================================

enriched.to_csv(
    OUTPUT_FILE,
    index=False,
)

print()
print("=" * 70)
print("ENRICHMENT COMPLETE")
print("=" * 70)

print(
    f"Original records: "
    f"{len(trial_sites):,}"
)

print(
    f"Enriched records: "
    f"{len(enriched):,}"
)

print()
print("Coordinate sources:")
print(
    enriched["coordinate_source"]
    .value_counts(dropna=False)
)

print()
print(
    f"Saved to: {OUTPUT_FILE}"
)

print("=" * 70)