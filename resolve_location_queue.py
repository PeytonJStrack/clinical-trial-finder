from __future__ import annotations

import argparse
import difflib
import re
import time
from datetime import datetime, timezone, UTC
from pathlib import Path

import pandas as pd
import requests

INPUT_FILE = Path("location_resolution_queue.csv")
OUTPUT_FILE = Path("location_resolution_results.csv")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

REQUEST_INTERVAL_SECONDS = 1.10
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRIES = 4

USER_AGENT = (
    "CITE-Foundation-Clinical-Trial-Access-Explorer/1.0 "
    "(location-resolution research; contact: CITE Foundation)"
)

RESULT_COLUMNS = [
    "location_id",
    "facility",
    "city",
    "state",
    "zip",
    "resolution_priority",
    "resolution_category",
    "resolution_status",
    "resolved_address",
    "resolved_latitude",
    "resolved_longitude",
    "resolved_zip",
    "resolved_city",
    "resolved_state",
    "resolved_facility_name",
    "facility_match_score",
    "candidate_type",
    "nominatim_place_id",
    "query",
    "failure_reason",
    "resolved_at_utc",
]


STATE_ABBREVIATIONS = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID",
    "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT",
    "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI", "WYOMING": "WY", "DISTRICT OF COLUMBIA": "DC",
}


def clean_text(value) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def normalize_zip(value) -> str:
    text = clean_text(value)
    digits = re.sub(r"\D", "", text)
    return digits[:5]


def normalize_name(value) -> str:
    text = clean_text(value).upper()
    text = text.replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\b(LLC|INC|INCORPORATED|LTD|LIMITED|CORP|CORPORATION)\b", " ", text)
    text = re.sub(r"\b(SITE|LOCATION|CAMPUS|FACILITY)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def state_abbrev(value) -> str:
    text = clean_text(value).upper()
    return STATE_ABBREVIATIONS.get(text, text if len(text) == 2 else "")


def similarity(a: str, b: str) -> float:
    a = normalize_name(a)
    b = normalize_name(b)
    if not a or not b:
        return 0.0
    return round(100.0 * difflib.SequenceMatcher(None, a, b).ratio(), 1)


def has_street_number(address: dict) -> bool:
    house = clean_text(address.get("house_number", ""))
    if house and re.search(r"\d", house):
        return True
    display = clean_text(address.get("display_name", ""))
    return bool(re.search(r"(?:^|,\s*)\d{1,6}[A-Za-z]?(?:-|\s|,)", display))


def build_query(row) -> str:
    facility = clean_text(row.get("facility", ""))
    city = clean_text(row.get("city", ""))
    state = clean_text(row.get("state", ""))
    zip_code = normalize_zip(row.get("zip", ""))

    parts = [facility, city, state]
    if zip_code:
        parts.append(zip_code)
    parts.append("USA")
    return ", ".join(p for p in parts if p)


def candidate_score(row, result: dict) -> tuple[float, dict]:
    address = result.get("address", {}) or {}
    source_city = clean_text(row.get("city", ""))
    source_state = state_abbrev(row.get("state", ""))
    source_zip = normalize_zip(row.get("zip", ""))

    result_name = clean_text(
        address.get("hospital")
        or address.get("clinic")
        or address.get("healthcare")
        or address.get("amenity")
        or address.get("building")
        or result.get("name", "")
    )
    result_city = clean_text(
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or address.get("county", "")
    )
    result_state = state_abbrev(address.get("state", ""))
    result_zip = normalize_zip(address.get("postcode", ""))

    name_score = similarity(row.get("facility", ""), result_name)
    city_score = similarity(source_city, result_city)

    score = name_score
    if source_city and result_city:
        if source_city.upper() == result_city.upper():
            score += 12
        elif city_score >= 75:
            score += 5
        else:
            score -= 20

    if source_state and result_state:
        if source_state == result_state:
            score += 8
        else:
            score -= 30

    if source_zip:
        if result_zip == source_zip:
            score += 20
        elif result_zip:
            score -= 35
        else:
            score -= 10

    if source_state and result_state and source_state != result_state:
        score = min(score, 20)
    if source_zip and result_zip and source_zip != result_zip:
        score = min(score, 20)

    details = {
        "result_name": result_name,
        "result_city": result_city,
        "result_state": result_state,
        "result_zip": result_zip,
        "name_score": name_score,
        "city_score": city_score,
    }
    return round(score, 1), details


def choose_candidate(row, results: list[dict]):
    candidates = []
    source_state = state_abbrev(row.get("state", ""))
    source_zip = normalize_zip(row.get("zip", ""))

    for result in results:
        address = result.get("address", {}) or {}
        if str(address.get("country_code", "")).lower() != "us":
            continue
        if not has_street_number(address):
            continue

        score, details = candidate_score(row, result)

        if source_state and details["result_state"] != source_state:
            continue
        if source_zip and details["result_zip"] != source_zip:
            continue

        candidates.append((score, details, result))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0]


