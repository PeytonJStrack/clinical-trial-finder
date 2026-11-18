from pathlib import Path
import math
import re

import pandas as pd


# ============================================================
# FILES
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

METADATA_FILE = BASE_DIR / "cite_trial_metadata.csv"
SITES_FILE = BASE_DIR / "cite_trial_sites.csv"


# ============================================================
# MATCH WEIGHTS
# ============================================================

WEIGHTS = {
    "medical_relevance": 0.35,
    "eligibility_compatibility": 0.25,
    "recruitment_fit": 0.15,
    "accessibility": 0.15,
    "preferences": 0.10,
}


# Only these statuses count as actively recruiting
# for the recruiting-only filter.
RECRUITING_STATUSES = {
    "RECRUITING",
    "ENROLLING_BY_INVITATION",
}


# ============================================================
# MEDICAL TERMINOLOGY
# ============================================================

# These are intentionally conservative.
#
# The purpose is NOT to build a giant medical dictionary by hand.
# The purpose of V0.3 is to establish a transparent baseline
# before we introduce a proper terminology/ontology layer.

MEDICAL_SYNONYMS = {

    "thyroid cancer": {
        "thyroid cancer",
        "thyroid carcinoma",
        "thyroid neoplasm",
        "cancer of the thyroid",
        "malignant neoplasm of thyroid",
        "malignant neoplasm of the thyroid",
    },

    "papillary thyroid cancer": {
        "papillary thyroid cancer",
        "papillary thyroid carcinoma",
        "papillary carcinoma of thyroid",
        "papillary carcinoma of the thyroid",
    },

    "follicular thyroid cancer": {
        "follicular thyroid cancer",
        "follicular thyroid carcinoma",
        "follicular carcinoma of thyroid",
        "follicular carcinoma of the thyroid",
    },

    "medullary thyroid cancer": {
        "medullary thyroid cancer",
        "medullary thyroid carcinoma",
        "medullary carcinoma of thyroid",
        "medullary carcinoma of the thyroid",
    },

    "anaplastic thyroid cancer": {
        "anaplastic thyroid cancer",
        "anaplastic thyroid carcinoma",
        "anaplastic carcinoma of thyroid",
        "anaplastic carcinoma of the thyroid",
    },

    "breast cancer": {
        "breast cancer",
        "breast carcinoma",
        "malignant neoplasm of breast",
        "malignant neoplasm of the breast",
    },

    "lung cancer": {
        "lung cancer",
        "lung carcinoma",
        "pulmonary carcinoma",
        "malignant neoplasm of lung",
        "malignant neoplasm of the lung",
    },

    "prostate cancer": {
        "prostate cancer",
        "prostate carcinoma",
        "malignant neoplasm of prostate",
        "malignant neoplasm of the prostate",
    },

    "colorectal cancer": {
        "colorectal cancer",
        "colorectal carcinoma",
        "colon cancer",
        "colon carcinoma",
        "rectal cancer",
        "rectal carcinoma",
    },
}


# Parent-child relationships.
#
# The direction matters:
#
# Patient asks for:
#     thyroid cancer
#
# Trial studies:
#     papillary thyroid carcinoma
#
# That is a strong relationship.
#
# But if patient asks for:
#     papillary thyroid cancer
#
# and trial only says:
#     thyroid cancer
#
# we should be somewhat less certain because the trial's
# condition is broader than the patient's specific condition.

CONDITION_HIERARCHY = {

    "thyroid cancer": {
        "papillary thyroid cancer",
        "follicular thyroid cancer",
        "medullary thyroid cancer",
        "anaplastic thyroid cancer",
    },

    "breast cancer": set(),

    "lung cancer": set(),

    "prostate cancer": set(),

    "colorectal cancer": set(),
}


# Broad disease categories that are intentionally weak.
#
# "Cancer" should NEVER be treated as a strong match to
# "thyroid cancer."

BROAD_TERMS = {
    "cancer",
    "carcinoma",
    "malignancy",
    "malignant neoplasm",
    "neoplasm",
    "tumor",
    "tumors",
    "oncology",
}


# Terms that are too generic to contribute meaningful
# condition similarity by themselves.
GENERIC_TERMS = {
    "study",
    "trial",
    "patients",
    "patient",
    "subjects",
    "subject",
    "participants",
    "participant",
    "disease",
    "disorder",
    "condition",
    "research",
    "clinical",
}


