from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_URL = "https://clinicaltrials.gov/api/v2/studies"
DEFAULT_BATCH_SIZE = 100
DEFAULT_OUTPUT = "cite_trial_metadata.csv"


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "CITE-Clinical-Trial-Access-Explorer/1.0 "
                      "(research data enrichment)"
    })
    return session


def get_nested(data: dict[str, Any], *path: str, default=None):
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def age_to_years(value: Any) -> float | None:
    if not value or not isinstance(value, str):
        return None
    pieces = value.strip().split()
    if not pieces:
        return None
    try:
        number = float(pieces[0])
    except (TypeError, ValueError):
        return None
    unit = pieces[1].lower() if len(pieces) > 1 else "years"
    if unit.startswith("day"):
        return number / 365.25
    if unit.startswith("week"):
        return number / 52.1775
    if unit.startswith("month"):
        return number / 12
    return number


def extract_study(study: dict[str, Any]) -> dict[str, Any]:
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    conditions = protocol.get("conditionsModule", {})
    eligibility = protocol.get("eligibilityModule", {})
    arms = protocol.get("armsInterventionsModule", {})

    nct_id = identification.get("nctId")
    min_age = eligibility.get("minimumAge")
    max_age = eligibility.get("maximumAge")

    interventions = []
    for item in arms.get("interventions", []) or []:
        name = item.get("name")
        if name:
            interventions.append(name)

    return {
        "nct_id": nct_id,
        "brief_title": identification.get("briefTitle"),
        "official_title": identification.get("officialTitle"),
        "overall_status": status.get("overallStatus"),
        "study_type": design.get("studyType"),
        "phases": "; ".join(design.get("phases", []) or []),
        "conditions": "; ".join(conditions.get("conditions", []) or []),
        "minimum_age": min_age,
        "maximum_age": max_age,
        "minimum_age_years": age_to_years(min_age),
        "maximum_age_years": age_to_years(max_age),
        "sex": eligibility.get("sex"),
        "healthy_volunteers": eligibility.get("healthyVolunteers"),
        "eligibility_criteria": eligibility.get("eligibilityCriteria"),
        "brief_summary": get_nested(
            protocol, "descriptionModule", "briefSummary"
        ),
        "interventions": "; ".join(interventions),
        "study_url": (
            f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else None
        ),
    }


def fetch_batch(
    session: requests.Session,
    nct_ids: list[str],
) -> list[dict[str, Any]]:
    # ClinicalTrials.gov API v2 supports a comma-separated filter.ids list.
    params = {
        "format": "json",
        "pageSize": min(1000, len(nct_ids)),
        "filter.ids": ",".join(nct_ids),
    }
    response = session.get(API_URL, params=params, timeout=90)
    response.raise_for_status()
    payload = response.json()
    return [
        extract_study(study)
        for study in payload.get("studies", [])
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="cite_trial_sites_final.csv")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--pause",
        type=float,
        default=0.25,
        help="Pause between batches in seconds.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch all NCT IDs instead of reusing existing metadata.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"Could not find site file: {input_path}")

    sites = pd.read_csv(input_path, dtype={"nct_id": "string"})
    if "nct_id" not in sites.columns:
        raise ValueError("The input site file must contain an 'nct_id' column.")

    nct_ids = sorted({
        str(value).strip().upper()
        for value in sites["nct_id"].dropna()
        if str(value).strip()
    })
    print(f"Unique study identifiers in site file: {len(nct_ids):,}")

    existing: dict[str, dict[str, Any]] = {}
    if output_path.exists() and not args.refresh:
        old = pd.read_csv(output_path, dtype={"nct_id": "string"})
        for record in old.to_dict("records"):
            if pd.notna(record.get("nct_id")):
                existing[str(record["nct_id"]).upper()] = record
        print(f"Reusing cached study records: {len(existing):,}")

    pending = [nct for nct in nct_ids if nct not in existing]
    print(f"Study records to fetch: {len(pending):,}")

    session = make_session()
    fetched: dict[str, dict[str, Any]] = dict(existing)

    for start in range(0, len(pending), args.batch_size):
        batch = pending[start:start + args.batch_size]
        records = fetch_batch(session, batch)
        for record in records:
            if record.get("nct_id"):
                fetched[str(record["nct_id"]).upper()] = record

        completed = min(start + len(batch), len(pending))
        print(
            f"Processed {completed:,}/{len(pending):,} requested IDs; "
            f"metadata rows cached: {len(fetched):,}"
        )
        if args.pause > 0:
            time.sleep(args.pause)

    # Keep a row for every requested NCT ID, including IDs no longer returned
    # by the registry, so missing metadata is visible rather than silently lost.
    rows = []
    for nct_id in nct_ids:
        rows.append(fetched.get(nct_id, {
            "nct_id": nct_id,
            "study_url": f"https://clinicaltrials.gov/study/{nct_id}",
        }))

    metadata = pd.DataFrame(rows)
    metadata.to_csv(output_path, index=False)
    print(f"Saved {len(metadata):,} rows to {output_path.resolve()}")
    print(
        "Metadata fields include conditions, recruitment status, study type, "
        "phase, age limits, sex, healthy-volunteer status, eligibility text, "
        "summary, interventions, and ClinicalTrials.gov URL."
    )


if __name__ == "__main__":
    main()
