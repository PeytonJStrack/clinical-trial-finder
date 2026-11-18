from pathlib import Path
import re
import json
import pandas as pd


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = BASE_DIR / "cite_trial_metadata.csv"

OUTPUT_CSV = BASE_DIR / "cite_trial_medical_profiles.csv"
OUTPUT_JSON = BASE_DIR / "cite_trial_medical_profiles.json"


# ============================================================
# TEXT UTILITIES
# ============================================================

def clean_text(value):
    """
    Convert a raw value into clean text.
    """
    if pd.isna(value):
        return ""

    text = str(value)

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Normalize repeated whitespace while preserving paragraphs.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def normalize_text(value):
    """
    Normalize text for matching.
    """
    text = clean_text(value).lower()

    text = text.replace("–", "-")
    text = text.replace("—", "-")
    text = text.replace("’", "'")

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def split_conditions(value):
    """
    Split the ClinicalTrials.gov conditions field.

    ClinicalTrials.gov-derived datasets commonly use
    semicolon- or pipe-separated conditions.
    """
    text = clean_text(value)

    if not text:
        return []

    parts = re.split(r"[;|]", text)

    conditions = []

    for part in parts:
        part = part.strip()

        if part:
            conditions.append(part)

    return conditions


def unique_preserve_order(values):
    """
    Remove duplicates while preserving original order.
    """
    seen = set()
    output = []

    for value in values:
        key = str(value).strip().lower()

        if not key:
            continue

        if key not in seen:
            seen.add(key)
            output.append(value)

    return output


# ============================================================
# CONDITION EXTRACTION
# ============================================================

def normalize_condition_name(condition):
    """
    Basic normalization only.

    IMPORTANT:
    This does NOT decide whether two diseases are equivalent.
    That belongs to the ontology layer.
    """
    text = normalize_text(condition)

    replacements = {
        "metastic": "metastatic",
        "non small cell lung cancer": "non-small cell lung cancer",
        "non-small-cell lung cancer": "non-small cell lung cancer",
        "nsclc": "non-small cell lung cancer",
        "dct": "differentiated thyroid carcinoma",
    }

    return replacements.get(text, text)


def build_condition_profile(conditions):
    """
    Build a condition-level profile.

    We deliberately preserve:
      - raw condition
      - normalized condition

    We do NOT yet assign disease hierarchy.
    """
    raw_conditions = unique_preserve_order(conditions)

    normalized_conditions = []

    for condition in raw_conditions:
        normalized = normalize_condition_name(condition)

        if normalized:
            normalized_conditions.append(normalized)

    normalized_conditions = unique_preserve_order(
        normalized_conditions
    )

    return {
        "raw_conditions": raw_conditions,
        "normalized_conditions": normalized_conditions,
        "condition_count": len(normalized_conditions),
    }


# ============================================================
# MEDICAL SIGNAL EXTRACTION
# ============================================================

