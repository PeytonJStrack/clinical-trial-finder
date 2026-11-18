import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("CENSUS_API_KEY")

def get_studies(query_location, page_size = 1000):
    url = "https://clinicaltrials.gov/api/v2/studies"

    studies = []
    next_page_token = None

    while True:

        params = {"query.locn": query_location, "filter.overallStatus": "RECRUITING,NOT_YET_RECRUITING", "pageSize": page_size, "format": "json"}

        if next_page_token:
            params["pageToken"] = next_page_token

        for attempt in range(3):
            try:
                response = requests.get(url, params = params, timeout = (10, 120))
                response.raise_for_status()
                break

            except requests.exceptions.ReadTimeout:
                print(f"Request timed out " f"(attempt {attempt + 1}/3).")
                if attempt == 2:
                    raise
                print("Retrying...")

        data = response.json()

        studies.extend(data.get("studies", []))

        print(f"Retrieved {len(studies)} active studies...")

        next_page_token = data.get("nextPageToken")

        if not next_page_token:
            break

    return studies

def get_unique_trial_sites(locations_df):
    unique_sites = locations_df.dropna(subset = ["latitude", "longitude"]).drop_duplicates(subset = ["nct_id", "latitude", "longitude"]).copy()

    return unique_sites

def extract_study_information(studies):
    study_information = []

    for study in studies:
        protocol = study.get("protocolSection", {})

        identification = protocol.get("identificationModule", {})
        nct_id = identification.get("nctId")
        title = identification.get("briefTitle")


        status_module = protocol.get("statusModule", {})
        status = status_module.get("overallStatus")

        conditions_module = protocol.get("conditionsModule", {})
        conditions = conditions_module.get("conditions", [])

        sponsor_module = protocol.get("sponsorCollaboratorsModule", {})

        lead_sponsor = sponsor_module.get("leadSponsor", {})
        sponsor = lead_sponsor.get("name")

        design_module = protocol.get("designModule", {})
        study_type = design_module.get("studyType")
        phases = design_module.get("phases", [])

        enrollment_info = design_module.get("enrollmentInfo", {})
        enrollment = enrollment_info.get("count")

        eligibility_module = protocol.get("eligibilityModule", {})
        sex = eligibility_module.get("sex")
        minimum_age = eligibility_module.get("minimumAge")
        maximum_age = eligibility_module.get("maximumAge")

        study_information.append({
            "nct_id": nct_id,
            "title": title,
            "status": status,
            "conditions": conditions,
            "sponsor": sponsor,
            "study_type": study_type,
            "phase": phases,
            "enrollment": enrollment,
            "sex": sex,
            "minimum_age": minimum_age,
            "maximum_age": maximum_age
        })

    return pd.DataFrame(study_information)


def extract_locations(studies):
    locations = []

    for study in studies:
        protocol = study.get("protocolSection", {})

        identification = protocol.get("identificationModule", {})
        nct_id = identification.get("nctId")

        contacts_locations = protocol.get("contactsLocationsModule", {})

        study_locations = contacts_locations.get("locations", [])

        for location in study_locations:
            geo_point = location.get("geoPoint", {})
            locations.append({
                "nct_id": nct_id,
                "facility": location.get("facility"),
                "city": location.get("city"),
                "state": location.get("state"),
                "zip": location.get("zip"),
                "country": location.get("country"),
                "latitude": geo_point.get("lat"),
                "longitude": geo_point.get("lon")
            })

    return pd.DataFrame(locations)


def get_county_from_coordinates(latitude, longitude):
    url = ("https://geocoding.geo.census.gov/""geocoder/geographies/coordinates")
    params = {"x": longitude, "y": latitude, "benchmark": "Public_AR_Current", "vintage": "Current_Current", "format": "json"}

    response = requests.get(url, params = params, timeout = 30)
    response.raise_for_status()
    data = response.json()
    geographies = data["result"]["geographies"]
    counties = geographies.get("Counties", [])
    if not counties:
        return None

    county = counties[0]

    return {"county": county["NAME"], "state_fips": county["STATE"], "county_fips": county["COUNTY"]}

