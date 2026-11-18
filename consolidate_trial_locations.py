from pathlib import Path
import re
import urllib.parse

import numpy as np
import pandas as pd
from rapidfuzz.fuzz import ratio

BASE_DIR = Path(__file__).resolve().parent

# Files from the previous step
DISTINCT_FILE = BASE_DIR / "distinct_trial_locations.csv"
VERIFIED_FILE = BASE_DIR / "verified_trial_locations.csv"
ORIGINAL_SITES_FILE = BASE_DIR / "cite_trial_sites.csv"

# Outputs
CONSOLIDATED_LOCATIONS_FILE = (
    BASE_DIR / "consolidated_trial_locations.csv"
)

CONSOLIDATED_SITES_FILE = (
    BASE_DIR / "cite_trial_sites_consolidated.csv"
)

REVIEW_FILE = (
    BASE_DIR / "location_duplicate_review.csv"
)

SAME_ZIP_THRESHOLD = 92

SAME_CITY_THRESHOLD = 97

MIN_NAME_LENGTH = 5

GENERIC_PATTERNS = [
    r"^LOCAL INSTITUTION$",
    r"^LOCAL INSTITUTION[- ]?\d+",
    r"^LOCAL SITE$",
    r"^CLINICAL SITE$",
    r"^CLINICAL TRIAL SITE$",
    r"^STUDY SITE$",
    r"^TRIAL SITE$",
    r"^RESEARCH SITE$",
    r"^INVESTIGATIONAL SITE$",
    r"^SITE$",
    r"^UNKNOWN$",
    r"^UNKNOWN SITE$",
    r"^UNKNOWN LOCATION$",
    r"^UNNAMED SITE$",
    r"^UNNAMED FACILITY$",
    r"^NOT APPLICABLE$",
    r"^N A$",
    r"^NA$",
    r"^NONE$",
    r"^NULL$",
    r"^N\/A$",
]


