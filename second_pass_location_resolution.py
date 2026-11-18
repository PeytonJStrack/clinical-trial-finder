from pathlib import Path
import re
import time
import pandas as pd
import requests


# ============================================================
# CITE SECOND-PASS LOCATION RESOLVER
# ============================================================
#
# Purpose:
#   Recover additional high-confidence trial-site locations
#   from the strict-validation queue.
#
# IMPORTANT:
#   This script does NOT automatically declare locations
#   VERIFIED.
#
# It creates resolution candidates which are subsequently
# evaluated by strict_validate_trial_locations.py.
#
# ============================================================


BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = BASE_DIR / "location_validation_queue.csv"

OUTPUT_FILE = (
    BASE_DIR /
    "location_second_pass_results.csv"
)

CACHE_FILE = (
    BASE_DIR /
    "location_geocode_cache.csv"
)


# ============================================================
# SETTINGS
# ============================================================

# Nominatim's public service requires responsible usage.
#
# Keep this at or below 1 request/second for the public
# endpoint.
#
# For a 41k-row queue, caching and deduplication are therefore
# extremely important.

REQUEST_DELAY_SECONDS = 1.05

NOMINATIM_URL = (
    "https://nominatim.openstreetmap.org/search"
)

USER_AGENT = (
    "CITE-Clinical-Trial-Access-Explorer/"
    "1.0 "
    "(clinical-trial-location-resolution)"
)


# ============================================================
# NORMALIZATION
# ============================================================

def clean_text(value):

    if pd.isna(value):
        return ""

    text = str(value).strip()

    if not text:
        return ""

    text = re.sub(
        r"/ID#\s*\d+",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def normalize_text(value):

    text = clean_text(value).lower()

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def normalize_zip(value):

    if pd.isna(value):
        return ""

    text = str(value).strip()

    if not text:
        return ""

    # Handle ZIP+4.
    match = re.search(
        r"\b(\d{5})(?:-\d{4})?\b",
        text
    )

    if match:
        return match.group(1)

    return text


# ============================================================
# STATE NORMALIZATION
# ============================================================

STATE_MAP = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


def normalize_state(value):

    text = clean_text(value)

    if not text:
        return ""

    lower = text.lower()

    if lower in STATE_MAP:
        return STATE_MAP[lower]

    if len(text) == 2:
        return text.upper()

    return text.upper()


# ============================================================
# GOOGLE MAPS URL
# ============================================================

def google_maps_url(
    facility,
    city,
    state,
    zip_code
):

    parts = [
        clean_text(facility),
        clean_text(city),
        normalize_state(state),
        normalize_zip(zip_code),
    ]

    parts = [
        x for x in parts if x
    ]

    query = ", ".join(parts)

    return (
        "https://www.google.com/maps/search/?api=1"
        "&query="
        + requests.utils.quote(query)
    )


# ============================================================
# LOAD CACHE
# ============================================================

def load_cache():

    if not CACHE_FILE.exists():

        return pd.DataFrame(
            columns=[
                "query_key",
                "query",
                "latitude",
                "longitude",
                "display_name",
                "address_type",
                "raw_json",
            ]
        )

    cache = pd.read_csv(
        CACHE_FILE,
        low_memory=False
    )

    print(
        f"Loaded geocode cache: "
        f"{len(cache):,} rows"
    )

    return cache


# ============================================================
# SAVE CACHE
# ============================================================

def save_cache(cache):

    cache.to_csv(
        CACHE_FILE,
        index=False
    )


# ============================================================
# QUERY KEY
# ============================================================

def make_query_key(
    facility,
    city,
    state,
    zip_code
):

    return "|".join(
        [
            normalize_text(facility),
            normalize_text(city),
            normalize_state(state),
            normalize_zip(zip_code),
        ]
    )


# ============================================================
# NOMINATIM SEARCH
# ============================================================

def geocode(
    facility,
    city,
    state,
    zip_code
):

    state_code = normalize_state(state)

    query_parts = [
        clean_text(facility),
        clean_text(city),
        state_code,
        normalize_zip(zip_code),
        "USA",
    ]

    query_parts = [
        x for x in query_parts
        if x
    ]

    query = ", ".join(query_parts)

    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 5,
        "countrycodes": "us",
        "addressdetails": 1,
    }

    headers = {
        "User-Agent": USER_AGENT
    }

    try:

        response = requests.get(
            NOMINATIM_URL,
            params=params,
            headers=headers,
            timeout=30,
        )

        response.raise_for_status()

        results = response.json()

        return query, results, None

    except Exception as exc:

        return query, [], str(exc)


# ============================================================
# RESULT SCORING
# ============================================================

