from pathlib import Path
import re
import requests
import xml.etree.ElementTree as ET
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent

MESH_DIR = BASE_DIR / "medical_ontology"
MESH_DIR.mkdir(exist_ok=True)

MESH_XML = MESH_DIR / "desc2026.xml"

MESH_URL = (
    "https://nlmpubs.nlm.nih.gov/"
    "projects/mesh/MESH_FILES/xmlmesh/desc2026.xml"
)

OUTPUT_ONTOLOGY = BASE_DIR / "cite_mesh_ontology.csv"
OUTPUT_LOOKUP = BASE_DIR / "cite_mesh_term_lookup.csv"

def normalize_text(text):
    if text is None:
        return ""

    text = str(text).strip().lower()

    text = text.replace("&", " and ")

    text = re.sub(r"[^a-z0-9\s\-]", " ", text)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def clean_synonym(term):
    if term is None:
        return ""

    term = str(term).strip()

    term = re.sub(r"\s+", " ", term)

    return term


def unique_preserve_order(values):
    seen = set()
    output = []

    for value in values:

        if not value:
            continue

        key = value.lower()

        if key not in seen:
            seen.add(key)
            output.append(value)

    return output

print("=" * 80)
print("CITE MeSH ONTOLOGY BUILDER")
print("=" * 80)

if MESH_XML.exists():

    print("\nMeSH XML already exists.")
    print(f"Using: {MESH_XML}")

else:

    print("\nDownloading official 2026 MeSH descriptor data...")
    print(MESH_URL)

    response = requests.get(
        MESH_URL,
        timeout=120
    )

    response.raise_for_status()

    MESH_XML.write_bytes(response.content)

    print("MeSH downloaded.")

print("\nParsing MeSH...")

tree = ET.parse(MESH_XML)
root = tree.getroot()

records = []
lookup_records = []

descriptor_count = 0

for descriptor in root.findall(".//DescriptorRecord"):

    descriptor_count += 1

    descriptor_ui = descriptor.findtext("DescriptorUI", default="")

    descriptor_name = descriptor.findtext(
        "./DescriptorName/String",
        default=""
    )

    scope_note = descriptor.findtext(
        "./Annotation",
        default=""
    )

    pharmacological_action = descriptor.findtext(
        "./PharmacologicalActionList"
    )

    synonyms = []

    for concept in descriptor.findall(
        "./ConceptList/Concept"
    ):

        for term in concept.findall(
            "./TermList/Term"
        ):

            term_text = term.findtext(
                "String",
                default=""
            )

            term_text = clean_synonym(term_text)

            if term_text:
                synonyms.append(term_text)

    synonyms = unique_preserve_order(synonyms)

    tree_numbers = []

    for tree_number in descriptor.findall(
        "./TreeNumberList/TreeNumber"
    ):

        value = tree_number.text

        if value:
            tree_numbers.append(value.strip())

    tree_numbers = unique_preserve_order(
        tree_numbers
    )

    qualifiers = []

    qualifier_list = descriptor.find(
        "./AllowableQualifiersList"
    )

    if qualifier_list is not None:

        for qualifier in qualifier_list.findall(
            "./AllowableQualifier"
        ):

            qualifier_ui = qualifier.findtext(
                "QualifierReferredTo/QualifierUI",
                default=""
            )

            qualifier_name = qualifier.findtext(
                "QualifierReferredTo/QualifierName/String",
                default=""
            )

            if qualifier_ui or qualifier_name:

                qualifiers.append(
                    f"{qualifier_ui}:{qualifier_name}"
                )

    qualifiers = unique_preserve_order(
        qualifiers
    )

    record = {
        "mesh_id": descriptor_ui,
        "preferred_name": descriptor_name,
        "normalized_name": normalize_text(
            descriptor_name
        ),
        "synonyms": " | ".join(synonyms),
        "tree_numbers": " | ".join(tree_numbers),
        "scope_note": scope_note,
        "allowable_qualifiers": " | ".join(
            qualifiers
        ),
        "source": "NLM MeSH 2026",
    }

    records.append(record)

    if descriptor_name:

        lookup_records.append({
            "term": descriptor_name,
            "normalized_term": normalize_text(
                descriptor_name
            ),
            "mesh_id": descriptor_ui,
            "preferred_name": descriptor_name,
            "match_type": "PREFERRED_TERM",
            "source": "MeSH",
        })

    for synonym in synonyms:

        if not synonym:
            continue

        # Don't duplicate preferred term
        if normalize_text(synonym) == normalize_text(
            descriptor_name
        ):
            continue

        lookup_records.append({
            "term": synonym,
            "normalized_term": normalize_text(
                synonym
            ),
            "mesh_id": descriptor_ui,
            "preferred_name": descriptor_name,
            "match_type": "ENTRY_TERM",
            "source": "MeSH",
        })

mesh_df = pd.DataFrame(records)

lookup_df = pd.DataFrame(
    lookup_records
)

# Remove exact duplicate lookup records

lookup_df = lookup_df.drop_duplicates(
    subset=[
        "normalized_term",
        "mesh_id",
        "match_type",
    ]
)

mesh_df.to_csv(
    OUTPUT_ONTOLOGY,
    index=False
)

lookup_df.to_csv(
    OUTPUT_LOOKUP,
    index=False
)

print("\n" + "=" * 80)
print("COMPLETE")
print("=" * 80)

print(
    f"\nMeSH descriptors: {len(mesh_df):,}"
)

print(
    f"Searchable terms: {len(lookup_df):,}"
)

print(
    f"\nOntology:"
    f"\n{OUTPUT_ONTOLOGY}"
)

print(
    f"\nTerm lookup:"
    f"\n{OUTPUT_LOOKUP}"
)

print("\nMeSH terminology is ready for CITE.")
