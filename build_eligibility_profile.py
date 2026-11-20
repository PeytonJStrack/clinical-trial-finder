from pathlib import Path
import re
import json
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = (
    BASE_DIR /
    "cite_trial_metadata.csv"
)

OUTPUT_FILE = (
    BASE_DIR /
    "cite_trial_eligibility_profiles.csv"
)

def clean_text(value):

    if pd.isna(value):
        return ""

    text = str(value)

    text = text.replace(
        "\r\n",
        "\n",
    )

    text = text.replace(
        "\r",
        "\n",
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text,
    )

    return text.strip()


def normalize_text(value):

    return re.sub(
        r"\s+",
        " ",
        clean_text(value).lower(),
    ).strip()

def split_eligibility_sections(text):

    text = clean_text(text)

    if not text:

        return {
            "inclusion_text": "",
            "exclusion_text": "",
            "other_text": "",
        }

    normalized = text.lower()

    inclusion_patterns = [
        r"\binclusion criteria\b",
        r"\binclusion\b",
        r"\bkey inclusion criteria\b",
    ]

    exclusion_patterns = [
        r"\bexclusion criteria\b",
        r"\bexclusion\b",
        r"\bkey exclusion criteria\b",
    ]

    inclusion_match = None
    exclusion_match = None

    for pattern in inclusion_patterns:

        match = re.search(
            pattern,
            normalized,
        )

        if match:

            inclusion_match = match

            break

    for pattern in exclusion_patterns:

        match = re.search(
            pattern,
            normalized,
        )

        if match:

            exclusion_match = match

            break

    inclusion_text = ""
    exclusion_text = ""
    other_text = ""

    if inclusion_match:

        start = inclusion_match.end()

        if exclusion_match and exclusion_match.start() > start:

            inclusion_text = text[
                start:exclusion_match.start()
            ]

        else:

            inclusion_text = text[start:]

    if exclusion_match:

        start = exclusion_match.end()

        exclusion_text = text[start:]

    if not inclusion_match and not exclusion_match:

        other_text = text

    return {
        "inclusion_text":
            inclusion_text.strip(),

        "exclusion_text":
            exclusion_text.strip(),

        "other_text":
            other_text.strip(),
    }

def extract_age_constraints(text):

    normalized = normalize_text(text)

    constraints = []

    patterns = [

        (
            r"(?:age|aged)\s*(?:greater than or equal to|at least|>=|≥)\s*"
            r"(\d+(?:\.\d+)?)\s*(years?|months?)",
            "minimum",
        ),

        (
            r"(?:age|aged)\s*(?:less than or equal to|at most|<=|≤)\s*"
            r"(\d+(?:\.\d+)?)\s*(years?|months?)",
            "maximum",
        ),

        (
            r"(\d+(?:\.\d+)?)\s*(?:and|-)\s*"
            r"(\d+(?:\.\d+)?)\s*years",
            "range",
        ),

        (
            r"(\d+(?:\.\d+)?)\s*to\s*"
            r"(\d+(?:\.\d+)?)\s*years",
            "range",
        ),

    ]

    for pattern, constraint_type in patterns:

        for match in re.finditer(
            pattern,
            normalized,
        ):

            if constraint_type == "range":

                minimum = float(
                    match.group(1)
                )

                maximum = float(
                    match.group(2)
                )

                constraints.append(
                    {
                        "type": "range",
                        "minimum_years": minimum,
                        "maximum_years": maximum,
                        "source_text": match.group(0),
                    }
                )

            else:

                value = float(
                    match.group(1)
                )

                unit = match.group(2)

                if unit.startswith("month"):

                    value /= 12

                constraints.append(
                    {
                        "type": constraint_type,
                        "value_years": value,
                        "source_text": match.group(0),
                    }
                )

    return constraints

def extract_sex_constraints(text):

    normalized = normalize_text(text)

    constraints = []

    patterns = {

        "female": [
            r"\bfemales?\b",
            r"\bwomen\b",
            r"\bgirls?\b",
        ],

        "male": [
            r"\bmales?\b",
            r"\bmen\b",
            r"\bboys?\b",
        ],

    }

    for sex, sex_patterns in patterns.items():

        for pattern in sex_patterns:

            if re.search(
                pattern,
                normalized,
            ):

                constraints.append(
                    {
                        "sex": sex.upper(),
                        "source_text":
                            pattern,
                    }
                )

                break

    return constraints