def score_result(
    facility,
    city,
    state,
    zip_code,
    result
):

    address = result.get(
        "address",
        {}
    )

    target_city = normalize_text(city)

    target_state = normalize_state(state)

    target_zip = normalize_zip(zip_code)

    result_city = normalize_text(
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or ""
    )

    result_state = normalize_state(
        address.get("state", "")
    )

    result_zip = normalize_zip(
        address.get("postcode", "")
    )

    score = 0

    reasons = []

    # --------------------------------------------------------
    # City
    # --------------------------------------------------------

    if (
        target_city
        and result_city
        and target_city == result_city
    ):

        score += 30

        reasons.append(
            "CITY_MATCH"
        )

    # --------------------------------------------------------
    # State
    # --------------------------------------------------------

    if (
        target_state
        and result_state
        and target_state == result_state
    ):

        score += 30

        reasons.append(
            "STATE_MATCH"
        )

    # --------------------------------------------------------
    # ZIP
    # --------------------------------------------------------

    if (
        target_zip
        and result_zip
        and target_zip == result_zip
    ):

        score += 30

        reasons.append(
            "ZIP_MATCH"
        )

    # --------------------------------------------------------
    # ZIP disagreement
    # --------------------------------------------------------

    elif (
        target_zip
        and result_zip
        and target_zip != result_zip
    ):

        reasons.append(
            "ZIP_CONFLICT"
        )

    # --------------------------------------------------------
    # Facility name
    # --------------------------------------------------------

    result_display = normalize_text(
        result.get(
            "display_name",
            ""
        )
    )

    facility_norm = normalize_text(
        facility
    )

    facility_tokens = {
        x for x in facility_norm.split()
        if len(x) > 2
    }

    result_tokens = {
        x for x in result_display.split()
        if len(x) > 2
    }

    overlap = (
        facility_tokens &
        result_tokens
    )

    if facility_tokens:

        facility_overlap = (
            len(overlap)
            /
            len(facility_tokens)
        )

        if facility_overlap >= 0.75:

            score += 10

            reasons.append(
                "FACILITY_STRONG_MATCH"
            )

        elif facility_overlap >= 0.40:

            score += 5

            reasons.append(
                "FACILITY_PARTIAL_MATCH"
            )

    return score, reasons


# ============================================================
# RESOLUTION CLASSIFICATION
# ============================================================

