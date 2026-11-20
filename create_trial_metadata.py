from pathlib import Path
import pandas as pd
import requests
from io import StringIO

BASE_DIR = Path(__file__).resolve().parent

TRIAL_FILE = BASE_DIR / "cite_trial_sites_final.csv"
OUTPUT_FILE = BASE_DIR / "trial_metadata.csv"

URL = "https://clinicaltrials.gov/api/v2/studies"

FIELDS = [
    "NCTId",
    "BriefTitle",
    "OfficialTitle",
    "Condition",
    "OverallStatus",
    "EligibilityCriteria",
    "Sex",
    "MinimumAge",
    "MaximumAge",
    "StdAge",
    "StudyType",
    "EnrollmentCount",
]

trial_sites = pd.read_csv(
    TRIAL_FILE,
    dtype={"nct_id": str},
)

nct_ids = (
    trial_sites["nct_id"]
    .dropna()
    .astype(str)
    .str.strip()
    .str.upper()
    .drop_duplicates()
    .tolist()
)

print(f"Found {len(nct_ids):,} unique NCT IDs.")

records = []

print("\nDownloading trial metadata...")
print("Using one API request per NCT ID, concurrently.")
print("This should be much faster than the previous approach.\n")


from concurrent.futures import ThreadPoolExecutor, as_completed


def get_trial(nct_id):

    try:
        response = requests.get(
            f"{URL}/{nct_id}",
            timeout=20,
        )

        if response.status_code != 200:
            return None

        study = response.json()

        p = study.get(
            "protocolSection",
            {},
        )

        identification = p.get(
            "identificationModule",
            {},
        )

        status = p.get(
            "statusModule",
            {},
        )

        conditions = p.get(
            "conditionsModule",
            {},
        )

        eligibility = p.get(
            "eligibilityModule",
            {},
        )

        design = p.get(
            "designModule",
            {},
        )

        enrollment = design.get(
            "enrollmentInfo",
            {},
        )

        return {
            "nct_id": identification.get(
                "nctId",
                nct_id,
            ),
            "brief_title": identification.get(
                "briefTitle",
                "",
            ),
            "official_title": identification.get(
                "officialTitle",
                "",
            ),
            "condition": "; ".join(
                conditions.get(
                    "conditions",
                    [],
                )
            ),
            "recruitment_status": status.get(
                "overallStatus",
                "",
            ),
            "eligibility": eligibility.get(
                "eligibilityCriteria",
                "",
            ),
            "sex": eligibility.get(
                "sex",
                "",
            ),
            "minimum_age": eligibility.get(
                "minimumAge",
                "",
            ),
            "maximum_age": eligibility.get(
                "maximumAge",
                "",
            ),
            "standard_age": "; ".join(
                eligibility.get(
                    "stdAges",
                    [],
                )
            ),
            "study_type": design.get(
                "studyType",
                "",
            ),
            "enrollment_count": enrollment.get(
                "count",
                "",
            ),
        }

    except Exception:
        return None

with ThreadPoolExecutor(
    max_workers=20
) as executor:

    futures = {
        executor.submit(
            get_trial,
            nct_id,
        ): nct_id
        for nct_id in nct_ids
    }

    completed = 0

    for future in as_completed(
        futures
    ):

        result = future.result()

        if result:
            records.append(result)

        completed += 1

        if completed % 100 == 0:
            print(
                f"\rCompleted "
                f"{completed:,} / "
                f"{len(nct_ids):,}",
                end="",
                flush=True,
            )

metadata = pd.DataFrame(records)

metadata = metadata.drop_duplicates(
    subset=["nct_id"]
)

metadata = metadata.sort_values(
    "nct_id"
)

metadata.to_csv(
    OUTPUT_FILE,
    index=False,
)

print("\n")
print("=" * 70)
print("DONE!")
print("=" * 70)
print(
    f"Saved {len(metadata):,} trial records."
)
print(
    f"File: {OUTPUT_FILE}"
)
