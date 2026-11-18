from pathlib import Path
import pandas as pd
import re

BASE_DIR = Path(__file__).resolve().parent

RAW_MAPPINGS = BASE_DIR / "cite_trial_condition_concepts.csv"

DO_CONCEPTS = BASE_DIR / "cite_medical_ontology.csv"
MESH_CONCEPTS = BASE_DIR / "cite_mesh_ontology.csv"

OUTPUT = BASE_DIR / "cite_trial_condition_relationships_v2.csv"

def normalize(value):
    if pd.isna(value):
        return ""

    text = str(value).lower().strip()

    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def tokens(value):
    return set(normalize(value).split())

GENERIC_WORDS = {
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

def load_file(path, name):

    print(f"\nLoading {name}...")

    if not path.exists():
        raise FileNotFoundError(path)

    df = pd.read_csv(path, low_memory=False)

    print(f"Rows: {len(df):,}")
    print(f"Columns: {list(df.columns)}")

    return df

def find_column(df, candidates):

    normalized = {
        str(c).lower().strip(): c
        for c in df.columns
    }

    for candidate in candidates:

        if candidate.lower() in normalized:
            return normalized[candidate.lower()]

    return None

def build_concept_table(df, ontology_name):

    id_col = find_column(
        df,
        [
            "concept_id",
            "doid",
            "mesh_id",
            "meshid",
            "id",
        ],
    )

    name_col = find_column(
        df,
        [
            "preferred_name",
            "name",
            "term",
            "label",
        ],
    )

    parent_col = find_column(
        df,
        [
            "parent_id",
            "parent_ids",
            "parents",
            "parent",
            "is_a",
        ],
    )

    tree_col = find_column(
        df,
        [
            "tree_numbers",
            "tree_number",
            "tree",
        ],
    )

    print(f"\n{ontology_name} structure:")
    print(f"  ID column:     {id_col}")
    print(f"  Name column:   {name_col}")
    print(f"  Parent column: {parent_col}")
    print(f"  Tree column:   {tree_col}")

    if id_col is None or name_col is None:
        raise ValueError(
            f"Could not identify ID/name columns in {ontology_name}."
        )

    result = pd.DataFrame()

    result["concept_id"] = (
        df[id_col].astype(str).str.strip()
    )

    result["preferred_name"] = (
        df[name_col].astype(str).str.strip()
    )

    if parent_col:
        result["parent_data"] = (
            df[parent_col].fillna("").astype(str)
        )
    else:
        result["parent_data"] = ""

    if tree_col:
        result["tree_data"] = (
            df[tree_col].fillna("").astype(str)
        )
    else:
        result["tree_data"] = ""

    result["ontology"] = ontology_name

    return result

def contains_parent_reference(parent_data, target_id):

    if not parent_data:
        return False

    # Handle common delimiters.
    parts = re.split(
        r"[,;| ]+",
        parent_data
    )

    return target_id in parts

def tree_is_ancestor(parent_tree, child_tree):

    if not parent_tree or not child_tree:
        return False

    parent_tree = parent_tree.strip()
    child_tree = child_tree.strip()

    return (
        child_tree.startswith(parent_tree + ".")
        or child_tree.startswith(parent_tree + " ")
    )

def lexical_relationship(condition, term):

    condition_norm = normalize(condition)
    term_norm = normalize(term)

    if not condition_norm or not term_norm:
        return "NO_MATCH", 0.0

    if condition_norm == term_norm:
        return "EXACT", 1.0

    condition_tokens = (
        tokens(condition)
        - GENERIC_WORDS
    )

    term_tokens = (
        tokens(term)
        - GENERIC_WORDS
    )

    if not condition_tokens or not term_tokens:
        return "NO_MATCH", 0.0

    # Exact meaningful-token equivalence.
    if condition_tokens == term_tokens:
        return "SYNONYM_CANDIDATE", 0.95

    # Shared meaningful terminology.
    overlap = condition_tokens & term_tokens

    if not overlap:
        return "NO_MATCH", 0.0

    # Require meaningful overlap, not just a modifier.
    condition_fraction = (
        len(overlap) / len(condition_tokens)
    )

    term_fraction = (
        len(overlap) / len(term_tokens)
    )

    if (
        condition_fraction >= 0.75
        and term_fraction >= 0.75
    ):
        return "RELATED_CANDIDATE", 0.50

    return "NO_MATCH", 0.0

def main():

    print("=" * 70)
    print("CITE MEDICAL RELATIONSHIP BUILDER")
    print("Hierarchy-aware / conservative version")
    print("=" * 70)

    raw = load_file(
        RAW_MAPPINGS,
        "raw condition mappings"
    )

    do = load_file(
        DO_CONCEPTS,
        "Disease Ontology concepts"
    )

    mesh = load_file(
        MESH_CONCEPTS,
        "MeSH concepts"
    )

    do_table = build_concept_table(
        do,
        "Disease Ontology"
    )

    mesh_table = build_concept_table(
        mesh,
        "MeSH"
    )

    concepts = pd.concat(
        [
            do_table,
            mesh_table,
        ],
        ignore_index=True
    )

    concept_lookup = {}

    for _, row in concepts.iterrows():

        concept_id = row["concept_id"]

        concept_lookup[
            (
                row["ontology"],
                concept_id
            )
        ] = row

    print(
        f"\nConcept records available: "
        f"{len(concept_lookup):,}"
    )

    required = {
        "nct_id",
        "condition",
        "ontology",
        "concept_id",
        "matched_term",
        "match_score",
        "match_type",
    }

    missing = required - set(raw.columns)

    if missing:
        raise ValueError(
            f"Missing raw mapping columns: {missing}"
        )

    print("\nProcessing mappings...")

    output_rows = []

    total = len(raw)

    for i, row in raw.iterrows():

        ontology = str(
            row["ontology"]
        ).strip()

        concept_id = str(
            row["concept_id"]
        ).strip()

        condition = row["condition"]
        matched_term = row["matched_term"]

        concept = concept_lookup.get(
            (
                ontology,
                concept_id
            )
        )

        condition_norm = normalize(condition)
        term_norm = normalize(matched_term)

        if condition_norm == term_norm:

            relationship = "EXACT"
            relationship_score = 1.0

        else:

            relationship, relationship_score = (
                lexical_relationship(
                    condition,
                    matched_term
                )
            )

        if term_norm in BROAD_CONCEPTS:

            if relationship != "EXACT":

                relationship = "BROAD_CONCEPT"
                relationship_score = 0.20

        hierarchy_verified = False

        if concept is not None:

            parent_data = str(
                concept["parent_data"]
            )

            if contains_parent_reference(
                parent_data,
                concept_id
            ):
                hierarchy_verified = True

        if relationship in {
            "RELATED_CANDIDATE",
            "SYNONYM_CANDIDATE",
        }:

            relationship_confidence = (
                "candidate"
            )

        elif relationship == "EXACT":

            relationship_confidence = (
                "high"
            )

        elif relationship == "BROAD_CONCEPT":

            relationship_confidence = (
                "low"
            )

        else:

            relationship_confidence = (
                "candidate"
            )

        output_rows.append(
            {
                "nct_id": row["nct_id"],
                "condition": condition,
                "ontology": ontology,
                "concept_id": concept_id,
                "matched_term": matched_term,
                "raw_match_score": row["match_score"],
                "raw_match_type": row["match_type"],
                "medical_relationship": relationship,
                "medical_relationship_score": relationship_score,
                "relationship_confidence":
                    relationship_confidence,
                "hierarchy_verified":
                    hierarchy_verified,
            }
        )

        if (i + 1) % 100_000 == 0:

            print(
                f"Processed "
                f"{i + 1:,}/{total:,}"
            )

    result = pd.DataFrame(output_rows)

    result = result[
        result["medical_relationship"] != "NO_MATCH"
    ].copy()

    result.sort_values(
        [
            "nct_id",
            "condition",
            "medical_relationship_score",
        ],
        ascending=[
            True,
            True,
            False,
        ],
        inplace=True,
    )

    result.drop_duplicates(
        subset=[
            "nct_id",
            "condition",
            "ontology",
            "concept_id",
        ],
        keep="first",
        inplace=True,
    )

    result.to_csv(
        OUTPUT,
        index=False
    )

    print("\n" + "=" * 70)
    print("COMPLETE")
    print("=" * 70)

    print(
        f"Output rows: {len(result):,}"
    )

    print("\nRelationships:")

    print(
        result[
            "medical_relationship"
        ]
        .value_counts()
        .to_string()
    )

    print("\nOutput:")
    print(OUTPUT)


if __name__ == "__main__":
    main()