def classify_result(score, reasons):

    if (
        "CITY_MATCH" in reasons
        and "STATE_MATCH" in reasons
        and "ZIP_MATCH" in reasons
        and score >= 90
    ):

        return "STRONG_CANDIDATE"

    if (
        "CITY_MATCH" in reasons
        and "STATE_MATCH" in reasons
        and score >= 60
    ):

        return "GOOD_CANDIDATE"

    if (
        "STATE_MATCH" in reasons
        and score >= 40
    ):

        return "WEAK_CANDIDATE"

    return "UNRESOLVED"


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("CITE SECOND-PASS LOCATION RESOLVER")
    print("=" * 70)

    if not INPUT_FILE.exists():

        raise FileNotFoundError(
            INPUT_FILE
        )

    df = pd.read_csv(
        INPUT_FILE,
        low_memory=False
    )

    print(
        f"\nValidation queue: "
        f"{len(df):,}"
    )

    cache = load_cache()

    cache_lookup = {
        row["query_key"]: row
        for _, row in cache.iterrows()
    }

    # --------------------------------------------------------
    # Deduplicate queries
    # --------------------------------------------------------

    df["query_key"] = df.apply(
        lambda row: make_query_key(
            row["facility"],
            row["city"],
            row["state"],
            row["zip"],
        ),
        axis=1,
    )

    unique_queries = (
        df[
            [
                "query_key",
                "facility",
                "city",
                "state",
                "zip",
            ]
        ]
        .drop_duplicates(
            "query_key"
        )
    )

    print(
        f"Unique location queries: "
        f"{len(unique_queries):,}"
    )

    # --------------------------------------------------------
    # Process
    # --------------------------------------------------------

    results = []

    new_cache_rows = []

    total = len(unique_queries)

    for i, row in enumerate(
        unique_queries.itertuples(
            index=False
        ),
        start=1,
    ):

        key = row.query_key

        # ----------------------------------------------------
        # Cached result
        # ----------------------------------------------------

        if key in cache_lookup:

            cached = cache_lookup[key]

            try:
                raw_results = [
                    cached["raw_json"]
                ]

                import json

                parsed = json.loads(
                    cached["raw_json"]
                )

            except Exception:

                parsed = []

            query = cached["query"]

        else:

            query, parsed, error = geocode(
                row.facility,
                row.city,
                row.state,
                row.zip,
            )

            import json

            raw_json = json.dumps(
                parsed
            )

            new_cache_rows.append(
                {
                    "query_key": key,
                    "query": query,
                    "latitude": (
                        parsed[0].get("lat")
                        if parsed
                        else None
                    ),
                    "longitude": (
                        parsed[0].get("lon")
                        if parsed
                        else None
                    ),
                    "display_name": (
                        parsed[0].get(
                            "display_name"
                        )
                        if parsed
                        else None
                    ),
                    "address_type": (
                        parsed[0].get(
                            "type"
                        )
                        if parsed
                        else None
                    ),
                    "raw_json": raw_json,
                }
            )

            if error:

                results.append(
                    {
                        "query_key": key,
                        "facility": row.facility,
                        "city": row.city,
                        "state": row.state,
                        "zip": row.zip,
                        "second_pass_status":
                            "GEOCODER_ERROR",
                        "candidate_latitude":
                            None,
                        "candidate_longitude":
                            None,
                        "candidate_display_name":
                            None,
                        "candidate_score": 0,
                        "candidate_reasons":
                            error,
                        "google_maps_url":
                            google_maps_url(
                                row.facility,
                                row.city,
                                row.state,
                                row.zip,
                            ),
                    }
                )

                time.sleep(
                    REQUEST_DELAY_SECONDS
                )

                continue

            time.sleep(
                REQUEST_DELAY_SECONDS
            )

        # ----------------------------------------------------
        # No result
        # ----------------------------------------------------

        if not parsed:

            results.append(
                {
                    "query_key": key,
                    "facility": row.facility,
                    "city": row.city,
                    "state": row.state,
                    "zip": row.zip,
                    "second_pass_status":
                        "NO_RESULT",
                    "candidate_latitude":
                        None,
                    "candidate_longitude":
                        None,
                    "candidate_display_name":
                        None,
                    "candidate_score": 0,
                    "candidate_reasons":
                        "NO_GEOCODER_RESULT",
                    "google_maps_url":
                        google_maps_url(
                            row.facility,
                            row.city,
                            row.state,
                            row.zip,
                        ),
                }
            )

        else:

            # Score all returned candidates.
            scored = []

            for result in parsed:

                score, reasons = score_result(
                    row.facility,
                    row.city,
                    row.state,
                    row.zip,
                    result,
                )

                scored.append(
                    (
                        score,
                        reasons,
                        result,
                    )
                )

            scored.sort(
                key=lambda x: x[0],
                reverse=True,
            )

            best_score, best_reasons, best = (
                scored[0]
            )

            results.append(
                {
                    "query_key": key,
                    "facility": row.facility,
                    "city": row.city,
                    "state": row.state,
                    "zip": row.zip,
                    "second_pass_status":
                        classify_result(
                            best_score,
                            best_reasons,
                        ),
                    "candidate_latitude":
                        best.get("lat"),
                    "candidate_longitude":
                        best.get("lon"),
                    "candidate_display_name":
                        best.get(
                            "display_name"
                        ),
                    "candidate_score":
                        best_score,
                    "candidate_reasons":
                        ";".join(
                            best_reasons
                        ),
                    "google_maps_url":
                        google_maps_url(
                            row.facility,
                            row.city,
                            row.state,
                            row.zip,
                        ),
                }
            )

        if i % 100 == 0:

            print(
                f"Processed "
                f"{i:,}/{total:,}"
            )

            if new_cache_rows:

                cache = pd.concat(
                    [
                        cache,
                        pd.DataFrame(
                            new_cache_rows
                        ),
                    ],
                    ignore_index=True,
                )

                save_cache(cache)

                new_cache_rows = []

    # --------------------------------------------------------
    # Save remaining cache
    # --------------------------------------------------------

    if new_cache_rows:

        cache = pd.concat(
            [
                cache,
                pd.DataFrame(
                    new_cache_rows
                ),
            ],
            ignore_index=True,
        )

        save_cache(cache)

    # --------------------------------------------------------
    # Expand results back to all queue records
    # --------------------------------------------------------

    result_df = pd.DataFrame(
        results
    )

    result_df.to_csv(
        OUTPUT_FILE,
        index=False
    )

    print("\n" + "=" * 70)
    print("SECOND PASS COMPLETE")
    print("=" * 70)

    print(
        f"Unique queries processed: "
        f"{len(result_df):,}"
    )

    print("\nStatus:")

    print(
        result_df[
            "second_pass_status"
        ]
        .value_counts()
        .to_string()
    )

    print("\nOutput:")
    print(OUTPUT_FILE)

    print("\nCache:")
    print(CACHE_FILE)


if __name__ == "__main__":
    main()