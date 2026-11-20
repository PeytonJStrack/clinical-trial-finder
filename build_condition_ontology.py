from pathlib import Path
import gzip
import re
import shutil
import urllib.request
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent

ONTOLOGY_DIR = BASE_DIR / "medical_ontology"

DO_FILE = ONTOLOGY_DIR / "doid.obo"

OUTPUT_FILE = (
    BASE_DIR /
    "cite_medical_ontology.csv"
)

# Disease Ontology official persistent release location.
DO_URL = (
    "https://purl.obolibrary.org/obo/doid.obo"
)

def normalize_text(text):

    if not text:
        return ""

    text = str(text).lower().strip()

    text = text.replace(
        "–",
        "-"
    )

    text = text.replace(
        "—",
        "-"
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text


def unquote(value):

    value = value.strip()

    if value.startswith('"'):

        value = value[1:]

    if '"' in value:

        value = value.split(
            '"',
            1
        )[0]

    return value.strip()

def download_disease_ontology():

    ONTOLOGY_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    if DO_FILE.exists():

        print(
            f"\nDisease Ontology already exists:"
            f"\n{DO_FILE}"
        )

        return

    print(
        "\nDownloading Disease Ontology..."
    )

    temp_file = (
        ONTOLOGY_DIR /
        "doid.obo.tmp"
    )

    urllib.request.urlretrieve(
        DO_URL,
        temp_file
    )

    shutil.move(
        temp_file,
        DO_FILE
    )

    print(
        "Disease Ontology downloaded."
    )

def parse_obo():

    print(
        "\nParsing Disease Ontology..."
    )

    records = []

    current = None

    with open(
        DO_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        for raw_line in file:
            line = raw_line.strip()

            if line == "[Term]":
                if current:
                    records.append(
                        current
                    )

                current = {
                    "doid": "",
                    "name": "",
                    "definition": "",
                    "synonyms": [],
                    "parents": [],
                    "xrefs": [],
                    "is_obsolete": False,
                }

                continue

            if current is None:
                continue

            if line.startswith("id:"):
                current[
                    "doid"
                ] = line[
                    3:
                ].strip()

            elif line.startswith("name:"):
                current[
                    "name"
                ] = line[
                    5:
                ].strip()

            elif line.startswith(
                "def:"
            ):
                current[
                    "definition"
                ] = unquote(
                    line[4:].strip()
                )

            elif line.startswith(
                "synonym:"
            ):

                synonym = unquote(
                    line[
                        len("synonym:"):
                    ].strip()
                )

                if synonym:

                    current[
                        "synonyms"
                    ].append(
                        synonym
                    )

            elif line.startswith(
                "is_a:"
            ):

                parent = line[
                    len("is_a:"):
                ].strip()

                parent = parent.split(
                    "!",
                    1
                )[0].strip()

                current[
                    "parents"
                ].append(
                    parent
                )

            elif line.startswith(
                "xref:"
            ):

                xref = line[
                    len("xref:"):
                ].strip()

                current[
                    "xrefs"
                ].append(
                    xref
                )

            elif line == (
                "is_obsolete: true"
            ):

                current[
                    "is_obsolete"
                ] = True

        # Last record.
        if current:

            records.append(
                current
            )

    return records

def build_dataframe(records):

    rows = []

    for record in records:

        if record[
            "is_obsolete"
        ]:

            continue

        name = record[
            "name"
        ]

        synonyms = record[
            "synonyms"
        ]

        all_terms = [
            name
        ] + synonyms

        all_terms = list(
            dict.fromkeys(
                all_terms
            )
        )

        normalized_terms = [
            normalize_text(
                term
            )
            for term in all_terms
        ]

        rows.append({

            "doid":
                record[
                    "doid"
                ],

            "preferred_name":
                name,

            "normalized_name":
                normalize_text(
                    name
                ),

            "synonyms":
                "|".join(
                    all_terms
                ),

            "normalized_terms":
                "|".join(
                    normalized_terms
                ),

            "definition":
                record[
                    "definition"
                ],

            "parents":
                "|".join(
                    record[
                        "parents"
                    ]
                ),

            "xrefs":
                "|".join(
                    record[
                        "xrefs"
                    ]
                ),

            "is_obsolete":
                False,

        })

    return pd.DataFrame(
        rows
    )

def build_term_lookup(ontology):

    rows = []

    for _, row in ontology.iterrows():

        terms = row[
            "normalized_terms"
        ].split("|")

        for term in terms:

            if not term:

                continue

            rows.append({

                "normalized_term":
                    term,

                "doid":
                    row[
                        "doid"
                    ],

                "preferred_name":
                    row[
                        "preferred_name"
                    ],

                "term_type":
                    (
                        "preferred"
                        if term ==
                        row[
                            "normalized_name"
                        ]
                        else
                        "synonym"
                    ),

            })

    return pd.DataFrame(
        rows
    )

def main():

    print("=" * 80)
    print("CITE MEDICAL ONTOLOGY BUILDER")
    print("=" * 80)

    download_disease_ontology()

    records = parse_obo()

    print(
        f"\nParsed "
        f"{len(records):,} ontology records."
    )

    ontology = build_dataframe(
        records
    )

    print(
        f"Active disease concepts: "
        f"{len(ontology):,}"
    )

    ontology.to_csv(
        OUTPUT_FILE,
        index=False
    )

    lookup_file = (
        BASE_DIR /
        "cite_medical_term_lookup.csv"
    )

    lookup = build_term_lookup(
        ontology
    )

    lookup.to_csv(
        lookup_file,
        index=False
    )

    print(
        f"\nOntology:"
        f"\n{OUTPUT_FILE}"
    )

    print(
        f"\nTerm lookup:"
        f"\n{lookup_file}"
    )

    print(
        f"\nSearchable terms: "
        f"{len(lookup):,}"
    )

    print(
        "\nCOMPLETE."
    )


if __name__ == "__main__":

    main()