MEDICAL_REQUIREMENT_PATTERNS = {

    "diagnosis": [
        r"\bdiagnos(?:is|ed|e)\b",
        r"\bconfirmed diagnosis\b",
        r"\bhistologically confirmed\b",
        r"\bpathologically confirmed\b",
    ],

    "metastatic_disease": [
        r"\bmetastatic\b",
        r"\bdistant metastases\b",
        r"\bmetastases\b",
    ],

    "recurrent_disease": [
        r"\brecurrent\b",
        r"\brecurrence\b",
        r"\brelapsed\b",
    ],

    "prior_treatment": [
        r"\bprior treatment\b",
        r"\bprevious treatment\b",
        r"\bprior therapy\b",
        r"\bprevious therapy\b",
        r"\bpreviously treated\b",
    ],

    "surgery": [
        r"\bprior surgery\b",
        r"\bunderwent surgery\b",
        r"\bunderwent.*surgery\b",
        r"\bpost[- ]surgical\b",
        r"\bpostoperative\b",
    ],

    "chemotherapy": [
        r"\bprior chemotherapy\b",
        r"\bprevious chemotherapy\b",
        r"\bchemotherapy\b",
    ],

    "radiation": [
        r"\bradiation therapy\b",
        r"\bradiotherapy\b",
        r"\bprior radiation\b",
        r"\bradioiodine\b",
        r"\bRAI\b",
    ],

    "biomarker": [
        r"\bmutation\b",
        r"\bmutations\b",
        r"\bbiomarker\b",
        r"\bvariant\b",
        r"\bgenetic alteration\b",
        r"\bgenomic alteration\b",
    ],

    "organ_function": [
        r"\badequate organ function\b",
        r"\brenal function\b",
        r"\bhepatic function\b",
        r"\bliver function\b",
        r"\bkidney function\b",
        r"\bbone marrow\b",
        r"\bhematologic function\b",
    ],

    "performance_status": [
        r"\bperformance status\b",
        r"\bkarnofsky\b",
        r"\bECOG\b",
    ],

    "pregnancy": [
        r"\bpregnan",
        r"\bbreastfeed",
        r"\blactat",
    ],

    "consent": [
        r"\binformed consent\b",
        r"\bconsent\b",
    ],

    "family_history": [
        r"\bfamily history\b",
        r"\bfamilial\b",
        r"\bfirst-degree relative\b",
        r"\bfirst degree relative\b",
    ],

}


def extract_medical_requirements(text):

    normalized = normalize_text(text)

    detected = []

    for requirement, patterns in (
        MEDICAL_REQUIREMENT_PATTERNS.items()
    ):

        for pattern in patterns:

            if re.search(
                pattern,
                normalized,
            ):

                detected.append(
                    requirement
                )

                break

    return detected

def extract_biomarkers(text):

    normalized = normalize_text(text)

    biomarkers = []

    patterns = [

        r"\bBRAF(?:\s+[A-Z0-9\-]+)?\b",

        r"\bKRAS(?:\s+[A-Z0-9\-]+)?\b",

        r"\bNRAS(?:\s+[A-Z0-9\-]+)?\b",

        r"\bHRAS(?:\s+[A-Z0-9\-]+)?\b",

        r"\bCRAF\b",

        r"\bRAF1\b",

        r"\bMEK1\b",

        r"\bMEK2\b",

        r"\bEGFR\b",

        r"\bALK\b",

        r"\bHER2\b",

        r"\bPD-L1\b",

    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        )

        biomarkers.extend(
            matches
        )

    # Normalize and deduplicate.
    output = []

    seen = set()

    for biomarker in biomarkers:

        cleaned = biomarker.upper().strip()

        if cleaned not in seen:

            seen.add(cleaned)

            output.append(
                cleaned
            )

    return output

