from pathlib import Path
import re
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent

DO_FILE = BASE_DIR / "cite_medical_ontology.csv"
MESH_FILE = BASE_DIR / "cite_mesh_ontology.csv"
RELATIONSHIP_FILE = BASE_DIR / "cite_trial_condition_relationships_v2.csv"

OUTPUT_GRAPH = BASE_DIR / "cite_medical_concept_graph.csv"
OUTPUT_CONCEPTS = BASE_DIR / "cite_medical_concepts.csv"

def normalize(text):
    if pd.isna(text):
        return ""

    text = str(text).lower().strip()

    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s\-]", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def split_values(value):
    if pd.isna(value):
        return []

    text = str(value).strip()

    if not text:
        return []

    parts = re.split(r"[;|\n]+", text)

    return [
        p.strip()
        for p in parts
        if p.strip()
    ]


def unique_list(values):
    seen = set()
    result = []

    for value in values:
        if not value:
            continue

        key = str(value).strip()

        if key and key not in seen:
            seen.add(key)
            result.append(key)

    return result

print("=" * 70)
print("CITE MEDICAL CONCEPT GRAPH BUILDER")
print("=" * 70)

print("\nLoading Disease Ontology...")
do = pd.read_csv(DO_FILE, low_memory=False)

print(f"Disease Ontology records: {len(do):,}")
print(f"Columns: {list(do.columns)}")

print("\nLoading MeSH...")
mesh = pd.read_csv(MESH_FILE, low_memory=False)

print(f"MeSH records: {len(mesh):,}")
print(f"Columns: {list(mesh.columns)}")

print("\nStandardizing Disease Ontology...")

do_records = []

for _, row in do.iterrows():

    concept_id = str(row.get("doid", "")).strip()

    if not concept_id:
        continue

    preferred = str(row.get("preferred_name", "")).strip()

    if not preferred:
        continue

    synonyms = split_values(row.get("synonyms", ""))
    normalized_terms = split_values(row.get("normalized_terms", ""))
    parents = split_values(row.get("parents", ""))

    terms = unique_list(
        [preferred]
        + synonyms
        + normalized_terms
    )

    do_records.append({
        "ontology": "Disease Ontology",
        "concept_id": concept_id,
        "preferred_name": preferred,
        "normalized_name": normalize(preferred),
        "search_terms": terms,
        "parent_ids": parents,
    })

print(f"Standardized DO concepts: {len(do_records):,}")

print("\nStandardizing MeSH...")

mesh_records = []

for _, row in mesh.iterrows():

    concept_id = str(row.get("mesh_id", "")).strip()

    if not concept_id:
        continue

    preferred = str(row.get("preferred_name", "")).strip()

    if not preferred:
        continue

    synonyms = split_values(row.get("synonyms", ""))
    tree_numbers = split_values(row.get("tree_numbers", ""))

    terms = unique_list(
        [preferred]
        + synonyms
    )

    mesh_records.append({
        "ontology": "MeSH",
        "concept_id": concept_id,
        "preferred_name": preferred,
        "normalized_name": normalize(preferred),
        "search_terms": terms,
        "tree_numbers": tree_numbers,
    })

print(f"Standardized MeSH concepts: {len(mesh_records):,}")

concept_records = []

for record in do_records:

    concept_records.append({
        "ontology": record["ontology"],
        "concept_id": record["concept_id"],
        "preferred_name": record["preferred_name"],
        "normalized_name": record["normalized_name"],
        "search_terms": "|".join(record["search_terms"]),
        "parent_ids": "|".join(record["parent_ids"]),
        "tree_numbers": "",
    })


for record in mesh_records:

    concept_records.append({
        "ontology": record["ontology"],
        "concept_id": record["concept_id"],
        "preferred_name": record["preferred_name"],
        "normalized_name": record["normalized_name"],
        "search_terms": "|".join(record["search_terms"]),
        "parent_ids": "",
        "tree_numbers": "|".join(record["tree_numbers"]),
    })


concepts = pd.DataFrame(concept_records)

print(f"\nTotal concept records: {len(concepts):,}")

concept_lookup = {}

for _, row in concepts.iterrows():

    key = (
        row["ontology"],
        row["concept_id"]
    )

    concept_lookup[key] = row

print("\nBuilding hierarchy edges...")

edges = []

do_id_set = set(
    str(x).strip()
    for x in do["doid"].dropna()
)