CACHE_FILE = "geocoding_cache.csv"

def load_geocoding_cache():
    try:
        return pd.read_csv(CACHE_FILE)
    except FileNotFoundError:
        return pd.DataFrame(columns = ["latitude","longitude", "county", "state_fips", "county_fips"])

def save_geocoding_cache(cache_df):
    cache_df.to_csv(CACHE_FILE, index = False)

def geocode_sites_with_cache(sites_df):
    cache_df = load_geocoding_cache()

    county_lookup = {}
    for _, row in cache_df.iterrows():
        county_lookup[(row["latitude"], row["longitude"])] = {"county": row["county"], "state_fips": row["state_fips"], "county_fips": row["county_fips"]}

    unique_coordinates = (sites_df[["latitude", "longitude"]].dropna().drop_duplicates())
    sites_df = sites_df.copy()

    for _, row in unique_coordinates.iterrows():
        latitude = row["latitude"]
        longitude = row["longitude"]
        coordinate = (latitude, longitude)

        if coordinate in county_lookup:
            continue

        try:

            result = get_county_from_coordinates(latitude, longitude)
            result = result or {}

        except requests.exceptions.RequestException as error:
            print(f"FAILED: {latitude}, {longitude}")
            print(f"Reason: {error}")

            continue

        county_lookup[coordinate] = result

        new_cache_row = pd.DataFrame([{
            "latitude": latitude,
            "longitude": longitude,
            "county": result.get("county"),
            "state_fips": result.get("state_fips"),
            "county_fips": result.get("county_fips")}])

        cache_df = pd.concat(
            [cache_df, new_cache_row], ignore_index = True)
        save_geocoding_cache(cache_df)


    sites_df["county"] = sites_df.apply(lambda row: county_lookup.get((row["latitude"],row["longitude"]), {}).get("county"), axis = 1)

    sites_df["state_fips"] = sites_df.apply(
        lambda row: county_lookup.get((row["latitude"], row["longitude"]), {}).get("state_fips"), axis = 1)

    sites_df["county_fips"] = sites_df.apply(lambda row: county_lookup.get((row["latitude"], row["longitude"]), {}).get("county_fips"), axis = 1)

    return sites_df

query_location = "United States"
studies = get_studies(query_location, page_size=1000)
studies_df = extract_study_information(studies)
locations_df = extract_locations(studies)
us_active_locations_df = locations_df[locations_df["country"] == "United States"].copy()
unique_sites_df = get_unique_trial_sites(us_active_locations_df)

locations_with_counties = geocode_sites_with_cache(unique_sites_df)

trial_locations = locations_with_counties.dropna(subset = ["state_fips", "county_fips"]).copy()

trial_locations["state_fips"] = (trial_locations["state_fips"].astype(str).str.zfill(2))

trial_locations["county_fips"] = (trial_locations["county_fips"].astype(str).str.zfill(3))

active_trial_counts = (trial_locations.groupby(["state_fips", "county_fips"])["nct_id"].nunique().reset_index(name = "active_trial_count"))

trial_site_counts = (trial_locations.groupby(["state_fips", "county_fips"]).size().reset_index(name = "active_trial_site_records"))

trial_county_data = active_trial_counts.merge(trial_site_counts, on = ["state_fips", "county_fips"], how = "outer")

TRIAL_SITE_OUTPUT_FILE = "cite_trial_sites.csv"
trial_locations.to_csv(TRIAL_SITE_OUTPUT_FILE, index=  False)