def normalize_text(value):
    """
    General-purpose text normalization.
    """
    if pd.isna(value):
        return ""

    value = str(value).upper().strip()

    value = value.replace("&", " AND ")

    value = re.sub(
        r"[^A-Z0-9]+",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip()

    return value


def normalize_facility(value):
    """
    Normalize facility names while preserving enough
    information to distinguish real facilities.
    """
    value = normalize_text(value)

    replacements = {
        "MED CTR": "MEDICAL CENTER",
        "MEDICAL CTR": "MEDICAL CENTER",
        "MED CTR.": "MEDICAL CENTER",
        "HOSP": "HOSPITAL",
        "UNIV": "UNIVERSITY",
        "CTR": "CENTER",
        "INST": "INSTITUTE",
        "HLTH": "HEALTH",
        "HEALTHCARE": "HEALTH CARE",
    }

    words = value.split()

    words = [
        replacements.get(word, word)
        for word in words
    ]

    return " ".join(words)


def normalize_city(value):
    return normalize_text(value)


def normalize_state(value):
    return normalize_text(value)


def normalize_zip(value):
    if pd.isna(value):
        return ""

    value = str(value).strip()

    # Remove .0 from numeric ZIPs
    value = re.sub(r"\.0$", "", value)

    match = re.search(
        r"\d{5}",
        value,
    )

    if match:
        return match.group(0)

    return ""


def is_generic_facility(value):
    """
    Determine whether a facility name is too generic to
    participate in fuzzy duplicate matching.
    """
    normalized = normalize_facility(value)

    if not normalized:
        return True

    for pattern in GENERIC_PATTERNS:
        if re.match(pattern, normalized):
            return True

    # Additional broad generic-name checks
    generic_words = {
        "CLINICAL TRIAL",
        "TRIAL",
        "CLINICAL SITE",
        "STUDY SITE",
        "RESEARCH SITE",
        "INVESTIGATIONAL SITE",
        "LOCAL INSTITUTION",
        "LOCAL SITE",
        "UNKNOWN",
        "UNKNOWN SITE",
        "UNNAMED SITE",
        "UNNAMED FACILITY",
    }

    if normalized in generic_words:
        return True

    return False

print("Loading location data...")

locations = pd.read_csv(
    DISTINCT_FILE,
    low_memory=False,
)

verified = pd.read_csv(
    VERIFIED_FILE,
    low_memory=False,
)

original_sites = pd.read_csv(
    ORIGINAL_SITES_FILE,
    low_memory=False,
)

print(
    f"Distinct locations loaded: "
    f"{len(locations):,}"
)

print(
    f"Original trial-site records: "
    f"{len(original_sites):,}"
)

locations["facility_norm"] = (
    locations["facility"]
    .map(normalize_facility)
)

locations["city_norm"] = (
    locations["city"]
    .map(normalize_city)
)

locations["state_norm"] = (
    locations["state"]
    .map(normalize_state)
)

locations["zip_norm"] = (
    locations["zip"]
    .map(normalize_zip)
)


locations["is_generic"] = (
    locations["facility"]
    .map(is_generic_facility)
)

generic_count = int(
    locations["is_generic"].sum()
)

print()
print(
    f"Generic facility names found: "
    f"{generic_count:,}"
)

locations.loc[
    locations["is_generic"],
    "facility"
] = "Clinical Trial Site"


# Recalculate normalized facility after renaming
locations["facility_norm"] = (
    locations["facility"]
    .map(normalize_facility)
)

locations["cluster_id"] = (
    locations["location_id"]
    .astype(str)
)

exact_keys = [
    "facility_norm",
    "city_norm",
    "state_norm",
    "zip_norm",
]

exact_groups = (
    locations[
        ~locations["is_generic"]
    ]
    .groupby(
        exact_keys,
        dropna=False,
    )
)

exact_merge_count = 0

for _, group in exact_groups:

    if len(group) <= 1:
        continue

    canonical = str(
        group.iloc[0]["cluster_id"]
    )

    for idx in group.index[1:]:
        locations.at[
            idx,
            "cluster_id"
        ] = canonical

        exact_merge_count += 1


print(
    f"Exact duplicate merges: "
    f"{exact_merge_count:,}"
)

review_rows = []

fuzzy_merge_count = 0


group_columns = [
    "state_norm",
    "city_norm",
]


groups = (
    locations[
        ~locations["is_generic"]
    ]
    .groupby(
        group_columns,
        dropna=False,
    )
)


for (
    (state_norm, city_norm),
    group,
) in groups:

    if not state_norm or not city_norm:
        continue

    if len(group) <= 1:
        continue

    # Work on a stable list of records
    records = list(group.index)

    for i in range(len(records)):

        idx_a = records[i]

        # If already merged, don't keep comparing
        # against the same cluster.
        cluster_a = locations.at[
            idx_a,
            "cluster_id",
        ]

        name_a = locations.at[
            idx_a,
            "facility_norm",
        ]

        zip_a = locations.at[
            idx_a,
            "zip_norm",
        ]

        if len(name_a) < MIN_NAME_LENGTH:
            continue

        for j in range(i + 1, len(records)):

            idx_b = records[j]

            cluster_b = locations.at[
                idx_b,
                "cluster_id",
            ]

            if cluster_a == cluster_b:
                continue

            name_b = locations.at[
                idx_b,
                "facility_norm",
            ]

            zip_b = locations.at[
                idx_b,
                "zip_norm",
            ]

            if len(name_b) < MIN_NAME_LENGTH:
                continue

            # Never fuzzy-match generic facilities.
            if (
                locations.at[idx_a, "is_generic"]
                or locations.at[idx_b, "is_generic"]
            ):
                continue

            similarity = ratio(
                name_a,
                name_b,
            )

            same_zip = (
                zip_a
                and zip_b
                and zip_a == zip_b
            )

            if (
                same_zip
                and similarity >= SAME_ZIP_THRESHOLD
            ):

                canonical = min(
                    cluster_a,
                    cluster_b,
                )

                locations.loc[
                    locations["cluster_id"].isin(
                        [
                            cluster_a,
                            cluster_b,
                        ]
                    ),
                    "cluster_id",
                ] = canonical

                fuzzy_merge_count += 1

                review_rows.append({
                    "match_type": "AUTO_MERGED_SAME_ZIP",
                    "facility_a": locations.at[
                        idx_a,
                        "facility",
                    ],
                    "facility_b": locations.at[
                        idx_b,
                        "facility",
                    ],
                    "city": locations.at[
                        idx_a,
                        "city",
                    ],
                    "state": locations.at[
                        idx_a,
                        "state",
                    ],
                    "zip_a": zip_a,
                    "zip_b": zip_b,
                    "similarity": similarity,
                    "decision": "MERGED",
                })

                cluster_a = canonical

            elif (
                similarity >= SAME_CITY_THRESHOLD
                and not same_zip
            ):

                review_rows.append({
                    "match_type": "POTENTIAL_SAME_FACILITY_DIFFERENT_ZIP",
                    "facility_a": locations.at[
                        idx_a,
                        "facility",
                    ],
                    "facility_b": locations.at[
                        idx_b,
                        "facility",
                    ],
                    "city": locations.at[
                        idx_a,
                        "city",
                    ],
                    "state": locations.at[
                        idx_a,
                        "state",
                    ],
                    "zip_a": zip_a,
                    "zip_b": zip_b,
                    "similarity": similarity,
                    "decision": "REVIEW",
                })


print(
    f"Fuzzy auto-merges: "
    f"{fuzzy_merge_count:,}"
)

review = pd.DataFrame(
    review_rows
)

if not review.empty:
    review = review.sort_values(
        [
            "decision",
            "similarity",
        ],
        ascending=[
            True,
            False,
        ],
    )

review.to_csv(
    REVIEW_FILE,
    index=False,
)

verified_lookup = verified.copy()

if "location_id" in verified_lookup.columns:

    verified_lookup["has_verified_coordinates"] = (
        pd.to_numeric(
            verified_lookup[
                "resolved_latitude"
            ],
            errors="coerce",
        ).notna()
        &
        pd.to_numeric(
            verified_lookup[
                "resolved_longitude"
            ],
            errors="coerce",
        ).notna()
    )

else:

    verified_lookup[
        "has_verified_coordinates"
    ] = False


locations = locations.merge(
    verified_lookup[
        [
            "location_id",
            "facility_address",
            "resolved_latitude",
            "resolved_longitude",
            "coordinate_source",
            "coordinate_confidence",
            "facility_match_score",
            "location_status",
            "transit_ready",
        ]
    ],
    on="location_id",
    how="left",
    suffixes=("", "_verified"),
)


locations["has_address"] = (
    locations["facility_address"]
    .fillna("")
    .astype(str)
    .str.strip()
    .ne("")
)


locations["has_verified_coordinates"] = (
    pd.to_numeric(
        locations["resolved_latitude"],
        errors="coerce",
    ).notna()
    &
    pd.to_numeric(
        locations["resolved_longitude"],
        errors="coerce",
    ).notna()
)


locations["record_count"] = (
    pd.to_numeric(
        locations["trial_site_record_count"],
        errors="coerce",
    )
    .fillna(0)
)

locations = locations.sort_values(
    [
        "cluster_id",
        "has_verified_coordinates",
        "has_address",
        "record_count",
    ],
    ascending=[
        True,
        False,
        False,
        False,
    ],
)


canonical = (
    locations
    .drop_duplicates(
        "cluster_id",
        keep="first",
    )
    .copy()
)

cluster_counts = (
    locations
    .groupby("cluster_id")
    .size()
    .rename("source_location_count")
    .reset_index()
)

canonical = canonical.merge(
    cluster_counts,
    on="cluster_id",
    how="left",
)

names_by_cluster = (
    locations
    .groupby("cluster_id")["facility"]
    .apply(
        lambda values:
        " | ".join(
            sorted(
                set(
                    str(v).strip()
                    for v in values
                    if str(v).strip()
                )
            )
        )
    )
    .rename("source_facility_names")
    .reset_index()
)

canonical = canonical.merge(
    names_by_cluster,
    on="cluster_id",
    how="left",
)

canonical["facility"] = canonical[
    "facility"
].fillna("Clinical Trial Site")


canonical.loc[
    canonical["facility"].map(
        is_generic_facility
    ),
    "facility",
] = "Clinical Trial Site"

def google_maps_url(row):

    parts = [
        row.get("facility", ""),
        row.get("facility_address", ""),
        row.get("city", ""),
        row.get("state", ""),
        row.get("zip", ""),
    ]

    query = ", ".join(
        str(x).strip()
        for x in parts
        if str(x).strip()
        and str(x).strip().lower() != "nan"
    )

    return (
        "https://www.google.com/maps/search/?api=1"
        "&query="
        + urllib.parse.quote_plus(query)
    )


canonical["google_maps_url"] = (
    canonical.apply(
        google_maps_url,
        axis=1,
    )
)

canonical["transit_ready"] = (
    canonical["transit_ready"]
    .fillna(False)
    .astype(bool)
)


canonical["location_status"] = (
    canonical["location_status"]
    .fillna("UNRESOLVED")
)

cluster_to_id = {
    cluster: i + 1
    for i, cluster in enumerate(
        sorted(
            canonical[
                "cluster_id"
            ].unique()
        )
    )
}


canonical["location_id"] = (
    canonical["cluster_id"]
    .map(cluster_to_id)
)

output_columns = [
    "location_id",
    "facility",
    "source_facility_names",
    "city",
    "state",
    "zip",
    "country",

    "facility_address",

    "resolved_latitude",
    "resolved_longitude",

    "coordinate_source",
    "coordinate_confidence",
    "facility_match_score",

    "location_status",
    "transit_ready",

    "google_maps_url",

    "source_location_count",
    "trial_site_record_count",
]


canonical[
    output_columns
].to_csv(
    CONSOLIDATED_LOCATIONS_FILE,
    index=False,
)

locations["new_location_id"] = (
    locations["cluster_id"]
    .map(cluster_to_id)
)


location_mapping = (
    locations[
        [
            "location_id",
            "new_location_id",
        ]
    ]
    .drop_duplicates(
        "location_id"
    )
)

# Rebuild original location key
original_sites["facility_norm"] = (
    original_sites["facility"]
    .map(normalize_facility)
)

original_sites["city_norm"] = (
    original_sites["city"]
    .map(normalize_city)
)

original_sites["state_norm"] = (
    original_sites["state"]
    .map(normalize_state)
)

original_sites["zip_norm"] = (
    original_sites["zip"]
    .map(normalize_zip)
)


original_sites["location_key"] = (
    original_sites[
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


# Find the original distinct-location row
key_to_old_id = (
    locations[
        [
            "location_key",
            "location_id",
        ]
    ]
    .drop_duplicates(
        "location_key"
    )
)


original_sites = original_sites.merge(
    key_to_old_id,
    on="location_key",
    how="left",
)


original_sites = original_sites.merge(
    location_mapping,
    on="location_id",
    how="left",
)

canonical_details = canonical[
    [
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
    ]
].copy()


canonical_details = canonical_details.rename(
    columns={
        "location_id": "consolidated_location_id",
        "facility": "consolidated_facility",
    }
)


original_sites = original_sites.merge(
    canonical_details,
    left_on="new_location_id",
    right_on="consolidated_location_id",
    how="left",
)

original_sites.loc[
    original_sites["consolidated_facility"]
    .fillna("")
    .map(is_generic_facility),
    "consolidated_facility",
] = "Clinical Trial Site"

original_sites.to_csv(
    CONSOLIDATED_SITES_FILE,
    index=False,
)

print()
print("=" * 70)
print("TRIAL LOCATION CONSOLIDATION COMPLETE")
print("=" * 70)

print(
    f"Original trial-site rows: "
    f"{len(original_sites):,}"
)

print(
    f"Original distinct locations: "
    f"{len(locations):,}"
)

print(
    f"Consolidated physical-location clusters: "
    f"{len(canonical):,}"
)

print(
    f"Location clusters eliminated: "
    f"{len(locations) - len(canonical):,}"
)

print()

print(
    f"Generic facilities renamed: "
    f"{generic_count:,}"
)

print(
    f"Exact duplicate merges: "
    f"{exact_merge_count:,}"
)

print(
    f"Fuzzy duplicate merges: "
    f"{fuzzy_merge_count:,}"
)

print()

if not review.empty:

    print(
        f"Potential matches requiring review: "
        f"{len(review):,}"
    )

else:

    print(
        "Potential matches requiring review: 0"
    )

print()

print(
    f"Consolidated locations file:\n"
    f"  {CONSOLIDATED_LOCATIONS_FILE}"
)

print(
    f"Consolidated trial-site file:\n"
    f"  {CONSOLIDATED_SITES_FILE}"
)

print(
    f"Duplicate review file:\n"
    f"  {REVIEW_FILE}"
)

print("=" * 70)