MEDICAL_SIGNAL_PATTERNS = {
    "cancer": [
        r"\bcancer\b",
        r"\bcarcinoma\b",
        r"\bmalignancy\b",
        r"\bmalignant\b",
        r"\bneoplasm\b",
        r"\btumou?r\b",
    ],

    "metastatic": [
        r"\bmetastatic\b",
        r"\bmetastases\b",
        r"\bdistant metast",
    ],

    "recurrent": [
        r"\brecurrent\b",
        r"\brecurrence\b",
        r"\brelapsed\b",
        r"\brelapse\b",
    ],

    "advanced": [
        r"\badvanced\b",
        r"\blocally advanced\b",
    ],

    "refractory": [
        r"\brefractory\b",
        r"\bresistant\b",
        r"\bresistance\b",
    ],

    "newly_diagnosed": [
        r"\bnewly diagnosed\b",
        r"\bnew diagnosis\b",
        r"\bnewly-diagnosed\b",
    ],

    "biomarker": [
        r"\bbiomarker\b",
        r"\bmutation\b",
        r"\bmutations\b",
        r"\bvariant\b",
        r"\bvariants\b",
        r"\bgenomic\b",
        r"\bmolecular\b",
    ],

    "prior_treatment": [
        r"\bprior treatment\b",
        r"\bprevious treatment\b",
        r"\bprior therapy\b",
        r"\bprevious therapy\b",
        r"\bpreviously treated\b",
        r"\bprior surgery\b",
        r"\bprior chemotherapy\b",
        r"\bprior radiotherapy\b",
        r"\bprior radiation\b",
    ],

    "surgery": [
        r"\bsurgery\b",
        r"\bsurgical\b",
        r"\bsurgical resection\b",
        r"\bresection\b",
        r"\boperation\b",
    ],

    "radiation": [
        r"\bradiation\b",
        r"\bradiotherapy\b",
        r"\bradiation therapy\b",
        r"\bradioiodine\b",
        r"\brai\b",
    ],

    "chemotherapy": [
        r"\bchemotherapy\b",
        r"\bchemotherapeutic\b",
    ],

    "immunotherapy": [
        r"\bimmunotherapy\b",
        r"\bimmune checkpoint\b",
        r"\bcheckpoint inhibitor\b",
    ],

    "targeted_therapy": [
        r"\btargeted therapy\b",
        r"\btargeted treatment\b",
    ],

    "organ_function": [
        r"\borgan function\b",
        r"\brenal function\b",
        r"\bhepatic function\b",
        r"\bliver function\b",
        r"\bkidney function\b",
        r"\bbone marrow\b",
        r"\bhematologic function\b",
    ],

    "performance_status": [
        r"\bkarnofsky\b",
        r"\becog\b",
        r"\bperformance status\b",
    ],

    "pregnancy": [
        r"\bpregnan",
        r"\bbreastfeeding\b",
        r"\blactating\b",
        r"\blactation\b",
    ],

    "family_history": [
        r"\bfamily history\b",
        r"\bfamilial\b",
        r"\bfirst-degree relative\b",
        r"\bfirst degree relative\b",
        r"\bgenetic susceptibility\b",
        r"\bhereditary\b",
        r"\binherited\b",
    ],

    "healthy_controls": [
        r"\bhealthy control\b",
        r"\bhealthy controls\b",
        r"\bhealthy volunteer\b",
        r"\bhealthy volunteers\b",
        r"\bnormal control\b",
        r"\bnormal controls\b",
    ],
}


def extract_medical_signals(text):
    """
    Detect broad medical concepts in title, summary,
    conditions, and eligibility text.

    This is evidence extraction, NOT eligibility determination.
    """
    normalized = normalize_text(text)

    signals = []

    for signal, patterns in MEDICAL_SIGNAL_PATTERNS.items():

        for pattern in patterns:

            if re.search(pattern, normalized):

                signals.append(signal)

                break

    return sorted(signals)


# ============================================================
# AGE EXTRACTION
# ============================================================

def parse_age_value(value):
    """
    Convert age values into numeric years where possible.

    Supports values such as:
      18
      18 Years
      6 Months
      65 Years
    """
    if pd.isna(value):
        return None

    text = normalize_text(value)

    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(year|years|month|months|week|weeks|day|days)",
        text,
    )

    if not match:
        return None

    number = float(match.group(1))
    unit = match.group(2)

    if unit.startswith("year"):
        return number

    if unit.startswith("month"):
        return number / 12

    if unit.startswith("week"):
        return number / 52.1429

    if unit.startswith("day"):
        return number / 365.25

    return None


# ============================================================
# SEX EXTRACTION
# ============================================================

def normalize_sex(value):
    """
    Normalize structured sex information.
    """
    text = normalize_text(value)

    if not text:
        return None

    if text in {"all", "both", "any"}:
        return "ALL"

    if text in {"male", "males"}:
        return "MALE"

    if text in {"female", "females"}:
        return "FEMALE"

    return text.upper()


# ============================================================
# STUDY POPULATION PROFILE
# ============================================================

def build_population_profile(row):

    eligibility = clean_text(
        row.get("eligibility_criteria", "")
    )

    title = clean_text(
        row.get("brief_title", "")
    )

    summary = clean_text(
        row.get("brief_summary", "")
    )

    conditions = clean_text(
        row.get("conditions", "")
    )

    combined_text = "\n".join(
        [
            title,
            summary,
            conditions,
            eligibility,
        ]
    )

    signals = extract_medical_signals(
        combined_text
    )

    minimum_age = parse_age_value(
        row.get("minimum_age_years")
    )

    maximum_age = parse_age_value(
        row.get("maximum_age_years")
    )

    sex = normalize_sex(
        row.get("sex")
    )

    return {
        "minimum_age_years": minimum_age,
        "maximum_age_years": maximum_age,
        "sex": sex,
        "medical_signals": signals,
    }


