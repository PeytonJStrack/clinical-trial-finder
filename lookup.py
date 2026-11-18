import requests


def search_facility(name, city, state, postal_code=""):
    url = "https://nominatim.openstreetmap.org/search"

    params = {
        "q": f"{name}, {city}, {state}",
        "format": "jsonv2",
        "limit": 5,
        "addressdetails": 1,
    }
    
    headers = {
        "User-Agent": "CITE-County-Explorer/1.0"
    }

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


facilities = [
    (
        "Sibley Memorial Hospital",
        "Washington",
        "DC",
        "20016",
    ),
    (
        "MedStar Georgetown University Hospital",
        "Washington",
        "DC",
        "20007",
    ),
    (
        "Children's National Hospital",
        "Washington",
        "DC",
        "20010",
    ),
    (
        "Emerson Clinical Research Institute",
        "Washington",
        "DC",
        "",
    ),
    (
        "TG Therapeutics Investigational Trial Site",
        "Washington",
        "DC",
        "",
    ),
]


print("=" * 70)
print("DIRECT FACILITY LOOKUP TEST")
print("=" * 70)

for name, city, state, postal_code in facilities:

    print()
    print("=" * 70)
    print(name)
    print("=" * 70)

    try:
        results = search_facility(
            name,
            city,
            state,
            postal_code,
        )

        print(f"Results found: {len(results)}")
        print()

        for i, result in enumerate(results, start=1):
            print(f"RESULT {i}")
            print("-" * 70)
            print("Name:", result.get("display_name"))
            print("Latitude:", result.get("lat"))
            print("Longitude:", result.get("lon"))
            print("Type:", result.get("type"))
            print("Category:", result.get("category"))

    except Exception as error:
        print("ERROR:", error)

print()
print("=" * 70)
print("TEST COMPLETE")
print("=" * 70)