def get_all_county_profiles():
    url = ("https://api.census.gov/data/2024/""acs/acs5/profile")

    params = {"get": ("NAME," "DP05_0001E," "DP03_0062E," "DP03_0128PE," "DP02_0154PE," "DP04_0058PE"), "for": "county:*", "in": "state:*","key": API_KEY}

    response = requests.get(url, params = params, timeout = (10, 120))
    response.raise_for_status()
    data = response.json()
    df = pd.DataFrame(data[1:], columns = data[0])
    
    df = df.rename(
        columns={
            "NAME": "county_name",
            "DP05_0001E": "population",
            "DP03_0062E": "median_income",
            "DP03_0128PE": "poverty_rate",
            "DP02_0154PE": "broadband",
            "DP04_0058PE": "no_vehicle"})

    df["median_income"] = pd.to_numeric(
        df["median_income"], errors="coerce"
    ).replace(-666666666, pd.NA)

    df["state_fips"] = (df["state"].astype(str).str.zfill(2))
    df["county_fips"] = (df["county"].astype(str).str.zfill(3))

    numeric_columns = ["population", "median_income", "poverty_rate", "broadband", "no_vehicle"]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors = "coerce")

    #Fixing the Puerto Rico Broadband issues
    pr_params = {"get": "DP02PR_0154PE", "for": "county:*", "in": "state:72", "key": API_KEY}
    pr_response = requests.get(url, params = pr_params, timeout = (10, 120))
    pr_response.raise_for_status()
    pr_data = pr_response.json()
    pr_df = pd.DataFrame(pr_data[1:], columns = pr_data[0])
    pr_df = pr_df.rename(columns = {"DP02PR_0154PE": "broadband"})

    pr_df["state_fips"] = (pr_df["state"].astype(str).str.zfill(2))
    pr_df["county_fips"] = (pr_df["county"].astype(str).str.zfill(3))
    pr_df["broadband"] = pd.to_numeric(pr_df["broadband"], errors = "coerce")

    pr_lookup = (pr_df[["state_fips", "county_fips", "broadband"]].set_index(["state_fips", "county_fips"])["broadband"])
    pr_mask = df["state_fips"].eq("72")
    df.loc[pr_mask, "broadband"] = [
        pr_lookup.get((state_fips, county_fips))
        for state_fips, county_fips in zip(df.loc[pr_mask, "state_fips"], df.loc[pr_mask, "county_fips"])]
    df = df[["county_name", "state_fips", "county_fips", "population", "median_income", "poverty_rate", "broadband", "no_vehicle"]]

    return df

def get_places_health():
    url = "https://data.cdc.gov/resource/swc5-untb.json"
    params = {
        "$select": "locationid,measureid,data_value,year,datavaluetypeid",
        "$where": (
            "datavaluetypeid='AgeAdjPrv' "
            "AND measureid in('GHLTH','PHLTH','MHLTH')"
        ),
        "$limit": "20000",
    }

    response = requests.get(url, params=params, timeout=(10, 120))
    response.raise_for_status()
    data = response.json()

    places = pd.DataFrame(data)
    if places.empty:
        raise ValueError("CDC PLACES returned no health-status records.")

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

    print(f"CDC PLACES health data: {len(places):,} counties")
    return places

census_county_data = get_all_county_profiles()

county_data = census_county_data.merge(
    trial_county_data,
    on=["state_fips", "county_fips"],
    how="left",
)
county_data["active_trial_count"] = (
    county_data["active_trial_count"].fillna(0).astype(int)
)
county_data["active_trial_site_records"] = (
    county_data["active_trial_site_records"].fillna(0).astype(int)
)

places_health = get_places_health()
county_data["geoid"] = county_data["state_fips"] + county_data["county_fips"]
county_data = county_data.merge(places_health, on="geoid", how="left")

county_data = county_data[
    [
        "county_name",
        "state_fips",
        "county_fips",
        "geoid",
        "population",
        "median_income",
        "poverty_rate",
        "broadband",
        "no_vehicle",
        "active_trial_count",
        "active_trial_site_records",
        "fair_poor_health",
        "physical_distress",
        "mental_distress",
        "places_release",
        "places_measure_year",
    ]
]

OUTPUT_FILE = "cite_county_explorer.csv"
county_data.to_csv(OUTPUT_FILE, index = False)