# ============================================================
# TRIAL PROFILE
# ============================================================

def build_trial_profile(row):

    conditions = split_conditions(
        row.get("conditions", "")
    )

    condition_profile = build_condition_profile(
        conditions
    )

    title = clean_text(
        row.get("brief_title", "")
    )

    official_title = clean_text(
        row.get("official_title", "")
    )

    summary = clean_text(
        row.get("brief_summary", "")
    )

    eligibility = clean_text(
        row.get("eligibility_criteria", "")
    )

    intervention_text = clean_text(
        row.get("interventions", "")
    )

    combined_text = "\n".join(
        [
            title,
            official_title,
            summary,
            condition_profile["raw_conditions"][0]
            if condition_profile["raw_conditions"]
            else "",
            eligibility,
            intervention_text,
        ]
    )

    signals = extract_medical_signals(
        combined_text
    )

    population = build_population_profile(
        row
    )

    return {
        "nct_id": clean_text(
            row.get("nct_id", "")
        ),

        "brief_title": title,

        "official_title": official_title,

        "brief_summary": summary,

        "overall_status": clean_text(
            row.get("overall_status", "")
        ),

        "study_type": clean_text(
            row.get("study_type", "")
        ),

        "conditions_raw": condition_profile[
            "raw_conditions"
        ],

        "conditions_normalized": condition_profile[
            "normalized_conditions"
        ],

        "condition_count": condition_profile[
            "condition_count"
        ],

        "interventions_raw": intervention_text,

        "eligibility_criteria_raw": eligibility,

        "medical_signals": signals,

        "minimum_age_years": population[
            "minimum_age_years"
        ],

        "maximum_age_years": population[
            "maximum_age_years"
        ],

        "sex": population[
            "sex"
        ],

        "source": "ClinicalTrials.gov-derived CITE metadata",
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 80)
    print("CITE TRIAL MEDICAL PROFILE BUILDER")
    print("=" * 80)

    if not INPUT_FILE.exists():

        raise FileNotFoundError(
            f"Input file not found:\n{INPUT_FILE}"
        )

    print(f"\nReading:\n{INPUT_FILE}")

    metadata = pd.read_csv(
        INPUT_FILE,
        low_memory=False,
    )

    print(
        f"Loaded {len(metadata):,} trial records."
    )

    required_columns = [
        "nct_id",
        "brief_title",
        "conditions",
        "eligibility_criteria",
    ]

    missing = [
        column
        for column in required_columns
        if column not in metadata.columns
    ]

    if missing:

        raise ValueError(
            "Missing required columns:\n"
            + "\n".join(
                f"  - {column}"
                for column in missing
            )
        )

    profiles = []

    for index, row in metadata.iterrows():

        profile = build_trial_profile(row)

        profiles.append(profile)

        if (index + 1) % 1000 == 0:

            print(
                f"Processed "
                f"{index + 1:,}/"
                f"{len(metadata):,}"
            )

    profiles_df = pd.DataFrame(
        profiles
    )

    # Store list-like columns as JSON strings in CSV.
    list_columns = [
        "conditions_raw",
        "conditions_normalized",
        "medical_signals",
    ]

    for column in list_columns:

        profiles_df[column] = profiles_df[
            column
        ].apply(
            json.dumps
        )

    profiles_df.to_csv(
        OUTPUT_CSV,
        index=False,
    )

    with open(
        OUTPUT_JSON,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            profiles,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print("\n" + "=" * 80)
    print("COMPLETE")
    print("=" * 80)

    print(
        f"\nCSV:\n{OUTPUT_CSV}"
    )

    print(
        f"\nJSON:\n{OUTPUT_JSON}"
    )

    print(
        f"\nTrials processed: "
        f"{len(profiles_df):,}"
    )

    print(
        "\nThe medical profile is an evidence layer."
    )

    print(
        "It does NOT determine patient eligibility."
    )


if __name__ == "__main__":
    main()