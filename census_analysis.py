import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("CENSUS_API_KEY")

def get_counties():
    url = "https://api.census.gov/data/2024/acs/acs5/profile"

    params = {"get": "NAME", "for": "county:*", "in": "state:*", "key": API_KEY}

    response = requests.get(url, params = params)
    response.raise_for_status()
    data = response.json()

    df = pd.DataFrame(data[1:], columns = data[0])

    df = df.rename(columns = {"NAME": "county_full", "state": "state_fips", "county": "county_fips"})

    df[["county", "state"]] = df["county_full"].str.rsplit(", ", n = 1, expand = True)
    df = df[["state", "county", "state_fips", "county_fips"]]

    return df

def find_county(counties, state_name, county_name):
    match = counties[(counties["state"] == state_name) & (counties["county"] == county_name)]

    if match.empty:
        raise ValueError("County not found.")

    return match.iloc[0]["state_fips"], match.iloc[0]["county_fips"]

def get_county_profile(state_fips, county_fips):
    url = "https://api.census.gov/data/2024/acs/acs5/profile"

    params = {
        "get": (
            "NAME,"
            "DP05_0001E,"
            "DP03_0062E,"
            "DP03_0128PE,"
            "DP02_0154PE,"
            "DP04_0058PE"),
        "for": f"county:{county_fips}",
        "in": f"state:{state_fips}",
        "key": API_KEY}

    response = requests.get(url, params = params, timeout = (10, 120))
    response.raise_for_status()

    data = response.json()

    df = pd.DataFrame(data[1:], columns = data[0])

    df = df.rename(columns = {
        "NAME": "county",
        "DP05_0001E": "population",
        "DP03_0062E": "median_income",
        "DP03_0128PE": "poverty_rate",
        "DP02_0154PE": "broadband",
        "DP04_0058PE": "no_vehicle"
    })

    numeric_columns = ["population", "median_income", "poverty_rate", "broadband", "no_vehicle"]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column])

    return df