for record in do_records:

    child_id = record["concept_id"]

    for parent_id in record["parent_ids"]:

        parent_id = str(parent_id).strip()

        if parent_id not in do_id_set:
            continue

        parent_row = concept_lookup.get(
            ("Disease Ontology", parent_id)
        )

        child_row = concept_lookup.get(
            ("Disease Ontology", child_id)
        )

        if parent_row is None or child_row is None:
            continue

        edges.append({
            "source_ontology": "Disease Ontology",
            "source_concept_id": child_id,
            "source_name": child_row["preferred_name"],
            "relationship": "CHILD_OF",
            "target_ontology": "Disease Ontology",
            "target_concept_id": parent_id,
            "target_name": parent_row["preferred_name"],
            "evidence": "Disease Ontology parent relationship",
        })

        edges.append({
            "source_ontology": "Disease Ontology",
            "source_concept_id": parent_id,
            "source_name": parent_row["preferred_name"],
            "relationship": "PARENT_OF",
            "target_ontology": "Disease Ontology",
            "target_concept_id": child_id,
            "target_name": child_row["preferred_name"],
            "evidence": "Disease Ontology parent relationship",
        })

print("Building MeSH hierarchy edges...")

mesh_tree_to_concepts = {}

for record in mesh_records:

    for tree_number in record["tree_numbers"]:

        tree_number = tree_number.strip()

        if not tree_number:
            continue

        mesh_tree_to_concepts.setdefault(
            tree_number,
            []
        ).append(record)


for record in mesh_records:

    child_id = record["concept_id"]

    for tree_number in record["tree_numbers"]:

        tree_number = tree_number.strip()

        if "." not in tree_number:
            continue

        parent_tree = tree_number.rsplit(".", 1)[0]

        parent_records = mesh_tree_to_concepts.get(
            parent_tree,
            []
        )

        for parent_record in parent_records:

            parent_id = parent_record["concept_id"]

            if parent_id == child_id:
                continue

            edges.append({
                "source_ontology": "MeSH",
                "source_concept_id": child_id,
                "source_name": record["preferred_name"],
                "relationship": "CHILD_OF",
                "target_ontology": "MeSH",
                "target_concept_id": parent_id,
                "target_name": parent_record["preferred_name"],
                "evidence": "MeSH tree hierarchy",
            })

            edges.append({
                "source_ontology": "MeSH",
                "source_concept_id": parent_id,
                "source_name": parent_record["preferred_name"],
                "relationship": "PARENT_OF",
                "target_ontology": "MeSH",
                "target_concept_id": child_id,
                "target_name": record["preferred_name"],
                "evidence": "MeSH tree hierarchy",
            })


print("Building Disease Ontology ↔ MeSH cross-links...")

do_name_lookup = {}

for record in do_records:

    name = normalize(record["preferred_name"])

    if name:
        do_name_lookup.setdefault(
            name,
            []
        ).append(record)


mesh_name_lookup = {}

for record in mesh_records:

    name = normalize(record["preferred_name"])

    if name:
        mesh_name_lookup.setdefault(
            name,
            []
        ).append(record)


crosslink_count = 0

for name in sorted(
    set(do_name_lookup.keys())
    &
    set(mesh_name_lookup.keys())
):

    for do_record in do_name_lookup[name]:

        for mesh_record in mesh_name_lookup[name]:

            edges.append({
                "source_ontology": "Disease Ontology",
                "source_concept_id": do_record["concept_id"],
                "source_name": do_record["preferred_name"],
                "relationship": "EXACT_CROSS_ONTOLOGY",
                "target_ontology": "MeSH",
                "target_concept_id": mesh_record["concept_id"],
                "target_name": mesh_record["preferred_name"],
                "evidence": "Exact normalized preferred-name match",
            })

            edges.append({
                "source_ontology": "MeSH",
                "source_concept_id": mesh_record["concept_id"],
                "source_name": mesh_record["preferred_name"],
                "relationship": "EXACT_CROSS_ONTOLOGY",
                "target_ontology": "Disease Ontology",
                "target_concept_id": do_record["concept_id"],
                "target_name": do_record["preferred_name"],
                "evidence": "Exact normalized preferred-name match",
            })

            crosslink_count += 1


print(f"Cross-ontology links: {crosslink_count:,}")

graph = pd.DataFrame(edges)

if len(graph) > 0:

    graph = graph.drop_duplicates(
        subset=[
            "source_ontology",
            "source_concept_id",
            "relationship",
            "target_ontology",
            "target_concept_id",
        ]
    ).reset_index(drop=True)

concepts.to_csv(
    OUTPUT_CONCEPTS,
    index=False
)

graph.to_csv(
    OUTPUT_GRAPH,
    index=False
)

print("\n" + "=" * 70)
print("CONCEPT GRAPH COMPLETE")
print("=" * 70)

print(f"Concepts: {len(concepts):,}")
print(f"Graph edges: {len(graph):,}")

if len(graph) > 0:

    print("\nRelationship summary:")

    print(
        graph["relationship"]
        .value_counts()
        .to_string()
    )

print(f"\nConcept table:")
print(OUTPUT_CONCEPTS)

print(f"\nConcept graph:")
print(OUTPUT_GRAPH)

print("\nThe graph is a knowledge layer only.")
print("It does NOT determine clinical eligibility.")