# ============================================================
# DATA LOADING
# ============================================================

def load_data():

    metadata = pd.read_csv(
        METADATA_FILE,
        low_memory=False,
    )

    sites = pd.read_csv(
        SITES_FILE,
        low_memory=False,
    )

    metadata.columns = [
        str(c).strip().lower()
        for c in metadata.columns
    ]

    sites.columns = [
        str(c).strip().lower()
        for c in sites.columns
    ]

    if "nct_id" not in metadata.columns:
        raise ValueError(
            "Metadata file is missing 'nct_id'."
        )

    if "nct_id" not in sites.columns:
        raise ValueError(
            "Sites file is missing 'nct_id'."
        )

    metadata["nct_id"] = (
        metadata["nct_id"]
        .astype(str)
        .str.strip()
    )

    sites["nct_id"] = (
        sites["nct_id"]
        .astype(str)
        .str.strip()
    )

    text_columns = [
        "brief_title",
        "official_title",
        "conditions",
        "eligibility_criteria",
        "brief_summary",
        "interventions",
        "overall_status",
        "study_type",
        "sex",
    ]

    for column in text_columns:

        if column in metadata.columns:

            metadata[column] = (
                metadata[column]
                .fillna("")
                .astype(str)
                .str.strip()
            )

    return metadata, sites


# ============================================================
# GENERAL HELPERS
# ============================================================

def is_missing(value):

    if value is None:
        return True

    if isinstance(value, float) and math.isnan(value):
        return True

    text = str(value).strip().upper()

    return text in {
        "",
        "NAN",
        "NONE",
        "NULL",
        "N/A",
        "NA",
        "UNKNOWN",
        "NOT REPORTED",
        "NOT AVAILABLE",
    }


