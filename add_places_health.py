import requests
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
COUNTY_FILE = BASE_DIR / "cite_county_explorer.csv"
PLACES_CACHE = BASE_DIR / "cite_places_health.csv"

PLACES_API = "https://data.cdc.gov/resource/swc5-untb.json"


def get_places_health():
    params = {
        "$select": "locationid,measureid,data_value,year,datavaluetypeid",
        "$where": (
            "datavaluetypeid='AgeAdjPrv' "
            "AND measureid in('GHLTH','PHLTH','MHLTH')"
        ),
        "$limit": "20000",
    }

    response = requests.get(PLACES_API, params=params, timeout=(10, 120))
    response.raise_for_status()
    rows = response.json()
    places = pd.DataFrame(rows)

    if places.empty:
        raise ValueError("CDC PLACES returned no records.")

    places["locationid"] = places["locationid"].astype(str).str.zfill(5)
    places["data_value"] = pd.to_numeric(places["data_value"], errors="coerce")
    places["year"] = pd.to_numeric(places["year"], errors="coerce")

    places = (
        places.sort_values("year", ascending=False)
        .drop_duplicates(["locationid", "measureid"])
    )

    places = places.pivot(
        index="locationid",
        columns="measureid",
        values="data_value",
    ).reset_index()

    places = places.rename(
        columns={
            "locationid": "geoid",
            "GHLTH": "fair_poor_health",
            "PHLTH": "physical_distress",
            "MHLTH": "mental_distress",
        }
    )

    places["places_release"] = "2025"
    places["places_measure_year"] = 2023
    return places


def main():
    county = pd.read_csv(COUNTY_FILE, dtype={"state_fips": str, "county_fips": str})
    county["state_fips"] = county["state_fips"].str.zfill(2)
    county["county_fips"] = county["county_fips"].str.zfill(3)
    county["geoid"] = county["state_fips"] + county["county_fips"]

    places = get_places_health()
    places.to_csv(PLACES_CACHE, index=False)

    health_columns = [
        "fair_poor_health",
        "physical_distress",
        "mental_distress",
        "places_release",
        "places_measure_year",
    ]

    county = county.drop(columns=health_columns, errors="ignore")
    county = county.merge(places, on="geoid", how="left")
    county.to_csv(COUNTY_FILE, index=False)

    available = int(county["fair_poor_health"].notna().sum())
    print(f"CDC PLACES health data added to {COUNTY_FILE.name}.")
    print(f"Health estimates available for {available:,} counties.")
    print(f"Saved source cache: {PLACES_CACHE.name}")


if __name__ == "__main__":
    main()
