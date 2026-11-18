from pathlib import Path
import re
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent

INPUT_FILE = BASE_DIR / "cite_trial_condition_concepts.csv"
OUTPUT_FILE = BASE_DIR / "cite_trial_condition_relationships.csv"

STOP_CONCEPT_TERMS = {
    "acute",
    "advanced",
    "adult",
    "adults",
    "benign",
    "cell",
    "cells",
    "chronic",
    "disease",
    "disorder",
    "familial",
    "general",
    "malignant",
    "malignancy",
    "neoplasm",
    "oncology",
    "primary",
    "secondary",
    "severe",
    "syndrome",
    "tumor",
    "tumors",
}

BROAD_CONCEPTS = {
    "cancer",
    "carcinoma",
    "malignant neoplasm",
    "neoplasm",
    "tumor",
    "tumors",
    "disease",
    "disorder",
}

def normalize_text(value):
    """
    Normalize text for conservative comparisons.
    """

    if pd.isna(value):
        return ""

    text = str(value).lower().strip()

    # Normalize punctuation to spaces.
    text = re.sub(r"[^a-z0-9\s\-]", " ", text)

    # Normalize hyphens.
    text = text.replace("-", " ")

    # Collapse whitespace.
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def tokenize(text):
    """
    Return normalized tokens.
    """

    text = normalize_text(text)

    if not text:
        return set()

    return set(text.split())

def is_broad_concept(term):
    normalized = normalize_text(term)

    return normalized in BROAD_CONCEPTS


def meaningful_tokens(text):
    tokens = tokenize(text)

    return {
        token
        for token in tokens
        if token not in STOP_CONCEPT_TERMS
        and len(token) > 2
    }

def classify_lexical_relationship(trial_condition, ontology_term):
    trial = normalize_text(trial_condition)
    ontology = normalize_text(ontology_term)

    if not trial or not ontology:
        return "NO_MATCH", 0.0

    if trial == ontology:
        return "EXACT", 1.0

    trial_tokens = meaningful_tokens(trial)
    ontology_tokens = meaningful_tokens(ontology)

    if not trial_tokens or not ontology_tokens:
        return "NO_MATCH", 0.0

    if trial_tokens == ontology_tokens:
        return "SYNONYM_CANDIDATE", 0.95

    if ontology_tokens < trial_tokens:
        return "SUBTYPE_CANDIDATE", 0.85

    if trial_tokens < ontology_tokens:
        return "PARENT_CANDIDATE", 0.60

    if is_broad_concept(ontology):
        return "BROAD_CONCEPT", 0.25

    intersection = trial_tokens.intersection(ontology_tokens)

    if not intersection:
        return "NO_MATCH", 0.0

    overlap_trial = len(intersection) / len(trial_tokens)
    overlap_ontology = len(intersection) / len(ontology_tokens)

    # Strong overlap only when the shared terminology is
    # actually meaningful.
    if overlap_trial >= 0.75 and overlap_ontology >= 0.75:
        return "RELATED_CANDIDATE", 0.55

    # Weak overlap is not enough for CITE-Match.
    return "NO_MATCH", 0.0

def adjust_score(relationship, raw_score, ontology_term):
    """
    Apply conservative adjustments.

    The resulting score is a medical terminology relationship
    score, NOT a clinical eligibility score.
    """

    if relationship == "NO_MATCH":
        return 0.0

    if relationship == "EXACT":
        return 1.0

    if relationship == "SYNONYM_CANDIDATE":
        return 0.95

    if relationship == "SUBTYPE_CANDIDATE":
        return 0.85

    if relationship == "PARENT_CANDIDATE":
        return 0.60

    if relationship == "RELATED_CANDIDATE":
        return 0.55

    if relationship == "BROAD_CONCEPT":
        return 0.25

    return raw_score

