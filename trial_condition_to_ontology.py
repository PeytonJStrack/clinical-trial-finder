from pathlib import Path
import re
from collections import defaultdict

import pandas as pd


# ============================================================
# CITE TRIAL CONDITION → MEDICAL ONTOLOGY MAPPER
# Optimized indexed version
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

TRIAL_FILE = BASE_DIR / "cite_trial_metadata.csv"

DO_LOOKUP_FILE = BASE_DIR / "cite_medical_term_lookup.csv"
DO_ONTOLOGY_FILE = BASE_DIR / "cite_medical_ontology.csv"

MESH_LOOKUP_FILE = BASE_DIR / "cite_mesh_term_lookup.csv"
MESH_ONTOLOGY_FILE = BASE_DIR / "cite_mesh_ontology.csv"

OUTPUT_FILE = BASE_DIR / "cite_trial_condition_concepts.csv"


# ============================================================
# 1. TEXT NORMALIZATION
# ============================================================

def normalize(text):
    if pd.isna(text):
        return ""

    text = str(text).lower()

    text = text.replace("-", " ")
    text = text.replace("/", " ")
    text = text.replace("_", " ")

    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def tokenize(text):
    return {
        token
        for token in normalize(text).split()
        if len(token) >= 3
    }


# ============================================================
# 2. LOAD DATA
# ============================================================

print("=" * 70)
print("CITE TRIAL CONDITION → MEDICAL ONTOLOGY MAPPER")
print("Optimized indexed version")
print("=" * 70)

print("\nLoading trial metadata...")

trials = pd.read_csv(
    TRIAL_FILE,
    low_memory=False
)

print(f"Trials loaded: {len(trials):,}")


print("\nLoading Disease Ontology lookup...")

do_lookup = pd.read_csv(
    DO_LOOKUP_FILE,
    low_memory=False
)

print(f"DO searchable terms: {len(do_lookup):,}")


print("\nLoading Disease Ontology concepts...")

do_ontology = pd.read_csv(
    DO_ONTOLOGY_FILE,
    low_memory=False
)

print(f"DO concepts: {len(do_ontology):,}")


print("\nLoading MeSH lookup...")

mesh_lookup = pd.read_csv(
    MESH_LOOKUP_FILE,
    low_memory=False
)

print(f"MeSH searchable terms: {len(mesh_lookup):,}")


print("\nLoading MeSH concepts...")

mesh_ontology = pd.read_csv(
    MESH_ONTOLOGY_FILE,
    low_memory=False
)

print(f"MeSH concepts: {len(mesh_ontology):,}")


# ============================================================
# 3. BUILD STANDARDIZED TERM TABLES
# ============================================================

print("\nStandardizing ontology lookup tables...")


# ----------------------------
# Disease Ontology
# ----------------------------

do_terms = pd.DataFrame({
    "term": do_lookup["normalized_term"],
    "concept_id": do_lookup["doid"],
    "preferred_name": do_lookup["preferred_name"],
    "term_type": do_lookup["term_type"]
})

do_terms["term"] = do_terms["term"].fillna("").astype(str)
do_terms["concept_id"] = do_terms["concept_id"].fillna("").astype(str)

do_terms = do_terms[
    do_terms["term"].str.strip() != ""
]

print(
    f"Usable DO terms: "
    f"{len(do_terms):,}"
)


# ----------------------------
# MeSH
# ----------------------------

mesh_terms = pd.DataFrame({
    "term": mesh_lookup["normalized_term"],
    "concept_id": mesh_lookup["mesh_id"],
    "preferred_name": mesh_lookup["preferred_name"],
    "term_type": mesh_lookup["match_type"]
})

mesh_terms["term"] = mesh_terms["term"].fillna("").astype(str)
mesh_terms["concept_id"] = mesh_terms["concept_id"].fillna("").astype(str)

mesh_terms = mesh_terms[
    mesh_terms["term"].str.strip() != ""
]

print(
    f"Usable MeSH terms: "
    f"{len(mesh_terms):,}"
)


# ============================================================
# 4. BUILD TERM → CONCEPT MAPS
# ============================================================

def build_term_map(df):

    term_map = defaultdict(set)

    for row in df.itertuples(index=False):

        term = normalize(row.term)

        if not term:
            continue

        concept_id = row.concept_id

        if not concept_id:
            continue

        term_map[term].add(str(concept_id))

    return term_map


print("\nBuilding Disease Ontology term map...")

do_term_map = build_term_map(do_terms)

print(
    f"Unique normalized DO terms: "
    f"{len(do_term_map):,}"
)


print("\nBuilding MeSH term map...")

mesh_term_map = build_term_map(mesh_terms)

print(
    f"Unique normalized MeSH terms: "
    f"{len(mesh_term_map):,}"
)


# ============================================================
# 5. BUILD TOKEN INDEX
# ============================================================

def build_token_index(term_map):

    token_index = defaultdict(set)

    for term in term_map:

        for token in tokenize(term):

            token_index[token].add(term)

    return token_index


print("\nBuilding Disease Ontology token index...")

do_token_index = build_token_index(
    do_term_map
)

print(
    f"DO indexed tokens: "
    f"{len(do_token_index):,}"
)


print("\nBuilding MeSH token index...")

mesh_token_index = build_token_index(
    mesh_term_map
)

print(
    f"MeSH indexed tokens: "
    f"{len(mesh_token_index):,}"
)