def normalize_text(value):

    if is_missing(value):
        return ""

    text = str(value).lower()

    text = text.replace(
        "&",
        " and ",
    )

    text = re.sub(
        r"[-_/]",
        " ",
        text,
    )

    text = re.sub(
        r"[^\w\s]",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def normalize_status(value):

    if is_missing(value):
        return None

    value = str(value).upper()

    value = re.sub(
        r"[^A-Z]+",
        "_",
        value,
    )

    return value.strip("_")


def safe_float(value):

    if is_missing(value):
        return None

    try:
        return float(value)

    except (
        ValueError,
        TypeError,
    ):
        return None


# ============================================================
# TOKENIZATION
# ============================================================

def tokenize(text):

    text = normalize_text(text)

    if not text:
        return set()

    tokens = re.findall(
        r"[a-z0-9]+",
        text,
    )

    return {
        token
        for token in tokens
        if token not in GENERIC_TERMS
    }


# ============================================================
# CONDITION NORMALIZATION
# ============================================================

def canonical_condition(condition):

    """
    Convert a condition phrase into the closest known
    CITE canonical concept.

    Returns:
        canonical condition or None
    """

    normalized = normalize_text(condition)

    if not normalized:
        return None

    # Exact synonym lookup.
    for canonical, synonyms in MEDICAL_SYNONYMS.items():

        normalized_synonyms = {
            normalize_text(term)
            for term in synonyms
        }

        if normalized in normalized_synonyms:
            return canonical

    # If the phrase already equals a canonical name.
    if normalized in MEDICAL_SYNONYMS:
        return normalized

    return None


def extract_trial_conditions(condition_text):

    """
    Split a registry condition field into individual conditions.

    ClinicalTrials.gov records may contain multiple conditions
    in one field.
    """

    if is_missing(condition_text):
        return []

    text = str(condition_text)

    # Common delimiters in exported registry data.
    parts = re.split(
        r"[;|]",
        text,
    )

    conditions = []

    for part in parts:

        part = part.strip()

        if part:
            conditions.append(part)

    # If no delimiter existed, use the entire field.
    if not conditions:
        conditions = [text]

    return conditions


# ============================================================
# MEDICAL RELEVANCE V0.3
# ============================================================

def condition_similarity(
    patient_condition,
    trial_condition,
):
    """
    Calculate graded medical relevance.

    Returns:
        score
        relationship
        explanation

    Score scale:

        1.00  Exact same condition
        0.95  Known synonym
        0.90  Known subtype relationship
        0.75  Strong lexical/clinical relationship
        0.45  Broad related disease category
        0.20  Generic disease-category overlap
        0.00  Unrelated
        None  Unknown
    """

    patient = normalize_text(
        patient_condition
    )

    trial = normalize_text(
        trial_condition
    )

    if not patient or not trial:
        return (
            None,
            "unknown",
            "Condition information was unavailable.",
        )

    # --------------------------------------------------------
    # Exact match
    # --------------------------------------------------------

    if patient == trial:

        return (
            1.00,
            "exact",
            "The trial condition exactly matches the requested condition.",
        )

    # --------------------------------------------------------
    # Canonical concepts
    # --------------------------------------------------------

    patient_canonical = canonical_condition(
        patient
    )

    trial_canonical = canonical_condition(
        trial
    )

    if (
        patient_canonical
        and trial_canonical
        and patient_canonical == trial_canonical
    ):

        return (
            0.95,
            "synonym",
            "The trial uses a recognized synonym or equivalent name for the requested condition.",
        )

    # --------------------------------------------------------
    # Patient asks for parent condition;
    # trial studies a known subtype.
    # --------------------------------------------------------

    if patient_canonical:

        children = CONDITION_HIERARCHY.get(
            patient_canonical,
            set(),
        )

        if (
            trial_canonical
            and trial_canonical in children
        ):

            return (
                0.90,
                "specific_subtype",
                "The trial studies a specific subtype of the requested condition.",
            )

    # --------------------------------------------------------
    # Trial is broader than patient's condition.
    # --------------------------------------------------------

    if trial_canonical:

        children = CONDITION_HIERARCHY.get(
            trial_canonical,
            set(),
        )

        if patient_canonical in children:

            return (
                0.75,
                "broader_condition",
                "The trial addresses a broader condition that includes the requested condition.",
            )

    # --------------------------------------------------------
    # Phrase containment
    # --------------------------------------------------------

    if (
        patient in trial
        or trial in patient
    ):

        # Avoid treating generic terms as strong matches.
        if (
            patient not in BROAD_TERMS
            and trial not in BROAD_TERMS
        ):

            return (
                0.75,
                "strong_phrase_relationship",
                "The requested condition and trial condition have a strong phrase-level relationship.",
            )

    # --------------------------------------------------------
    # Token overlap
    # --------------------------------------------------------

    patient_tokens = tokenize(patient)
    trial_tokens = tokenize(trial)

    if patient_tokens and trial_tokens:

        intersection = (
            patient_tokens
            & trial_tokens
        )

        overlap = (
            len(intersection)
            / len(patient_tokens)
        )

        # Strong overlap requires more than one meaningful
        # concept word whenever possible.
        if (
            overlap >= 0.75
            and len(intersection) >= 2
        ):

            return (
                0.75,
                "strong_lexical_relationship",
                "The trial condition shares multiple meaningful terms with the requested condition.",
            )

        if (
            overlap >= 0.50
            and len(intersection) >= 1
        ):

            return (
                0.45,
                "related_condition",
                "The trial condition shares some meaningful terminology with the requested condition.",
            )

    # --------------------------------------------------------
    # Broad disease category
    # --------------------------------------------------------

    patient_is_broad = (
        patient in BROAD_TERMS
    )

    trial_is_broad = (
        trial in BROAD_TERMS
    )

    if patient_is_broad or trial_is_broad:

        return (
            0.20,
            "broad_category",
            "The trial and requested condition share only a broad disease category.",
        )

    # --------------------------------------------------------
    # No meaningful relationship
    # --------------------------------------------------------

    return (
        0.0,
        "unrelated",
        "The trial condition does not appear meaningfully related to the requested condition.",
    )


def condition_relevance(
    patient_condition,
    trial_conditions,
):
    """
    Evaluate all conditions attached to a trial and return
    the strongest medically relevant relationship.

    This prevents a trial with many unrelated conditions
    from receiving a high score simply because one generic
    word happens to overlap.
    """

    if is_missing(patient_condition):
        return (
            None,
            "unknown",
            "Patient condition was not provided.",
        )

    if is_missing(trial_conditions):
        return (
            None,
            "unknown",
            "Trial condition information was unavailable.",
        )

    trial_condition_list = (
        extract_trial_conditions(
            trial_conditions
        )
    )

    if not trial_condition_list:
        return (
            None,
            "unknown",
            "Trial condition information was unavailable.",
        )

    candidates = []

    for trial_condition in trial_condition_list:

        (
            score,
            relationship,
            explanation,
        ) = condition_similarity(
            patient_condition,
            trial_condition,
        )

        if score is not None:

            candidates.append(
                (
                    score,
                    relationship,
                    explanation,
                    trial_condition,
                )
            )

    if not candidates:

        return (
            None,
            "unknown",
            "Trial condition information could not be evaluated.",
        )

    # Highest relationship wins.
    candidates.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    (
        best_score,
        best_relationship,
        best_explanation,
        best_condition,
    ) = candidates[0]

    if best_score == 0:

        return (
            0.0,
            "incompatible",
            "No meaningful condition relationship was identified.",
        )

    return (
        best_score,
        best_relationship,
        (
            f"{best_explanation} "
            f"Matched trial condition: '{best_condition}'."
        ),
    )


# ============================================================
# AGE
# ============================================================

def age_compatibility(
    patient_age,
    minimum_age,
    maximum_age,
):

    if patient_age is None:

        return (
            None,
            "unknown",
            "Patient age was not provided.",
        )

    min_age = safe_float(
        minimum_age
    )

    max_age = safe_float(
        maximum_age
    )

    if (
        min_age is not None
        and patient_age < min_age
    ):

        return (
            0.0,
            "incompatible",
            (
                f"Trial minimum age is "
                f"{min_age:g}; patient is "
                f"{patient_age:g}."
            ),
        )

    if (
        max_age is not None
        and patient_age > max_age
    ):

        return (
            0.0,
            "incompatible",
            (
                f"Trial maximum age is "
                f"{max_age:g}; patient is "
                f"{patient_age:g}."
            ),
        )

    if (
        min_age is not None
        or max_age is not None
    ):

        return (
            1.0,
            "compatible",
            "Patient age is within the available trial age range.",
        )

    return (
        None,
        "unknown",
        "Trial age limits were unavailable.",
    )


# ============================================================
# SEX
# ============================================================

def sex_compatibility(
    patient_sex,
    trial_sex,
):

    if is_missing(patient_sex):

        return (
            None,
            "unknown",
            "Patient sex was not provided.",
        )

    if is_missing(trial_sex):

        return (
            None,
            "unknown",
            "Trial sex requirement was unavailable.",
        )

    patient = normalize_text(
        patient_sex
    )

    trial = normalize_text(
        trial_sex
    )

    if patient in {
        "f",
        "female",
        "woman",
    }:
        patient = "FEMALE"

    elif patient in {
        "m",
        "male",
        "man",
    }:
        patient = "MALE"

    if trial in {
        "all",
        "both",
        "any",
        "male and female",
    }:

        return (
            1.0,
            "compatible",
            "Trial accepts all sexes.",
        )

    if trial in {
        "male",
        "female",
    }:

        if patient == trial.upper():

            return (
                1.0,
                "compatible",
                "Sex requirement appears compatible.",
            )

        return (
            0.0,
            "incompatible",
            (
                "Trial is restricted to "
                f"{trial.lower()} participants."
            ),
        )

    return (
        None,
        "unknown",
        "Trial sex requirement could not be interpreted.",
    )


# ============================================================
# ELIGIBILITY
# ============================================================

def evaluate_eligibility(
    patient_age,
    patient_sex,
    minimum_age,
    maximum_age,
    trial_sex,
):

    checks = []

    age_result = age_compatibility(
        patient_age,
        minimum_age,
        maximum_age,
    )

    checks.append(
        {
            "criterion": "age",
            "score": age_result[0],
            "status": age_result[1],
            "reason": age_result[2],
        }
    )

    sex_result = sex_compatibility(
        patient_sex,
        trial_sex,
    )

    checks.append(
        {
            "criterion": "sex",
            "score": sex_result[0],
            "status": sex_result[1],
            "reason": sex_result[2],
        }
    )

    incompatible = [
        check
        for check in checks
        if check["status"] == "incompatible"
    ]

    if incompatible:

        return {
            "status": "incompatible",
            "score": 0.0,
            "checks": checks,
        }

    known_scores = [
        check["score"]
        for check in checks
        if check["score"] is not None
    ]

    if not known_scores:

        return {
            "status": "unknown",
            "score": None,
            "checks": checks,
        }

    return {
        "status": "compatible",
        "score": (
            sum(known_scores)
            / len(known_scores)
        ),
        "checks": checks,
    }


# ============================================================
# RECRUITMENT
# ============================================================

def recruitment_score(status):

    normalized = normalize_status(
        status
    )

    if normalized is None:

        return (
            None,
            "unknown",
        )

    if normalized == "RECRUITING":

        return (
            1.0,
            "compatible",
        )

    if normalized == "ENROLLING_BY_INVITATION":

        return (
            0.90,
            "compatible",
        )

    if normalized == "ACTIVE_NOT_RECRUITING":

        return (
            0.0,
            "not_recruiting",
        )

    if normalized in {
        "NOT_YET_RECRUITING",
        "SUSPENDED",
        "TERMINATED",
        "COMPLETED",
        "WITHDRAWN",
    }:

        return (
            0.0,
            "not_recruiting",
        )

    return (
        None,
        "unknown",
    )


# ============================================================
# DISTANCE
# ============================================================

def haversine_miles(
    lat1,
    lon1,
    lat2,
    lon2,
):

    if None in (
        lat1,
        lon1,
        lat2,
        lon2,
    ):

        return None

    radius_miles = 3958.8

    phi1 = math.radians(
        lat1
    )

    phi2 = math.radians(
        lat2
    )

    d_phi = math.radians(
        lat2 - lat1
    )

    d_lambda = math.radians(
        lon2 - lon1
    )

    a = (
        math.sin(d_phi / 2) ** 2
        +
        math.cos(phi1)
        * math.cos(phi2)
        * math.sin(d_lambda / 2) ** 2
    )

    c = (
        2
        * math.atan2(
            math.sqrt(a),
            math.sqrt(1 - a),
        )
    )

    return radius_miles * c


def get_nearest_site(
    trial_id,
    sites,
    origin_latitude,
    origin_longitude,
):

    if (
        origin_latitude is None
        or origin_longitude is None
    ):

        return None

    trial_sites = sites[
        sites["nct_id"] == trial_id
    ].copy()

    if trial_sites.empty:

        return None

    if (
        "latitude" not in trial_sites.columns
        or "longitude" not in trial_sites.columns
    ):

        return None

    trial_sites["latitude"] = pd.to_numeric(
        trial_sites["latitude"],
        errors="coerce",
    )

    trial_sites["longitude"] = pd.to_numeric(
        trial_sites["longitude"],
        errors="coerce",
    )

    trial_sites = trial_sites.dropna(
        subset=[
            "latitude",
            "longitude",
        ]
    )

    if trial_sites.empty:

        return None

    trial_sites["distance_miles"] = (
        trial_sites.apply(
            lambda row:
                haversine_miles(
                    origin_latitude,
                    origin_longitude,
                    row["latitude"],
                    row["longitude"],
                ),
            axis=1,
        )
    )

    trial_sites = trial_sites.dropna(
        subset=["distance_miles"]
    )

    if trial_sites.empty:

        return None

    nearest = (
        trial_sites
        .sort_values(
            "distance_miles"
        )
        .iloc[0]
    )

    return nearest.to_dict()


def accessibility_score(
    nearest_site,
    max_distance_miles=None,
):

    if nearest_site is None:

        return (
            None,
            "unknown",
            None,
        )

    distance = safe_float(
        nearest_site.get(
            "distance_miles"
        )
    )

    if distance is None:

        return (
            None,
            "unknown",
            None,
        )

    if (
        max_distance_miles is not None
        and distance > max_distance_miles
    ):

        return (
            0.0,
            "incompatible",
            distance,
        )

    if max_distance_miles is not None:

        score = max(
            0.0,
            1.0
            - (
                distance
                / max_distance_miles
            ),
        )

        return (
            score,
            "compatible",
            distance,
        )

    if distance <= 10:
        score = 1.0

    elif distance <= 25:
        score = 0.85

    elif distance <= 50:
        score = 0.70

    elif distance <= 100:
        score = 0.50

    elif distance <= 250:
        score = 0.30

    else:
        score = 0.10

    return (
        score,
        "compatible",
        distance,
    )


# ============================================================
# PREFERENCES
# ============================================================

def preference_score(
    row,
    preferred_study_type=None,
):

    scores = []
    reasons = []

    if preferred_study_type:

        trial_type = normalize_text(
            row.get("study_type")
        )

        preferred_type = normalize_text(
            preferred_study_type
        )

        if trial_type:

            if trial_type == preferred_type:

                scores.append(1.0)

                reasons.append(
                    "Study type matches your preference."
                )

            else:

                scores.append(0.0)

    if not scores:

        return (
            None,
            [],
        )

    return (
        sum(scores)
        / len(scores),
        reasons,
    )


# ============================================================
# WEIGHTED MATCH SCORE
# ============================================================

def calculate_match_score(
    components,
):

    numerator = 0.0
    denominator = 0.0

    used_components = []
    unknown_components = []

    for component, weight in WEIGHTS.items():

        score = components.get(
            component
        )

        if score is None:

            unknown_components.append(
                component
            )

            continue

        numerator += (
            score
            * weight
        )

        denominator += weight

        used_components.append(
            component
        )

    if denominator == 0:

        return (
            None,
            0.0,
            used_components,
            unknown_components,
        )

    return (
        numerator / denominator,
        denominator,
        used_components,
        unknown_components,
    )


# ============================================================
# EVIDENCE COVERAGE
# ============================================================

def calculate_evidence_coverage(
    used_components,
):

    total_weight = sum(
        WEIGHTS.values()
    )

    used_weight = sum(
        WEIGHTS[component]
        for component in used_components
    )

    if total_weight == 0:

        return 0.0

    return (
        used_weight
        / total_weight
    )


def confidence_label(
    coverage
):

    if coverage >= 0.80:

        return "HIGH"

    if coverage >= 0.60:

        return "MODERATE"

    return "LIMITED"


# ============================================================
# PATIENT-FACING DISCLAIMER
# ============================================================

def generate_disclaimer(
    unknown_components,
    eligibility_checks,
):

    messages = []

    unknown = set(
        unknown_components
    )

    if "medical_relevance" in unknown:

        messages.append(
            "CITE could not determine how closely "
            "the trial's condition information relates "
            "to your selected condition."
        )

    if "eligibility_compatibility" in unknown:

        unknown_criteria = {
            check["criterion"]
            for check in eligibility_checks
            if check["status"] == "unknown"
        }

        if "age" in unknown_criteria:

            messages.append(
                "Trial age requirements were unavailable "
                "or incomplete."
            )

        if "sex" in unknown_criteria:

            messages.append(
                "Trial sex requirements were unavailable "
                "or could not be interpreted."
            )

        messages.append(
            "Other inclusion and exclusion criteria "
            "may require review by the study team."
        )

    if "recruitment_fit" in unknown:

        messages.append(
            "Current recruitment status could not be verified."
        )

    if "accessibility" in unknown:

        messages.append(
            "A trial site could not be located well enough "
            "to evaluate travel accessibility."
        )

    if "preferences" in unknown:

        messages.append(
            "No applicable study-preference information "
            "was available."
        )

    messages.append(
        "The CITE Match percentage is based only on "
        "information available to CITE. It does not "
        "determine whether you are eligible for the study. "
        "Please verify eligibility and participation "
        "requirements with the study team."
    )

    # Deduplicate.
    output = []

    for message in messages:

        if message not in output:

            output.append(
                message
            )

    return output


# ============================================================
# MAIN MATCHER
# ============================================================

def cite_match(
    condition=None,
    age=None,
    patient_sex=None,
    origin_latitude=None,
    origin_longitude=None,
    max_distance_miles=None,
    recruiting_only=False,
    preferred_study_type=None,
    top_n=10,
):

    metadata, sites = load_data()

    results = []

    for _, row in metadata.iterrows():

        trial_id = row["nct_id"]

        # ----------------------------------------------------
        # RECRUITMENT
        # ----------------------------------------------------

        recruitment_status = normalize_status(
            row.get(
                "overall_status"
            )
        )

        (
            recruitment_value,
            recruitment_state,
        ) = recruitment_score(
            row.get(
                "overall_status"
            )
        )

        if recruiting_only:

            if (
                recruitment_status
                not in RECRUITING_STATUSES
            ):

                continue

        # ----------------------------------------------------
        # ELIGIBILITY
        # ----------------------------------------------------

        eligibility = evaluate_eligibility(
            patient_age=age,
            patient_sex=patient_sex,
            minimum_age=row.get(
                "minimum_age_years"
            ),
            maximum_age=row.get(
                "maximum_age_years"
            ),
            trial_sex=row.get(
                "sex"
            ),
        )

        # Known incompatibility = exclude.
        if (
            eligibility["status"]
            == "incompatible"
        ):

            continue

        # ----------------------------------------------------
        # MEDICAL RELEVANCE
        # ----------------------------------------------------

        (
            medical_value,
            medical_relationship,
            medical_explanation,
        ) = condition_relevance(
            condition,
            row.get(
                "conditions"
            ),
        )

        # Known unrelated condition = exclude.
        if (
            medical_relationship
            == "incompatible"
        ):

            continue

        # ----------------------------------------------------
        # ACCESSIBILITY
        # ----------------------------------------------------

        nearest_site = get_nearest_site(
            trial_id,
            sites,
            origin_latitude,
            origin_longitude,
        )

        (
            accessibility_value,
            accessibility_state,
            distance,
        ) = accessibility_score(
            nearest_site,
            max_distance_miles,
        )

        # Known site outside user radius = exclude.
        if (
            accessibility_state
            == "incompatible"
        ):

            continue

        # ----------------------------------------------------
        # PREFERENCES
        # ----------------------------------------------------

        (
            preferences_value,
            preference_reasons,
        ) = preference_score(
            row,
            preferred_study_type,
        )

        # Explicit study type mismatch = exclude.
        if preferred_study_type:

            trial_type = normalize_text(
                row.get(
                    "study_type"
                )
            )

            desired_type = normalize_text(
                preferred_study_type
            )

            if (
                trial_type
                and desired_type
                and trial_type
                != desired_type
            ):

                continue

        # ----------------------------------------------------
        # COMPONENTS
        # ----------------------------------------------------

        components = {
            "medical_relevance":
                medical_value,

            "eligibility_compatibility":
                eligibility["score"],

            "recruitment_fit":
                recruitment_value,

            "accessibility":
                accessibility_value,

            "preferences":
                preferences_value,
        }

        (
            match_score,
            evidence_weight,
            used_components,
            unknown_components,
        ) = calculate_match_score(
            components
        )

        if match_score is None:

            continue

        # ----------------------------------------------------
        # EVIDENCE COVERAGE
        # ----------------------------------------------------

        evidence_coverage = (
            calculate_evidence_coverage(
                used_components
            )
        )

        confidence = confidence_label(
            evidence_coverage
        )

        # ----------------------------------------------------
        # REASONS
        # ----------------------------------------------------

        reasons = []
        considerations = []

        # Medical
        if medical_value is not None:

            if medical_value >= 0.95:

                reasons.append(
                    "Condition is an exact or recognized equivalent match."
                )

            elif medical_value >= 0.90:

                reasons.append(
                    "Trial studies a specific subtype of the requested condition."
                )

            elif medical_value >= 0.75:

                reasons.append(
                    "Trial condition is closely related to the requested condition."
                )

            elif medical_value >= 0.45:

                reasons.append(
                    "Trial condition has a moderate relationship to the requested condition."
                )

            elif medical_value >= 0.20:

                considerations.append(
                    "Medical relevance is limited because the trial addresses only a broad disease category."
                )

            reasons.append(
                f"Medical relevance score: "
                f"{medical_value * 100:.0f}%."
            )

        else:

            considerations.append(
                "Medical relevance could not be evaluated from available information."
            )

        # Eligibility
        for check in eligibility["checks"]:

            if (
                check["status"]
                == "compatible"
            ):

                if (
                    check["criterion"]
                    == "age"
                ):

                    reasons.append(
                        "Age appears compatible with the available trial age limits."
                    )

                elif (
                    check["criterion"]
                    == "sex"
                ):

                    reasons.append(
                        "Sex requirement appears compatible."
                    )

            elif (
                check["status"]
                == "unknown"
            ):

                considerations.append(
                    check["reason"]
                )

        # Recruitment
        if (
            recruitment_state
            == "compatible"
        ):

            if (
                recruitment_status
                == "RECRUITING"
            ):

                reasons.append(
                    "Currently recruiting."
                )

            elif (
                recruitment_status
                == "ENROLLING_BY_INVITATION"
            ):

                reasons.append(
                    "Currently enrolling by invitation."
                )

        elif (
            recruitment_state
            == "unknown"
        ):

            considerations.append(
                "Recruitment status could not be verified."
            )

        # Accessibility
        if (
            accessibility_state
            == "compatible"
        ):

            if distance is not None:

                reasons.append(
                    "Nearest known trial site is approximately "
                    f"{distance:.1f} miles away."
                )

        elif (
            accessibility_state
            == "unknown"
        ):

            considerations.append(
                "Site accessibility could not be determined."
            )

        # Preferences
        reasons.extend(
            preference_reasons
        )

        # Unknown components
        for component in unknown_components:

            label = component.replace(
                "_",
                " ",
            ).capitalize()

            if (
                component
                not in {
                    "eligibility_compatibility",
                }
            ):

                considerations.append(
                    f"{label} could not be evaluated from available information."
                )

        # ----------------------------------------------------
        # DISCLAIMER
        # ----------------------------------------------------

        disclaimer = generate_disclaimer(
            unknown_components,
            eligibility["checks"],
        )

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        results.append(
            {
                "nct_id":
                    trial_id,

                "brief_title":
                    row.get(
                        "brief_title",
                        "",
                    ),

                "match_score":
                    round(
                        match_score * 100,
                        1,
                    ),

                "confidence":
                    confidence,

                "evidence_coverage":
                    round(
                        evidence_coverage * 100,
                        1,
                    ),

                "recruitment_status":
                    (
                        recruitment_status
                        or "UNKNOWN"
                    ),

                "medical_relevance":
                    (
                        None
                        if medical_value is None
                        else round(
                            medical_value * 100,
                            1,
                        )
                    ),

                "medical_relationship":
                    medical_relationship,

                "medical_explanation":
                    medical_explanation,

                "eligibility_compatibility":
                    (
                        None
                        if eligibility["score"] is None
                        else round(
                            eligibility["score"] * 100,
                            1,
                        )
                    ),

                "accessibility":
                    (
                        None
                        if accessibility_value is None
                        else round(
                            accessibility_value * 100,
                            1,
                        )
                    ),

                "distance_miles":
                    (
                        None
                        if distance is None
                        else round(
                            distance,
                            1,
                        )
                    ),

                "used_components":
                    used_components,

                "unknown_components":
                    unknown_components,

                "reasons":
                    reasons,

                "considerations":
                    considerations,

                "disclaimer":
                    disclaimer,

                "eligibility_details":
                    eligibility[
                        "checks"
                    ],
            }
        )

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    results.sort(
        key=lambda result: (
            result["match_score"],
            result["evidence_coverage"],
            (
                result["medical_relevance"]
                if result["medical_relevance"]
                is not None
                else -1
            ),
        ),
        reverse=True,
    )

    return results[:top_n]


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print("=" * 70)
    print("CITE-MATCH V0.3 TEST")
    print("=" * 70)

    results = cite_match(
        condition="thyroid cancer",
        age=58,
        patient_sex="FEMALE",

        # Baltimore test location
        origin_latitude=39.2904,
        origin_longitude=-76.6122,

        max_distance_miles=50,

        recruiting_only=True,

        top_n=10,
    )

    if not results:

        print(
            "\nNo matching trials found."
        )

    else:

        display_columns = [
            "nct_id",
            "brief_title",
            "match_score",
            "confidence",
            "evidence_coverage",
            "recruitment_status",
            "medical_relevance",
            "medical_relationship",
            "eligibility_compatibility",
            "accessibility",
            "distance_miles",
        ]

        output = pd.DataFrame(
            results
        )

        print(
            "\nTop CITE-Match results:\n"
        )

        print(
            output[
                display_columns
            ].to_string(
                index=False
            )
        )

        print("\n")
        print("=" * 70)
        print("MATCH EXPLANATIONS")
        print("=" * 70)

        for i, result in enumerate(
            results[:5],
            start=1,
        ):

            print(
                f"\n#{i} "
                f"{result['nct_id']} — "
                f"{result['match_score']}%"
            )

            print(
                "Evidence coverage: "
                f"{result['evidence_coverage']}%"
            )

            print(
                "Confidence: "
                f"{result['confidence']}"
            )

            print(
                "Medical relevance: "
                f"{result['medical_relevance']}%"
                if result["medical_relevance"]
                is not None
                else
                "Medical relevance: UNKNOWN"
            )

            print(
                "Medical relationship: "
                f"{result['medical_relationship']}"
            )

            print("Why:")

            for reason in result[
                "reasons"
            ]:

                print(
                    f"  ✓ {reason}"
                )

            if result[
                "considerations"
            ]:

                print(
                    "Considerations:"
                )

                for consideration in result[
                    "considerations"
                ]:

                    print(
                        f"  ⚠ {consideration}"
                    )

            print(
                "\nDisclaimer:"
            )

            for disclaimer in result[
                "disclaimer"
            ]:

                print(
                    f"  {disclaimer}"
                )