def should_keep_relationship(
    trial_condition,
    ontology_term,
    relationship,
    score
):
    """
    Final quality gate.

    The purpose is to eliminate obviously misleading mappings.
    """

    if relationship == "NO_MATCH":
        return False

    trial_tokens = meaningful_tokens(trial_condition)
    ontology_tokens = meaningful_tokens(ontology_term)

    if not trial_tokens or not ontology_tokens:
        return False

    if is_broad_concept(ontology_term):
        return score >= 0.25

    if len(trial_tokens.intersection(ontology_tokens)) == 0:
        return False

    return True

def main():

    print("=" * 70)
    print("CITE TRIAL CONDITION RELATIONSHIP CLEANER")
    print("=" * 70)

    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Input file not found:\n{INPUT_FILE}"
        )

    print("\nLoading raw ontology mappings...")

    df = pd.read_csv(INPUT_FILE, low_memory=False)

    print(f"Rows loaded: {len(df):,}")
    print(f"Columns: {list(df.columns)}")

    required_columns = {
        "nct_id",
        "condition",
        "ontology",
        "concept_id",
        "matched_term",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            f"\nMissing required columns: {sorted(missing)}\n"
            f"Available columns: {list(df.columns)}"
        )

    if "match_score" in df.columns:

        df["terminology_match_score"] = pd.to_numeric(
            df["match_score"],
            errors="coerce"
        )

    else:

        df["terminology_match_score"] = None

    print("\nClassifying relationships...")

    relationships = []
    relationship_scores = []
    keep_flags = []

    total = len(df)

    for i, row in df.iterrows():

        trial_condition = row["condition"]
        ontology_term = row["matched_term"]

        relationship, raw_score = classify_lexical_relationship(
            trial_condition,
            ontology_term
        )

        score = adjust_score(
            relationship,
            raw_score,
            ontology_term
        )

        keep = should_keep_relationship(
            trial_condition,
            ontology_term,
            relationship,
            score
        )

        relationships.append(relationship)
        relationship_scores.append(score)
        keep_flags.append(keep)

        if (i + 1) % 100_000 == 0:
            print(f"Processed {i + 1:,}/{total:,}")

    df["medical_relationship"] = relationships
    df["medical_relationship_score"] = relationship_scores
    df["keep_relationship"] = keep_flags

    cleaned = df[
        df["keep_relationship"]
    ].copy()

    # Remove helper column.
    cleaned.drop(
        columns=["keep_relationship"],
        inplace=True
    )

    cleaned.sort_values(
        by=[
            "nct_id",
            "condition",
            "medical_relationship_score"
        ],
        ascending=[
            True,
            True,
            False
        ],
        inplace=True
    )

    print("\nSaving cleaned relationship layer...")

    cleaned.to_csv(
        OUTPUT_FILE,
        index=False
    )

    print("\n" + "=" * 70)
    print("COMPLETE")
    print("=" * 70)

    print(f"Input mappings:       {len(df):,}")
    print(f"Cleaned mappings:     {len(cleaned):,}")
    print(f"Removed mappings:     {len(df) - len(cleaned):,}")

    print("\nRelationship summary:")

    print(
        cleaned["medical_relationship"]
        .value_counts()
        .to_string()
    )

    print("\nOntology summary:")

    print(
        cleaned["ontology"]
        .value_counts()
        .to_string()
    )

    print("\nOutput:")
    print(OUTPUT_FILE)

    print("\n" + "=" * 70)
    print("DIAGNOSTIC EXAMPLES")
    print("=" * 70)

    examples = [
        "thyroid cancer",
        "follicular thyroid cancer",
        "breast cancer",
        "diabetes",
        "diabetes mellitus",
        "chronic migraine",
        "migraine",
    ]

    for example in examples:

        subset = cleaned[
            cleaned["condition"]
            .astype(str)
            .str.lower()
            .eq(example.lower())
        ]

        print(f"\n{example.upper()}")

        if subset.empty:
            print("  No retained mappings.")
            continue

        display_columns = [
            "ontology",
            "concept_id",
            "matched_term",
            "medical_relationship",
            "medical_relationship_score",
        ]

        print(
            subset[
                display_columns
            ]
            .head(10)
            .to_string(index=False)
        )


if __name__ == "__main__":
    main()