def request_nominatim(session: requests.Session, query: str):
    params = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 5,
        "countrycodes": "us",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(
                NOMINATIM_URL,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

            if response.status_code == 200:
                return response.json(), ""

            if response.status_code == 429:
                wait = min(60, 10 * attempt)
                print(f"  429 rate limit; waiting {wait}s...")
                time.sleep(wait)
                continue

            if response.status_code in {500, 502, 503, 504}:
                wait = min(30, 3 * attempt)
                print(f"  HTTP {response.status_code}; retrying in {wait}s...")
                time.sleep(wait)
                continue

            return [], f"HTTP_{response.status_code}"

        except requests.RequestException as exc:
            if attempt == MAX_RETRIES:
                return [], f"REQUEST_ERROR:{type(exc).__name__}"
            wait = min(30, 3 * attempt)
            print(f"  Request error; retrying in {wait}s...")
            time.sleep(wait)

    return [], "MAX_RETRIES_EXCEEDED"


def append_result(record: dict):
    frame = pd.DataFrame([record], columns=RESULT_COLUMNS)
    write_header = not OUTPUT_FILE.exists() or OUTPUT_FILE.stat().st_size == 0
    frame.to_csv(
        OUTPUT_FILE,
        mode="a",
        header=write_header,
        index=False,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--retry-unresolved",
        action="store_true",
        help="Retry rows previously recorded as UNRESOLVED or ERROR.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional test limit. 0 = process all eligible rows.",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("CITE OVERNIGHT LOCATION RESOLUTION")
    print("=" * 72)
    print("Source: location_resolution_queue.csv")
    print("Output: location_resolution_results.csv")
    print("No Google Maps fallback.")
    print("No original-coordinate fallback.")
    print("Public Nominatim: single-threaded, ~1 request every 1.1 seconds.")
    print("Checkpoint mode: append-only; existing results are preserved.")
    print()

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Missing {INPUT_FILE}")

    queue = pd.read_csv(INPUT_FILE, low_memory=False)
    queue["resolution_priority"] = queue["resolution_priority"].fillna("").astype(str)

    eligible = queue[
        queue["resolution_priority"].astype(str).isin(
            ["1", "2", "HIGH_PRIORITY_NAMED_FACILITY", "NAMED_FACILITY_MISSING_ZIP"]
        )
    ].copy()

    # We only send named facilities to the geocoder.
    eligible = eligible[
        eligible["facility"].fillna("").astype(str).str.strip().ne("")
    ].copy()

    if args.limit > 0:
        eligible = eligible.head(args.limit).copy()

    print(f"Queue rows: {len(queue):,}")
    print(f"Eligible named facilities: {len(eligible):,}")

    previous = {}
    if OUTPUT_FILE.exists():
        existing = pd.read_csv(OUTPUT_FILE, low_memory=False)
        for _, row in existing.iterrows():
            previous[str(row["location_id"])] = row.to_dict()
        print(f"Existing saved results: {len(previous):,}")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    processed = 0
    accepted = 0
    unresolved = 0
    skipped = 0
    last_request = 0.0

    for _, row in eligible.iterrows():
        location_id = str(row["location_id"])
        prior = previous.get(location_id)

        if prior and not (
            args.retry_unresolved
            and str(prior.get("resolution_status", "")) in {"UNRESOLVED", "ERROR"}
        ):
            skipped += 1
            continue

        query = build_query(row)
        print(
            f"[{processed + 1:,}/{len(eligible):,}] "
            f"{clean_text(row['facility'])} | "
            f"{clean_text(row['city'])}, {clean_text(row['state'])} {normalize_zip(row['zip'])}"
        )

        elapsed = time.monotonic() - last_request
        if elapsed < REQUEST_INTERVAL_SECONDS:
            time.sleep(REQUEST_INTERVAL_SECONDS - elapsed)

        last_request = time.monotonic()
        api_results, error = request_nominatim(session, query)

        now = datetime.now(UTC).isoformat()

        if error:
            record = {
                "location_id": row["location_id"],
                "facility": row["facility"],
                "city": row["city"],
                "state": row["state"],
                "zip": row["zip"],
                "resolution_priority": row["resolution_priority"],
                "resolution_category": row.get("resolution_category", ""),
                "resolution_status": "ERROR",
                "resolved_address": "",
                "resolved_latitude": "",
                "resolved_longitude": "",
                "resolved_zip": "",
                "resolved_city": "",
                "resolved_state": "",
                "resolved_facility_name": "",
                "facility_match_score": "",
                "candidate_type": "",
                "nominatim_place_id": "",
                "query": query,
                "failure_reason": error,
                "resolved_at_utc": now,
            }
            unresolved += 1
        else:
            chosen = choose_candidate(row, api_results)

            if chosen is None:
                record = {
                    "location_id": row["location_id"],
                    "facility": row["facility"],
                    "city": row["city"],
                    "state": row["state"],
                    "zip": row["zip"],
                    "resolution_priority": row["resolution_priority"],
                    "resolution_category": row.get("resolution_category", ""),
                    "resolution_status": "UNRESOLVED",
                    "resolved_address": "",
                    "resolved_latitude": "",
                    "resolved_longitude": "",
                    "resolved_zip": "",
                    "resolved_city": "",
                    "resolved_state": "",
                    "resolved_facility_name": "",
                    "facility_match_score": "",
                    "candidate_type": "",
                    "nominatim_place_id": "",
                    "query": query,
                    "failure_reason": "NO_ACCEPTABLE_US_STREET_ADDRESS_WITH_SOURCE_ZIP",
                    "resolved_at_utc": now,
                }
                unresolved += 1
                print("  -> unresolved (no acceptable ZIP/address match)")
            else:
                score, details, result = chosen
                address = result.get("address", {}) or {}
                resolved_address = clean_text(result.get("display_name", ""))

                record = {
                    "location_id": row["location_id"],
                    "facility": row["facility"],
                    "city": row["city"],
                    "state": row["state"],
                    "zip": row["zip"],
                    "resolution_priority": row["resolution_priority"],
                    "resolution_category": row.get("resolution_category", ""),
                    "resolution_status": "ACCEPTED",
                    "resolved_address": resolved_address,
                    "resolved_latitude": result.get("lat", ""),
                    "resolved_longitude": result.get("lon", ""),
                    "resolved_zip": details["result_zip"],
                    "resolved_city": details["result_city"],
                    "resolved_state": details["result_state"],
                    "resolved_facility_name": details["result_name"],
                    "facility_match_score": score,
                    "candidate_type": result.get("type", ""),
                    "nominatim_place_id": result.get("place_id", ""),
                    "query": query,
                    "failure_reason": "",
                    "resolved_at_utc": now,
                }
                accepted += 1
                print(
                    f"  -> ACCEPTED | score={score} | "
                    f"{resolved_address}"
                )

        processed += 1

        append_result(record)

        if processed % 100 == 0:
            print(
                f"\nProgress: processed={processed:,} "
                f"accepted={accepted:,} unresolved/errors={unresolved:,} "
                f"skipped={skipped:,}\n"
            )

    print("\n" + "=" * 72)
    print("LOCATION RESOLUTION COMPLETE")
    print("=" * 72)
    print(f"Eligible rows:       {len(eligible):,}")
    print(f"Processed this run:  {processed:,}")
    print(f"Skipped/resumed:     {skipped:,}")
    print(f"Accepted:            {accepted:,}")
    print(f"Unresolved/errors:   {unresolved:,}")
    print(f"Output:              {OUTPUT_FILE}")
    print("\nNext step: run the strict validator after reviewing the resolution output.")


if __name__ == "__main__":
    main()
