from pathlib import Path
import re
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent

CONCEPT_FILE = BASE_DIR / "cite_medical_concepts.csv"
GRAPH_FILE = BASE_DIR / "cite_medical_concept_graph.csv"
RELATIONSHIP_FILE = BASE_DIR / "cite_trial_condition_relationships_v2.csv"

OUTPUT_FILE = BASE_DIR / "cite_medical_search_index.csv"

def normalize(text):

    if pd.isna(text):
        return ""

    text = str(text).lower().strip()

    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s\-]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def split_terms(value):

    if pd.isna(value):
        return []

    value = str(value).strip()

    if not value:
        return []

    return [
        x.strip()
        for x in re.split(r"\|", value)
        if x.strip()
    ]

print("=" * 70)
print("CITE MEDICAL SEARCH INDEX BUILDER")
print("=" * 70)

print("\nLoading concepts...")

concepts = pd.read_csv(
    CONCEPT_FILE,
    low_memory=False
)

print(f"Concepts: {len(concepts):,}")

print("\nLoading concept graph...")

graph = pd.read_csv(
    GRAPH_FILE,
    low_memory=False
)

print(f"Graph edges: {len(graph):,}")

print("\nLoading trial relationships...")

relationships = pd.read_csv(
    RELATIONSHIP_FILE,
    low_memory=False
)

print(f"Trial relationship rows: {len(relationships):,}")

print("\nBuilding term index...")

index_rows = []

for _, row in concepts.iterrows():

    ontology = row["ontology"]
    concept_id = str(row["concept_id"])
    preferred_name = str(row["preferred_name"])

    # Preferred name
    preferred_normalized = normalize(preferred_name)

    if preferred_normalized:

        index_rows.append({
            "query_term": preferred_normalized,
            "display_term": preferred_name,
            "ontology": ontology,
            "concept_id": concept_id,
            "concept_name": preferred_name,
            "term_type": "PREFERRED",
            "search_weight": 1.00,
        })

    # Other search terms
    for term in split_terms(
        row.get("search_terms", "")
    ):

        normalized = normalize(term)

        if not normalized:
            continue

        if normalized == preferred_normalized:
            continue

        index_rows.append({
            "query_term": normalized,
            "display_term": term,
            "ontology": ontology,
            "concept_id": concept_id,
            "concept_name": preferred_name,
            "term_type": "SYNONYM",
            "search_weight": 0.98,
        })


term_index = pd.DataFrame(index_rows)

term_index = term_index.drop_duplicates(
    subset=[
        "query_term",
        "ontology",
        "concept_id",
    ]
).reset_index(drop=True)

print("Building search expansion relationships...")

expansion_rows = []


for _, row in graph.iterrows():

    relationship = row["relationship"]

    if relationship not in {
        "CHILD_OF",
        "PARENT_OF",
        "EXACT_CROSS_ONTOLOGY",
    }:
        continue

    if relationship == "CHILD_OF":
        expansion_weight = 0.90

        expansion_type = "CHILD_OF"

    elif relationship == "PARENT_OF":
        expansion_weight = 0.75

        expansion_type = "PARENT_OF"

    else:

        expansion_weight = 0.98

        expansion_type = "CROSS_ONTOLOGY"

    expansion_rows.append({

        "source_ontology":
            row["source_ontology"],

        "source_concept_id":
            row["source_concept_id"],

        "source_name":
            row["source_name"],

        "relationship":
            expansion_type,

        "target_ontology":
            row["target_ontology"],

        "target_concept_id":
            row["target_concept_id"],

        "target_name":
            row["target_name"],

        "search_weight":
            expansion_weight,
    })


expansion = pd.DataFrame(expansion_rows)

print("Connecting concepts to clinical trials...")

trial_columns = [
    "nct_id",
    "condition",
    "ontology",
    "concept_id",
    "matched_term",
    "raw_match_score",
    "raw_match_type",
    "medical_relationship",
    "medical_relationship_score",
    "relationship_confidence",
    "hierarchy_verified",
]

available_trial_columns = [
    col
    for col in trial_columns
    if col in relationships.columns
]

trial_map = relationships[
    available_trial_columns
].copy()

def relationship_search_weight(relationship):

    if relationship == "EXACT":
        return 1.00

    if relationship == "SYNONYM_CANDIDATE":
        return 0.98

    if relationship == "BROAD_CONCEPT":
        return 0.75

    if relationship == "RELATED_CANDIDATE":
        return 0.40

    return 0.20


trial_map["search_relationship_weight"] = (
    trial_map["medical_relationship"]
    .map(relationship_search_weight)
    .fillna(0.20)
)

print("Building final search index...")

search_rows = []

for _, row in trial_map.iterrows():

    search_rows.append({

        "index_type": "TRIAL",

        "query_term": normalize(
            row.get("condition", "")
        ),

        "display_term":
            row.get("condition", ""),

        "ontology":
            row.get("ontology", ""),

        "concept_id":
            row.get("concept_id", ""),

        "concept_name":
            row.get("matched_term", ""),

        "relationship":
            row.get("medical_relationship", ""),

        "trial_id":
            row.get("nct_id", ""),

        "trial_condition":
            row.get("condition", ""),

        "search_weight":
            row.get(
                "search_relationship_weight",
                0.20
            ),

        "confidence":
            row.get(
                "relationship_confidence",
                ""
            ),
    })


for _, row in term_index.iterrows():

    search_rows.append({

        "index_type": "TERM",

        "query_term":
            row["query_term"],

        "display_term":
            row["display_term"],

        "ontology":
            row["ontology"],

        "concept_id":
            row["concept_id"],

        "concept_name":
            row["concept_name"],

        "relationship":
            row["term_type"],

        "trial_id": "",

        "trial_condition": "",

        "search_weight":
            row["search_weight"],

        "confidence":
            "high",
    })


search_index = pd.DataFrame(search_rows)

search_index = search_index.drop_duplicates(
    subset=[
        "index_type",
        "query_term",
        "ontology",
        "concept_id",
        "trial_id",
        "trial_condition",
        "relationship",
    ]
).reset_index(drop=True)

search_index.to_csv(
    OUTPUT_FILE,
    index=False
)

print("\n" + "=" * 70)
print("MEDICAL SEARCH INDEX COMPLETE")
print("=" * 70)

print(f"Search index rows: {len(search_index):,}")

print("\nIndex types:")

print(
    search_index["index_type"]
    .value_counts()
    .to_string()
)

print("\nRelationships:")

print(
    search_index["relationship"]
    .value_counts()
    .head(20)
    .to_string()
)

print("\nOutput:")
print(OUTPUT_FILE)

print("\nThis index supports BROAD SEARCH.")
print("It does NOT determine clinical eligibility.")