def extract_requirement_sentences(text):

    text = clean_text(text)

    if not text:

        return []

    # Split on common bullet/number boundaries.
    parts = re.split(
        r"(?:\n+|(?<=\.)\s+(?=\d+\.)|(?<=\.)\s+(?=\*))",
        text,
    )

    output = []

    for part in parts:

        cleaned = re.sub(
            r"^\s*[\*\-\u2022\d\.\)]+\s*",
            "",
            part,
        ).strip()

        if cleaned:

            output.append(
                cleaned
            )

    return output

def build_profile(row):

    eligibility = clean_text(
        row.get(
            "eligibility_criteria",
            "",
        )
    )

    sections = split_eligibility_sections(
        eligibility
    )

    inclusion = sections[
        "inclusion_text"
    ]

    exclusion = sections[
        "exclusion_text"
    ]

    medical_requirements = (
        extract_medical_requirements(
            inclusion
        )
    )

    exclusion_requirements = (
        extract_medical_requirements(
            exclusion
        )
    )

    biomarkers = extract_biomarkers(
        inclusion
    )

    exclusion_biomarkers = (
        extract_biomarkers(
            exclusion
        )
    )

    return {

        "nct_id": clean_text(
            row.get(
                "nct_id",
                "",
            )
        ),

        "brief_title": clean_text(
            row.get(
                "brief_title",
                "",
            )
        ),

        "minimum_age_structured":
            row.get(
                "minimum_age_years",
                None,
            ),

        "maximum_age_structured":
            row.get(
                "maximum_age_years",
                None,
            ),

        "sex_structured":
            clean_text(
                row.get(
                    "sex",
                    "",
                )
            ),

        "eligibility_raw":
            eligibility,

        "inclusion_text":
            inclusion,

        "exclusion_text":
            exclusion,

        "other_eligibility_text":
            sections[
                "other_text"
            ],

        "inclusion_age_constraints":
            extract_age_constraints(
                inclusion
            ),

        "exclusion_age_constraints":
            extract_age_constraints(
                exclusion
            ),

        "inclusion_sex_constraints":
            extract_sex_constraints(
                inclusion
            ),

        "exclusion_sex_constraints":
            extract_sex_constraints(
                exclusion
            ),

        "inclusion_medical_requirements":
            medical_requirements,

        "exclusion_medical_requirements":
            exclusion_requirements,

        "inclusion_biomarkers":
            biomarkers,

        "exclusion_biomarkers":
            exclusion_biomarkers,

        "inclusion_requirement_sentences":
            extract_requirement_sentences(
                inclusion
            ),

        "exclusion_requirement_sentences":
            extract_requirement_sentences(
                exclusion
            ),

    }

def main():

    print("=" * 80)
    print("CITE ELIGIBILITY PROFILE BUILDER")
    print("=" * 80)

    if not INPUT_FILE.exists():

        raise FileNotFoundError(
            f"Input file not found:\n"
            f"{INPUT_FILE}"
        )

    metadata = pd.read_csv(
        INPUT_FILE,
        low_memory=False,
    )

    print(
        f"\nLoaded "
        f"{len(metadata):,} trials."
    )

    required = [
        "nct_id",
        "brief_title",
        "eligibility_criteria",
    ]

    missing = [
        column
        for column in required
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

        profiles.append(
            build_profile(
                row
            )
        )

        if (index + 1) % 1000 == 0:

            print(
                f"Processed "
                f"{index + 1:,}/"
                f"{len(metadata):,}"
            )

    output = pd.DataFrame(
        profiles
    )

    # Serialize list/dict fields for CSV.
    for column in output.columns:

        if output[column].apply(
            lambda x:
                isinstance(
                    x,
                    (list, dict),
                )
        ).any():

            output[column] = output[
                column
            ].apply(
                lambda x:
                    json.dumps(
                        x,
                        ensure_ascii=False,
                    )
            )

    output.to_csv(
        OUTPUT_FILE,
        index=False,
    )

    print("\n" + "=" * 80)
    print("COMPLETE")
    print("=" * 80)

    print(
        f"\nSaved:\n{OUTPUT_FILE}"
    )

    print(
        f"\nTrials processed: "
        f"{len(output):,}"
    )

    print(
        "\nThis script extracts evidence."
    )

    print(
        "It does NOT determine eligibility."
    )


if __name__ == "__main__":
    main()