# ============================================================
# 6. CANDIDATE GENERATION
# ============================================================

def get_candidates(condition, token_index):

    condition_tokens = tokenize(condition)

    if not condition_tokens:
        return set()

    candidates = set()

    for token in condition_tokens:

        candidates.update(
            token_index.get(token, set())
        )

    return candidates


# ============================================================
# 7. SCORE CANDIDATES
# ============================================================

def score_candidate(condition, candidate):

    condition_norm = normalize(condition)
    candidate_norm = normalize(candidate)

    # Exact match
    if condition_norm == candidate_norm:
        return 1.00, "EXACT"

    condition_tokens = tokenize(condition_norm)
    candidate_tokens = tokenize(candidate_norm)

    if not condition_tokens or not candidate_tokens:
        return 0.0, "NONE"

    # Phrase containment
    if condition_norm in candidate_norm:
        return 0.90, "PHRASE_CONTAINED"

    if candidate_norm in condition_norm:
        return 0.90, "PHRASE_CONTAINS"

    # Token overlap
    overlap = (
        len(condition_tokens & candidate_tokens)
        / len(condition_tokens)
    )

    if overlap >= 1.0:
        return 0.85, "TOKEN_MATCH"

    if overlap >= 0.75:
        return 0.75, "STRONG_TOKEN_MATCH"

    if overlap >= 0.50:
        return 0.60, "PARTIAL_TOKEN_MATCH"

    return 0.0, "WEAK"


# ============================================================
# 8. MAP ONE CONDITION
# ============================================================

def map_condition(
    condition,
    term_map,
    token_index,
    ontology_name,
    max_results=10
):

    if not condition:
        return []

    candidates = get_candidates(
        condition,
        token_index
    )

    if not candidates:
        return []

    results = []

    for candidate in candidates:

        score, match_type = score_candidate(
            condition,
            candidate
        )

        if score <= 0:
            continue

        for concept_id in term_map[candidate]:

            results.append({
                "source_condition": condition,
                "ontology": ontology_name,
                "concept_id": concept_id,
                "matched_term": candidate,
                "match_score": score,
                "match_type": match_type
            })

    results.sort(
        key=lambda x: x["match_score"],
        reverse=True
    )

    return results[:max_results]


# ============================================================
# 9. SPLIT CONDITIONS
# ============================================================

def split_conditions(value):

    if pd.isna(value):
        return []

    text = str(value).strip()

    if not text:
        return []

    if "|" in text:
        parts = text.split("|")

    elif ";" in text:
        parts = text.split(";")

    else:
        parts = [text]

    return [
        part.strip()
        for part in parts
        if part.strip()
    ]


# ============================================================
# 10. PROCESS TRIALS
# ============================================================

print("\n" + "=" * 70)
print("PROCESSING TRIAL CONDITIONS")
print("=" * 70)

records = []
unmapped_conditions = set()

total_trials = len(trials)


for i, row in enumerate(
    trials.itertuples(index=False),
    start=1
):

    nct_id = getattr(row, "nct_id")
    raw_conditions = getattr(row, "conditions")

    conditions = split_conditions(
        raw_conditions
    )

    for condition in conditions:

        # Disease Ontology
        do_matches = map_condition(
            condition=condition,
            term_map=do_term_map,
            token_index=do_token_index,
            ontology_name="Disease Ontology",
            max_results=10
        )

        # MeSH
        mesh_matches = map_condition(
            condition=condition,
            term_map=mesh_term_map,
            token_index=mesh_token_index,
            ontology_name="MeSH",
            max_results=10
        )

        matches = (
            do_matches +
            mesh_matches
        )

        if not matches:
            unmapped_conditions.add(
                condition
            )

        for match in matches:

            records.append({
                "nct_id": nct_id,
                "condition": condition,
                "ontology": match["ontology"],
                "concept_id": match["concept_id"],
                "matched_term": match["matched_term"],
                "match_score": match["match_score"],
                "match_type": match["match_type"]
            })

    # Progress
    if i % 1000 == 0 or i == total_trials:

        print(
            f"Processed "
            f"{i:,}/{total_trials:,}"
        )


# ============================================================
# 11. CREATE OUTPUT
# ============================================================

print("\nBuilding output dataframe...")

output = pd.DataFrame(records)


if not output.empty:

    output = output.sort_values(
        by=[
            "nct_id",
            "condition",
            "match_score"
        ],
        ascending=[
            True,
            True,
            False
        ]
    )


# ============================================================
# 12. SAVE
# ============================================================

print("\nSaving ontology mappings...")

output.to_csv(
    OUTPUT_FILE,
    index=False
)


# ============================================================
# 13. SUMMARY
# ============================================================

print("\n" + "=" * 70)
print("COMPLETE")
print("=" * 70)

print(
    f"Trials processed: "
    f"{total_trials:,}"
)

print(
    f"Ontology mappings: "
    f"{len(output):,}"
)

print(
    f"Unique unmapped conditions: "
    f"{len(unmapped_conditions):,}"
)

print(
    f"Output: {OUTPUT_FILE}"
)


if not output.empty:

    print("\nMatch type summary:")

    print(
        output["match_type"]
        .value_counts()
        .to_string()
    )

    print("\nOntology summary:")

    print(
        output["ontology"]
        .value_counts()
        .to_string()
    )


print("\nCITE terminology mapping complete.")

print(
    "IMPORTANT: These mappings are terminology mappings "
    "only and do NOT determine clinical trial eligibility."
)