from pathlib import Path
from urllib.parse import quote
from geopy.geocoders import Nominatim
from html import escape
import json
import pandas as pd
import requests
from ipyleaflet import GeoJSON, Map, Marker, Popup
from ipywidgets import HTML
from shiny import App, reactive, render, ui
from shinywidgets import output_widget, render_widget
from route_accessibility import get_trial_accessibility
BASE_DIR = Path(__file__).resolve().parent
COUNTY_FILE_CANDIDATES = [
    BASE_DIR / "cite_county_explorer.csv",
    BASE_DIR / "cite_county_explorer(2).csv",
]
COUNTY_FILE = next((path for path in COUNTY_FILE_CANDIDATES if path.exists()), COUNTY_FILE_CANDIDATES[-1])
TRIAL_FILE_CANDIDATES = [
    BASE_DIR / "cite_trial_sites_verified.csv",
    BASE_DIR / "cite_trial_sites_final.csv",
    BASE_DIR / "cite_trial_sites_final(5).csv",
    BASE_DIR / "cite_trial_sites.csv",
]
TRIAL_FILE = None
for _candidate in TRIAL_FILE_CANDIDATES:
    if not _candidate.exists():
        continue
    try:
        _columns = pd.read_csv(_candidate, nrows=0).columns
    except Exception:
        continue
    required_location_columns = {
        "facility_address",
        "facility_match_score",
        "resolved_latitude",
        "resolved_longitude",
    }
    if required_location_columns.issubset(set(_columns)):
        TRIAL_FILE = _candidate
        break
if TRIAL_FILE is None:
    TRIAL_FILE = next(
        (path for path in TRIAL_FILE_CANDIDATES if path.exists()),
        TRIAL_FILE_CANDIDATES[-1],
    )
TRIAL_METADATA_CANDIDATES = [
    BASE_DIR / "trial_metadata.csv",
    BASE_DIR / "cite_trial_metadata.csv",
    BASE_DIR / "cite_trial_metadata(2).csv",
    BASE_DIR / "trial_metadata(1).csv",
]
TRIAL_METADATA_FILE = next((path for path in TRIAL_METADATA_CANDIDATES if path.exists()), TRIAL_METADATA_CANDIDATES[-1])
county_data = pd.read_csv(COUNTY_FILE)
trial_sites = pd.read_csv(TRIAL_FILE, low_memory=False)
trial_metadata = pd.read_csv(TRIAL_METADATA_FILE) if TRIAL_METADATA_FILE.exists() else pd.DataFrame()
if "nct_id" in trial_metadata.columns:
    trial_metadata["nct_id"] = trial_metadata["nct_id"].astype(str).str.strip()
def normalize_fips(frame):
    for column, width in (("state_fips", 2), ("county_fips", 3)):
        if column in frame.columns:
            frame[column] = (
                frame[column]
                .astype(str)
                .str.replace(".0", "", regex=False)
                .str.zfill(width)
            )
    return frame
county_data = normalize_fips(county_data)
trial_sites = normalize_fips(trial_sites)
if "nct_id" in trial_sites.columns:
    trial_sites["nct_id"] = trial_sites["nct_id"].astype(str).str.strip()
if not trial_metadata.empty and "nct_id" in trial_metadata.columns and "nct_id" in trial_sites.columns:
    metadata_cols = [c for c in ["nct_id", "brief_title", "official_title", "condition", "conditions", "recruitment_status", "overall_status", "eligibility", "sex", "minimum_age", "maximum_age", "standard_age", "study_type", "enrollment_count"] if c in trial_metadata.columns]
    trial_sites = trial_sites.merge(trial_metadata[metadata_cols].drop_duplicates("nct_id"), on="nct_id", how="left")
for column in ("latitude", "longitude", "resolved_latitude", "resolved_longitude", "facility_match_score"):
    if column in trial_sites.columns:
        trial_sites[column] = pd.to_numeric(trial_sites[column], errors="coerce")
def normalize_zip_value(value):
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[:5]
def extract_address_zip(value):
    if pd.isna(value):
        return ""
    import re
    matches = re.findall(r"\b(\d{5})(?:-\d{4})?\b", str(value))
    return matches[-1] if matches else ""
def has_street_address(value):
    if pd.isna(value):
        return False
    import re
    return bool(re.search(r"(?:^|,\s*)\d{1,6}[A-Za-z]?(?:-\d{1,6})?(?:,\s|\s)", str(value)))
def is_generic_facility(value):
    import re
    name = "" if pd.isna(value) else str(value).strip().upper()
    generic_exact = {
        "CLINICAL TRIAL SITE", "CLINICAL SITE", "STUDY SITE",
        "TRIAL SITE", "RESEARCH SITE", "INVESTIGATIONAL SITE",
        "LOCAL SITE", "SITE", "UNKNOWN", "UNKNOWN SITE",
        "UNKNOWN LOCATION", "UNNAMED SITE", "UNNAMED FACILITY",
        "NOT APPLICABLE", "N A", "N/A", "NA", "NONE", "NULL",
    }
    return name in generic_exact or bool(re.match(r"^LOCAL INSTITUTION(?:[- ]?\d*)?$", name))
def valid_coordinate_pair(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return (-90 <= lat <= 90) and (-180 <= lon <= 180)
if "facility_address" in trial_sites.columns:
    source_zips = (
        trial_sites["zip"].apply(normalize_zip_value)
        if "zip" in trial_sites.columns
        else pd.Series("", index=trial_sites.index)
    )
    address_zips = trial_sites["facility_address"].apply(extract_address_zip)
    score_pass = (
        pd.to_numeric(
            trial_sites.get("facility_match_score"),
            errors="coerce",
        ).fillna(-1) >= 90
    )
    zip_pass = (
        source_zips.ne("")
        & address_zips.ne("")
        & source_zips.eq(address_zips)
    )
    address_pass = trial_sites["facility_address"].apply(has_street_address)
    non_generic_pass = ~trial_sites["facility"].apply(is_generic_facility)
    coordinate_pass = pd.Series(
        [
            valid_coordinate_pair(lat, lon)
            for lat, lon in zip(
                trial_sites.get(
                    "resolved_latitude",
                    pd.Series(index=trial_sites.index),
                ),
                trial_sites.get(
                    "resolved_longitude",
                    pd.Series(index=trial_sites.index),
                ),
            )
        ],
        index=trial_sites.index,
    )
    calculated_transit_ready = (
        score_pass
        & zip_pass
        & address_pass
        & non_generic_pass
        & coordinate_pass
    )
    if "transit_ready" in trial_sites.columns:
        authoritative = trial_sites["transit_ready"].fillna(False).astype(bool)
        trial_sites["transit_ready"] = authoritative | calculated_transit_ready
    else:
        trial_sites["transit_ready"] = calculated_transit_ready
else:
    trial_sites["transit_ready"] = False
trial_sites["map_latitude"] = trial_sites["resolved_latitude"].where(
    trial_sites["transit_ready"], pd.NA
)
trial_sites["map_longitude"] = trial_sites["resolved_longitude"].where(
    trial_sites["transit_ready"], pd.NA
)
county_data["state_name"] = (
    county_data["county_name"]
    .str.rsplit(", ", n=1)
    .str[-1]
)
county_data["county_only"] = (
    county_data["county_name"]
    .str.rsplit(", ", n=1)
    .str[0]
)
states = sorted(
    county_data["state_name"]
    .dropna()
    .unique()
)
default_state = "United States"
default_counties = []
default_county = None
def number(value):
    if pd.isna(value):
        return "—"
    return f"{value:,.0f}"
def currency(value):
    if pd.isna(value):
        return "—"
    return f"${value:,.0f}"
def percent(value):
    if value is None or pd.isna(value):
        return "—"
    return f"{value:.1f}%"
def health_bar_width(value):
    if value is None or pd.isna(value):
        return 0
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, value))
def get_column(row, names):
    for name in names:
        if name in row.index:
            return row[name]
    return None
def trial_sites_for_state(state):
    if not state or state == "United States":
        return pd.DataFrame()
    rows = county_data.loc[county_data["state_name"] == state, "state_fips"].dropna().unique()
    if len(rows) == 0:
        return pd.DataFrame()
    return trial_sites.loc[trial_sites["state_fips"] == str(rows[0]).zfill(2)].copy()
def trial_sites_for(row):
    if row is None:
        return pd.DataFrame()
    return trial_sites.loc[
        (trial_sites["state_fips"] == str(row["state_fips"]).zfill(2))
        & (trial_sites["county_fips"] == str(row["county_fips"]).zfill(3))
    ].copy()
def verified_map_sites(frame):
    if frame is None or frame.empty or "transit_ready" not in frame.columns:
        return pd.DataFrame()
    return frame.loc[frame["transit_ready"].fillna(False).astype(bool)].dropna(
        subset=["resolved_latitude", "resolved_longitude"]
    ).copy()
STATE_GEOJSON_URL = "https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/data/geojson/us-states.json"
COUNTY_GEOJSON_URL = "https://geopub.epa.gov/ArcGIS/rest/services/NEPmap/context/MapServer/5/query"
def load_state_boundaries():
    response = requests.get(STATE_GEOJSON_URL, timeout=20)
    response.raise_for_status()
    return response.json()
def normalize_county_feature_properties(geojson):
    for feature in geojson.get("features", []):
        props = feature.setdefault("properties", {})
        state = str(props.get("STATE_FIPS", "")).strip().replace(".0", "").zfill(2)
        county = str(
            props.get("CNTY_FIPS", props.get("COUNTY_FIPS", ""))
        ).strip().replace(".0", "").zfill(3)
        props["STATE_FIPS"] = state
        props["CNTY_FIPS"] = county
        props["FIPS"] = f"{state}{county}" if state and county else props.get("FIPS")
    return geojson
def load_county_boundaries(state_fips):
    response = requests.get(
        COUNTY_GEOJSON_URL,
        params={
            "where": f"STATE_FIPS = '{state_fips}'",
            "outFields": "NAME,STATE_FIPS,CNTY_FIPS,FIPS",
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
        },
        timeout=20,
    )
    response.raise_for_status()
    return normalize_county_feature_properties(response.json())
def geometry_bounds(geometry):
    points = []
    def walk(value):
        if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(x, (int, float)) for x in value[:2]):
            points.append((float(value[1]), float(value[0])))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
    walk(geometry.get("coordinates", []))
    if not points:
        return None
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]
def trial_status_series(frame):
    for column in ("recruitment_status", "overall_status", "status"):
        if column in frame.columns:
            return frame[column].fillna("").astype(str).str.strip().str.lower()
    return pd.Series("", index=frame.index)
def is_recruiting_status(value):
    value = str(value).strip().lower()
    return value in {"recruiting", "enrolling by invitation", "active, not recruiting"}
def is_not_yet_recruiting_status(value):
    return str(value).strip().lower() == "not yet recruiting"
def has_verified_public_location(frame):
    if frame.empty:
        return pd.Series(dtype=bool)
    if "transit_ready" in frame.columns:
        return frame["transit_ready"].fillna(False).astype(bool)
    status_ok = (
        frame["location_status"].fillna("").astype(str).str.upper().eq("VERIFIED")
        if "location_status" in frame.columns
        else pd.Series(False, index=frame.index)
    )
    address_ok = (
        frame["facility_address"].fillna("").astype(str).str.strip().ne("")
        if "facility_address" in frame.columns
        else pd.Series(False, index=frame.index)
    )
    lat_ok = pd.to_numeric(frame["resolved_latitude"], errors="coerce").notna() if "resolved_latitude" in frame.columns else pd.Series(False, index=frame.index)
    lon_ok = pd.to_numeric(frame["resolved_longitude"], errors="coerce").notna() if "resolved_longitude" in frame.columns else pd.Series(False, index=frame.index)
    return status_ok & address_ok & lat_ok & lon_ok
def location_category(frame):
    if frame.empty:
        return pd.Series([], dtype="object")
    status = trial_status_series(frame)
    verified = has_verified_public_location(frame)
    result = pd.Series("Address not publicly available", index=frame.index)
    result.loc[verified] = "Verified physical location"
    result.loc[status.map(is_not_yet_recruiting_status)] = "Not yet recruiting"
    return result

geolocator = Nominatim(
    user_agent="cite-clinical-trial-access-explorer"
)


def geocode_address(address):
    if not address or not address.strip():
        return None
    try:
        location = geolocator.geocode(address.strip(), timeout=10)
        if location is None:
            return None
        return {
            "latitude": float(location.latitude),
            "longitude": float(location.longitude),
            "address": location.address,
        }
    except Exception:
        return None


def google_maps_directions_url(
    origin_lat, origin_lon, destination_lat, destination_lon, mode="driving"
):
    origin = f"{float(origin_lat):.6f},{float(origin_lon):.6f}"
    destination = f"{float(destination_lat):.6f},{float(destination_lon):.6f}"
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={quote(origin)}"
        f"&destination={quote(destination)}"
        f"&travelmode={quote(mode)}"
    )


def haversine_distance(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, asin, sqrt

    earth_radius_miles = 3958.8
    lat1, lon1 = radians(float(lat1)), radians(float(lon1))
    lat2, lon2 = radians(float(lat2)), radians(float(lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = (
        sin(dlat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    )
    return 2 * earth_radius_miles * asin(sqrt(a))


def find_nearest_trial_site(latitude, longitude, sites):
    if sites.empty:
        return None

    sites = sites.dropna(
        subset=["map_latitude", "map_longitude"]
    ).copy()

    if "transit_ready" in sites.columns:
        sites = sites[
            sites["transit_ready"].fillna(False).astype(bool)
        ].copy()

    if sites.empty:
        return None

    sites["_distance_miles"] = sites.apply(
        lambda site: haversine_distance(
            latitude,
            longitude,
            site["map_latitude"],
            site["map_longitude"],
        ),
        axis=1,
    )
    return sites.loc[sites["_distance_miles"].idxmin()]

CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@600;700;800&display=swap');
:root {
    --cite-navy: #164A7A;
    --cite-blue: #1F5F94;
    --cite-blue-soft: #EAF3F8;
    --cite-orange: #D9823B;
    --cite-orange-soft: #FDF1E7;
    --ink: #18324B;
    --muted: #66788A;
    --light: #91A0AE;
    --border: #DDE5EC;
    --background: #F6F8FA;
    --white: #FFFFFF;
}
html {
    scroll-behavior: smooth;
}
body {
    background: var(--background);
    color: var(--ink);
    font-family: "DM Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    line-height: 1.5;
}
.container-fluid {
    max-width: 1260px;
    padding: 34px 34px 64px;
}
/* HERO */
.hero {
    position: relative;
    padding: 16px 0 34px;
    border-bottom: 1px solid var(--border);
}
.hero::before {
    content: "";
    display: block;
    width: 52px;
    height: 4px;
    border-radius: 999px;
    background: var(--cite-orange);
    margin-bottom: 22px;
}
.eyebrow,
.section-eyebrow,
.metric-label,
.signal-label {
    font-family: "DM Sans", sans-serif;
    text-transform: uppercase;
    letter-spacing: 0.13em;
    font-weight: 800;
}
.eyebrow {
    color: var(--cite-blue);
    font-size: 0.70rem;
    margin-bottom: 10px;
}
.hero-title {
    color: var(--cite-navy);
    font-family: "Plus Jakarta Sans", sans-serif;
    font-size: clamp(2.45rem, 5vw, 4.15rem);
    line-height: 1.02;
    letter-spacing: -0.055em;
    font-weight: 800;
    margin: 0;
}
.hero-title .accent {
    color: var(--cite-blue);
}
.hero-description {
    max-width: 790px;
    color: var(--muted);
    font-size: 1.02rem;
    line-height: 1.72;
    margin-top: 18px;
}
/* SECTION HEADERS */
.section {
    margin-top: 34px;
    margin-bottom: 17px;
}
.section-eyebrow {
    color: var(--cite-orange);
    font-size: 0.66rem;
    margin-bottom: 5px;
}
.section-title {
    color: var(--cite-navy);
    font-family: "Plus Jakarta Sans", sans-serif;
    font-size: 1.58rem;
    line-height: 1.2;
    font-weight: 700;
    letter-spacing: -0.025em;
}
.section-description {
    color: var(--muted);
    font-size: 0.89rem;
    line-height: 1.6;
    margin-top: 6px;
    max-width: 790px;
}
/* EXPLORER */
.explorer {
    background: var(--white);
    border: 1px solid var(--border);
    border-top: 3px solid var(--cite-blue);
    border-radius: 14px;
    padding: 23px 24px 21px;
    margin-top: 28px;
    box-shadow: 0 5px 18px rgba(24, 50, 75, 0.045);
}
.explorer .section-eyebrow {
    color: var(--cite-blue);
}
.trial-filter-row {
    display: grid;
    grid-template-columns: 2fr 3fr 2fr 2fr 3fr;
    gap: 14px;
    align-items: end;
    width: 100%;
}
.trial-filter-item {
    min-width: 0;
}
.trial-filter-item .shiny-input-container {
    width: 100%;
    margin: 0;
}
.trial-filter-row .form-control,
.trial-filter-row .form-select {
    width: 100%;
}
.explorer-label {
    color: var(--cite-navy);
    font-weight: 700;
    font-size: 0.82rem;
    margin-bottom: 8px;
}
/* COUNTY HEADER */
.county-header {
    margin-top: 31px;
    padding: 4px 0 0;
}
.county-name {
    color: var(--cite-navy);
    font-family: "Plus Jakarta Sans", sans-serif;
    font-size: 2.45rem;
    line-height: 1.05;
    font-weight: 800;
    letter-spacing: -0.045em;
}
.county-state {
    color: var(--muted);
    margin-top: 7px;
    font-size: 0.94rem;
}
/* CARDS */
.metric-card,
.signal-card,
.context-card {
    background: var(--white);
    border: 1px solid var(--border);
    border-radius: 13px;
    box-shadow: 0 4px 14px rgba(24, 50, 75, 0.035);
}
.metric-card {
    padding: 21px 22px;
    min-height: 148px;
    border-top: 3px solid var(--cite-blue);
}
.metric-label {
    color: var(--muted);
    font-size: 0.65rem;
}
.metric-value {
    color: var(--cite-navy);
    font-family: "Plus Jakarta Sans", sans-serif;
    font-size: 2.28rem;
    line-height: 1;
    font-weight: 800;
    letter-spacing: -0.045em;
    margin-top: 13px;
}
.metric-note {
    color: var(--light);
    font-size: 0.74rem;
    line-height: 1.4;
    margin-top: 9px;
}
.signal-card {
    padding: 22px;
    min-height: 188px;
    position: relative;
    overflow: hidden;
}
.signal-card.health-primary {
    border-top: 4px solid var(--cite-orange);
}
.signal-card.health-secondary {
    border-top: 4px solid var(--cite-blue);
}
.signal-card.health-tertiary {
    border-top: 4px solid #6F8FA8;
}
.health-spotlight {
    background: linear-gradient(135deg, #FFFFFF 0%, #F8FBFD 100%);
    border: 1px solid var(--border);
    border-left: 4px solid var(--cite-orange);
    border-radius: 14px;
    padding: 22px 24px;
    margin-bottom: 17px;
    box-shadow: 0 5px 18px rgba(24, 50, 75, 0.045);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 24px;
}
.health-spotlight-copy {
    max-width: 720px;
}
.health-spotlight-kicker {
    color: var(--cite-orange);
    font-size: 0.66rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.13em;
}
.health-spotlight-title {
    color: var(--cite-navy);
    font-family: "Plus Jakarta Sans", sans-serif;
    font-size: 1.12rem;
    font-weight: 800;
    margin-top: 5px;
}
.health-spotlight-text {
    color: var(--muted);
    font-size: 0.82rem;
    line-height: 1.55;
    margin-top: 5px;
}
.health-spotlight-badge {
    flex: 0 0 auto;
    background: var(--cite-orange-soft);
    border: 1px solid #F2D5BD;
    border-radius: 999px;
    padding: 9px 13px;
    color: var(--cite-orange);
    font-size: 0.68rem;
    font-weight: 800;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    white-space: nowrap;
}
.health-status {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0 0 12px 2px;
    color: var(--muted);
    font-size: 0.72rem;
}
.health-status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #5C9B73;
    flex: 0 0 auto;
}
.health-status-dot.unavailable {
    background: var(--cite-orange);
}
.health-status strong {
    color: var(--cite-navy);
}
.health-meter {
    height: 7px;
    background: #EDF2F5;
    border-radius: 999px;
    overflow: hidden;
    margin-top: 13px;
}
.health-meter-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--cite-orange), var(--cite-orange-soft));
    border-radius: 999px;
}
.health-secondary .health-meter-fill {
    background: linear-gradient(90deg, var(--cite-blue), #9FC3DD);
}
.health-tertiary .health-meter-fill {
    background: linear-gradient(90deg, #6F8FA8, #B8CBD9);
}
.health-footnote {
    color: var(--light);
    font-size: 0.68rem;
    margin-top: 8px;
}
.signal-label {
    color: var(--cite-blue);
    font-size: 0.65rem;
}
.signal-title {
    color: var(--cite-navy);
    font-family: "Plus Jakarta Sans", sans-serif;
    font-size: 0.98rem;
    font-weight: 700;
    margin-top: 9px;
}
.signal-value {
    color: var(--cite-navy);
    font-family: "Plus Jakarta Sans", sans-serif;
    font-size: 1.72rem;
    font-weight: 800;
    letter-spacing: -0.025em;
    margin-top: 8px;
}
.signal-description {
    color: var(--muted);
    font-size: 0.77rem;
    line-height: 1.48;
    margin-top: 4px;
}
.context-card {
    padding: 21px;
    min-height: 205px;
}
.context-title {
    color: var(--cite-navy);
    font-family: "Plus Jakarta Sans", sans-serif;
    font-size: 0.98rem;
    font-weight: 700;
    margin-bottom: 12px;
}
.context-row {
    display: flex;
    justify-content: space-between;
    gap: 15px;
    padding: 9px 0;
    border-bottom: 1px solid #EEF2F5;
    font-size: 0.81rem;
}
.context-row:last-child {
    border-bottom: none;
}
.context-label {
    color: var(--muted);
}
.context-value {
    color: var(--cite-navy);
    font-weight: 700;
    text-align: right;
}
/* MAP */
.leaflet-container {
    border-radius: 11px;
}
.card:has(.leaflet-container) {
    border: 1px solid var(--border);
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 5px 18px rgba(24, 50, 75, 0.045);
    background: var(--white);
}
/* SHINY CONTROLS */
.form-label {
    color: var(--cite-navy);
    font-size: 0.78rem;
    font-weight: 700;
}
.form-control {
    border-color: var(--border);
    border-radius: 9px;
    min-height: 42px;
    box-shadow: none;
}
.form-select {
    border-color: var(--border);
    border-radius: 9px;
    color: var(--ink);
    min-height: 42px;
    box-shadow: none;
}
.form-select:focus {
    border-color: var(--cite-blue);
    box-shadow: 0 0 0 0.18rem rgba(31, 95, 148, 0.12);
}

/* TRIAL ACCESSIBILITY */
.accessibility-results-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 17px;
    margin-top: 17px;
}

.accessibility-button {
    display: flex;
    align-items: flex-end;
}

.accessibility-button .btn {
    width: 100%;
    min-height: 42px;
}

.maps-link {
    display: inline-block;
    margin-top: 10px;
    color: var(--cite-blue);
    font-weight: 700;
    text-decoration: none;
    font-size: 0.76rem;
}

@media (max-width: 768px) {
    .accessibility-results-grid {
        grid-template-columns: 1fr;
    }
}

/* FOOTER */
.footer {
    border-top: 1px solid var(--border);
    margin-top: 45px;
    padding-top: 18px;
    color: var(--light);
    font-size: 0.70rem;
    letter-spacing: 0.01em;
}
/* ADDRESSLESS TRIAL SITES */
.addressless-section {
    margin-top: 38px;
}
.addressless-groups {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 17px;
    margin-top: 18px;
}
.addressless-group {
    background: var(--white);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 20px;
    box-shadow: 0 5px 18px rgba(24, 50, 75, 0.035);
}
.addressless-list {
    max-height: 320px;
    overflow-y: auto;
    padding-right: 8px;
    margin-top: 4px;
}
.addressless-subtitle {
    color: var(--cite-navy);
    font-family: "Plus Jakarta Sans", sans-serif;
    font-weight: 800;
    font-size: 0.95rem;
}
.addressless-count {
    color: var(--cite-blue);
    font-family: "Plus Jakarta Sans", sans-serif;
    font-size: 1.65rem;
    font-weight: 800;
    margin: 6px 0 12px;
}
.addressless-card {
    border-top: 1px solid var(--border);
    padding: 13px 0;
}
.addressless-card:first-of-type {
    border-top: none;
}
.addressless-facility,
.addressless-title {
    color: var(--cite-navy);
    font-weight: 700;
}
.addressless-location,
.addressless-meta {
    color: var(--muted);
    font-size: 0.75rem;
    margin-top: 3px;
}
.addressless-title {
    font-size: 0.78rem;
    margin-top: 7px;
}
.addressless-meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
}
.addressless-status {
    font-weight: 700;
}
.addressless-link {
    color: var(--cite-blue);
    font-weight: 700;
    text-decoration: none;
}
.addressless-empty {
    color: var(--light);
    font-size: 0.75rem;
    padding-top: 8px;
}
@media (max-width: 768px) {
    .addressless-groups {
        grid-template-columns: 1fr;
    }
    .addressless-list {
        max-height: 280px;
    }
}
/* RESPONSIVE */
@media (max-width: 768px) {
    .container-fluid {
        padding: 24px 18px 48px;
    }
    .hero {
        padding-top: 8px;
    }
    .county-name {
        font-size: 2rem;
    }
    .hero-title {
        font-size: 2.7rem;
    }
    .metric-value {
        font-size: 2rem;
    }
    .health-spotlight {
        align-items: flex-start;
        flex-direction: column;
    }
    .trial-filter-row {
        grid-template-columns: 1fr;
    }
}
"""
app_ui = ui.page_fluid(
    ui.tags.style(CSS),
    ui.div(
        ui.div(
            "CITE FOUNDATION · RESEARCH PROTOTYPE",
            class_="eyebrow",
        ),
        ui.HTML(
            """
            <div class="hero-title">
                Clinical Trial
                <span class="accent">Access Explorer</span>
            </div>
            """
        ),
        ui.div(
            "Explore how clinical trial availability intersects "
            "with the health and socioeconomic characteristics "
            "of communities across the United States.",
            class_="hero-description",
        ),
        class_="hero",
    ),
    ui.div(
        ui.div(
            ui.div(
                "EXPLORE",
                class_="section-eyebrow",
            ),
            ui.div(
                "Choose a community",
                class_="section-title",
            ),
            ui.div(
                "Select a state and county to investigate "
                "clinical trial availability and potential "
                "community-level access barriers.",
                class_="section-description",
            ),
        ),
        ui.layout_columns(
            ui.input_select(
                "state",
                "State",
                choices=["United States"] + states,
                selected=default_state,
            ),
            ui.input_select(
                "county",
                "County",
                choices=["All Counties"],
                selected="All Counties",
            ),
            col_widths=(5, 7),
        ),
        class_="explorer",
    ),
    ui.output_ui("county_header"),
    ui.div(
        ui.div(
            "COMMUNITY HEALTH NEED",
            class_="section-eyebrow",
        ),
        ui.div(
            "Start with the health landscape.",
            class_="section-title",
        ),
        ui.div(
            "Community health need is a core lens for understanding where "
            "clinical-trial navigation may matter most. These measures are "
            "shown separately so the dashboard does not turn different health "
            "dimensions into a single score.",
            class_="section-description",
        ),
        class_="section",
    ),
    ui.div(
        ui.div(
            ui.div(
                "HEALTH NEED SPOTLIGHT",
                class_="health-spotlight-kicker",
            ),
            ui.div(
                "A health-first view of the community.",
                class_="health-spotlight-title",
            ),
            ui.div(
                "These county-level estimates come from the CDC PLACES dataset and are "
                "prepared alongside the Census and clinical-trial data. They give "
                "us a health-first view before we look at trial availability or access context.",
                class_="health-spotlight-text",
            ),
            class_="health-spotlight-copy",
        ),
        ui.div(
            "CDC PLACES · 2025 release",
            class_="health-spotlight-badge",
        ),
        class_="health-spotlight",
    ),
    ui.output_ui("health_data_status"),
    ui.layout_columns(
        ui.output_ui("health_card_1"),
        ui.output_ui("health_card_2"),
        ui.output_ui("health_card_3"),
        col_widths=(4, 4, 4),
    ),
    ui.div(
        ui.div(
            "TRIAL FILTERS",
            class_="section-eyebrow",
        ),
        ui.div(
            "Narrow the clinical trial sites.",
            class_="section-title",
        ),
        ui.div(
            ui.div(
                ui.input_text("trial_condition", "Condition / ailment", placeholder="e.g., diabetes"),
                class_="trial-filter-item condition",
            ),
            ui.div(
                ui.input_select("trial_status", "Recruitment status", choices=["", "RECRUITING", "NOT_YET_RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION", "AVAILABLE"], selected=""),
                class_="trial-filter-item status",
            ),
            ui.div(
                ui.input_select("trial_sex", "Sex", choices=["", "FEMALE", "MALE"], selected=""),
                class_="trial-filter-item sex",
            ),
            ui.div(
                ui.input_select("trial_age", "Age group", choices=["", "Child", "Adult", "Older Adult"], selected=""),
                class_="trial-filter-item age",
            ),
            ui.div(
                ui.input_text("trial_eligibility", "Eligibility keyword", placeholder="e.g., BMI, smoker, pregnancy"),
                class_="trial-filter-item eligibility",
            ),
            class_="trial-filter-row",
        ),
        class_="explorer",
    ),
    ui.div(
        ui.div(
            "CLINICAL TRIAL LANDSCAPE",
            class_="section-eyebrow",
        ),
        ui.div(
            "What is available here?",
            class_="section-title",
        ),
        ui.div(
            "Current recruiting and not-yet-recruiting clinical "
            "trial activity associated with locations in the "
            "selected county.",
            class_="section-description",
        ),
        class_="section",
    ),
    ui.layout_columns(
        ui.output_ui("active_trials_card"),
        ui.output_ui("trial_sites_card"),
        ui.output_ui("facility_card"),
        col_widths=(4, 4, 4),
    ),
    ui.div(
        ui.div(
            "GEOGRAPHIC DISTRIBUTION",
            class_="section-eyebrow",
        ),
        ui.div(
            "Where are the trial sites?",
            class_="section-title",
        ),
        ui.div(
            "Only strictly verified public facility locations are shown on the physical map. Trial sites without a verified public address remain available in the addressless-site section below. Click a point to see the trials associated with that location.",
            class_="section-description",
        ),
        class_="section",
    ),
    ui.card(
        output_widget(
            "trial_map",
            height="480px",
        ),
        full_screen=True,
    ),
    ui.output_ui("addressless_trials_section"),

    ui.div(
        ui.div("TRIAL ACCESSIBILITY", class_="section-eyebrow"),
        ui.div(
            "Can someone realistically get there?",
            class_="section-title",
        ),
        ui.div(
            "Enter a starting address to find the nearest verified trial site, "
            "then compare driving and public-transit options.",
            class_="section-description",
        ),
        ui.layout_columns(
            ui.input_text(
                "accessibility_address",
                "Starting address",
                placeholder="Enter an address, city, state, or ZIP code",
            ),
            ui.div(
                ui.input_action_button(
                    "find_nearest_site",
                    "Find nearest trial site",
                    class_="btn-primary",
                ),
                class_="accessibility-button",
            ),
            col_widths=(8, 4),
        ),
        ui.layout_columns(
            ui.input_select(
                "accessibility_site",
                "Trial site",
                choices={"": "Select a trial site"},
                selected="",
            ),
            ui.div(
                ui.input_action_button(
                    "calculate_accessibility",
                    "Get directions",
                    class_="btn-primary",
                ),
                class_="accessibility-button",
            ),
            col_widths=(8, 4),
        ),
        ui.output_ui("accessibility_location_status"),
        ui.output_ui("accessibility_results"),
        class_="section",
    ),
    ui.div(
        ui.div(
            "COMMUNITY CONTEXT",
            class_="section-eyebrow",
        ),
        ui.div(
            "What might shape the path to participation?",
            class_="section-title",
        ),
        ui.div(
            "Community characteristics provide context for "
            "understanding potential non-medical barriers to "
            "clinical trial participation.",
            class_="section-description",
        ),
        class_="section",
    ),
    ui.layout_columns(
        ui.output_ui("economic_card"),
        ui.output_ui("transportation_card"),
        ui.output_ui("connectivity_card"),
        col_widths=(4, 4, 4),
    ),
    ui.div(
        "CITE Foundation · Clinical Trial Access Explorer · "
        "Exploratory Research Prototype",
        class_="footer",
    ),
)
def server(input, output, session):
    clicked_state = reactive.value(None)
    clicked_county = reactive.value(None)
    @reactive.effect
    def _apply_clicked_state():
        value = clicked_state()
        if value is None:
            return
        ui.update_select("state", selected=value, session=session)
        clicked_state.set(None)
    @reactive.effect
    def _apply_clicked_county():
        value = clicked_county()
        if value is None:
            return
        ui.update_select(
            "county",
            selected=value,
            session=session,
        )
        clicked_county.set(None)
    @reactive.effect
    def _update_counties():
        state = input.state()
        if state == "United States":
            ui.update_select("county", choices=["All Counties"], selected="All Counties")
            return
        choices = sorted(county_data.loc[county_data["state_name"] == state, "county_only"].dropna().unique())
        ui.update_select("county", choices=["All Counties"] + choices, selected="All Counties")
    @reactive.calc
    def selected_row():
        state = input.state()
        county = input.county()
        if state == "United States":
            return None
        if county is None or county in ("", "All Counties") or county.startswith("Select a"):
            return None
        matches = county_data[
            (county_data["state_name"] == state)
            & (county_data["county_only"] == county)
        ]
        if matches.empty:
            return None
        return matches.iloc[0]
    @reactive.calc
    def selected_sites():
        state = input.state()
        county = input.county()
        if state == "United States":
            return pd.DataFrame()
        if county in (None, "", "All Counties"):
            return trial_sites_for_state(state)
        return trial_sites_for(selected_row())
    @reactive.calc
    def filtered_trial_sites():
        result = selected_sites()
        if result.empty:
            return result
        condition = input.trial_condition().strip()
        status = input.trial_status()
        sex = input.trial_sex()
        age = input.trial_age()
        eligibility = input.trial_eligibility().strip()
        if condition:
            text = result.get("condition", pd.Series("", index=result.index)).fillna("").astype(str)
            conditions = result.get("conditions", pd.Series("", index=result.index)).fillna("").astype(str)
            result = result[text.str.contains(condition, case=False, na=False, regex=False) | conditions.str.contains(condition, case=False, na=False, regex=False)]
        if status:
            status_text = result.get(
                "recruitment_status",
                result.get("overall_status", pd.Series("", index=result.index)),
            ).fillna("").astype(str).str.upper().str.strip()
            if "overall_status" in result.columns and "recruitment_status" in result.columns:
                status_text = (
                    result["recruitment_status"]
                    .fillna(result["overall_status"])
                    .astype(str)
                    .str.upper()
                    .str.strip()
                )
            normalize_status = lambda s: (
                str(s)
                .upper()
                .strip()
                .replace(",", "")
                .replace("-", "_")
                .replace(" ", "_")
            )
            status_text = status_text.map(normalize_status)
            result = result[status_text == normalize_status(status)]
        if sex:
            sex_text = result.get("sex", pd.Series("", index=result.index)).fillna("").astype(str).str.upper().str.strip()
            result = result[sex_text.isin([sex.upper(), "ALL", ""])]
        if age:
            minimum = pd.to_numeric(result.get("minimum_age", pd.Series(index=result.index)), errors="coerce")
            maximum = pd.to_numeric(result.get("maximum_age", pd.Series(index=result.index)), errors="coerce")
            if age == "Child":
                mask = minimum.isna() | (minimum <= 17)
            elif age == "Adult":
                mask = maximum.isna() | (maximum >= 18)
            else:
                mask = maximum.isna() | (maximum >= 65)
            result = result[mask]
        if eligibility:
            eligibility_text = result.get("eligibility", pd.Series("", index=result.index)).fillna("").astype(str)
            result = result[eligibility_text.str.contains(eligibility, case=False, na=False, regex=False)]
        return result

    @reactive.effect
    def _update_accessibility_sites():
        if input.state() == "United States":
            ui.update_select(
                "accessibility_site",
                choices={"": "Select a state first"},
                selected="",
            )
            return

        sites = selected_sites()

        if "transit_ready" in sites.columns:
            sites = sites[
                sites["transit_ready"].fillna(False).astype(bool)
            ].copy()

        sites = sites.dropna(
            subset=["map_latitude", "map_longitude"]
        ).drop_duplicates(
            subset=["map_latitude", "map_longitude"]
        )

        if sites.empty:
            ui.update_select(
                "accessibility_site",
                choices={"": "Select a trial site"},
                selected="",
            )
            return

        choices = {}
        for index, site in sites.iterrows():
            label = str(site.get("facility", "Unknown facility"))
            city = site.get("city", "")
            state = site.get("state", "")

            if pd.notna(city) and str(city).strip():
                label += f" · {city}"
            if pd.notna(state) and str(state).strip():
                label += f", {state}"

            choices[str(index)] = label

        ui.update_select(
            "accessibility_site",
            choices={"": "Select a trial site", **choices},
            selected="",
        )

    @reactive.calc
    @reactive.event(input.find_nearest_site)
    def accessibility_origin():
        address = input.accessibility_address()

        if not address or not address.strip():
            return {"error": "Please enter a starting address."}

        location = geocode_address(address)

        if location is None:
            return {
                "error": (
                    "We could not find that address. "
                    "Try including the city, state, or ZIP code."
                )
            }

        return location

    @reactive.effect
    def _select_nearest_site():
        origin = accessibility_origin()

        if origin is None or "error" in origin:
            return

        sites = selected_sites()

        if "transit_ready" in sites.columns:
            sites = sites[
                sites["transit_ready"].fillna(False).astype(bool)
            ].copy()

        nearest = find_nearest_trial_site(
            origin["latitude"],
            origin["longitude"],
            sites,
        )

        if nearest is not None:
            ui.update_select(
                "accessibility_site",
                selected=str(nearest.name),
            )

    @render.ui
    def accessibility_location_status():
        if input.state() == "United States":
            return ui.div(
                "Select a state and county first so the nearest-site search "
                "is limited to the locations currently shown in the explorer.",
                class_="metric-note",
            )
        return ui.div()

    @reactive.calc
    @reactive.event(input.calculate_accessibility)
    def accessibility_result():
        site_id = input.accessibility_site()

        if not site_id:
            return None

        origin = accessibility_origin()

        if origin is None:
            return None
        if "error" in origin:
            return origin

        sites = selected_sites()

        if "transit_ready" in sites.columns:
            sites = sites[
                sites["transit_ready"].fillna(False).astype(bool)
            ].copy()

        try:
            site = sites.loc[int(site_id)]
        except (KeyError, ValueError):
            return {"error": "The selected trial site could not be found."}

        destination_lat = site.get("map_latitude")
        destination_lon = site.get("map_longitude")

        if any(pd.isna(v) for v in [
            origin["latitude"],
            origin["longitude"],
            destination_lat,
            destination_lon,
        ]):
            return {
                "error": (
                    "Coordinates are unavailable for the starting "
                    "location or trial site."
                )
            }

        try:
            result = get_trial_accessibility(
                float(origin["latitude"]),
                float(origin["longitude"]),
                float(destination_lat),
                float(destination_lon),
            )
            result["origin_address"] = origin.get(
                "address",
                input.accessibility_address(),
            )
            result["destination_facility"] = site.get(
                "facility",
                "Selected clinical trial site",
            )
            result["destination_city"] = site.get("city", "")
            result["destination_latitude"] = float(destination_lat)
            result["destination_longitude"] = float(destination_lon)
            return result
        except Exception as exc:
            return {"error": str(exc)}

    @render.ui
    def accessibility_results():
        result = accessibility_result()

        if result is None:
            return ui.div()

        if "error" in result:
            return ui.div(
                ui.div(
                    "Accessibility could not be calculated.",
                    class_="context-title",
                ),
                ui.div(
                    result["error"],
                    class_="context-label",
                ),
                class_="context-card",
            )

        driving = result.get("driving", {})
        transit = result.get("transit", {})

        driving_time = driving.get("duration_minutes")
        driving_distance = driving.get("distance_miles")
        transit_time = transit.get("duration_minutes")
        transfers = transit.get("transfers")
        walking = transit.get("walking_minutes")

        destination_lat = result.get("destination_latitude")
        destination_lon = result.get("destination_longitude")
        origin = accessibility_origin()

        driving_url = transit_url = None
        if (
            origin
            and "error" not in origin
            and destination_lat is not None
            and destination_lon is not None
        ):
            driving_url = google_maps_directions_url(
                origin["latitude"],
                origin["longitude"],
                destination_lat,
                destination_lon,
                "driving",
            )
            transit_url = google_maps_directions_url(
                origin["latitude"],
                origin["longitude"],
                destination_lat,
                destination_lon,
                "transit",
            )

        driving_link = (
            ui.a(
                "Open driving directions in Google Maps ↗",
                href=driving_url,
                target="_blank",
                rel="noopener noreferrer",
                class_="maps-link",
            )
            if driving_url else ui.div()
        )

        transit_link = (
            ui.a(
                "Open transit directions in Google Maps ↗",
                href=transit_url,
                target="_blank",
                rel="noopener noreferrer",
                class_="maps-link",
            )
            if transit_url else ui.div()
        )

        return ui.div(
            ui.div(
                ui.div("DRIVING", class_="metric-label"),
                ui.div(
                    f"{driving_time:.0f} min"
                    if driving_time is not None else "Unavailable",
                    class_="metric-value",
                ),
                ui.div(
                    f"{driving_distance:.1f} miles"
                    if driving_distance is not None else "Route unavailable",
                    class_="metric-note",
                ),
                driving_link,
                class_="metric-card",
            ),
            ui.div(
                ui.div("PUBLIC TRANSIT", class_="metric-label"),
                ui.div(
                    f"{transit_time:.0f} min"
                    if transit_time is not None else "Unavailable",
                    class_="metric-value",
                ),
                ui.div(
                    (
                        f"{transfers} transfers · {walking:.0f} min walking"
                        if transit_time is not None and walking is not None
                        else "No transit itinerary available"
                    ),
                    class_="metric-note",
                ),
                transit_link,
                class_="metric-card",
            ),
            class_="accessibility-results-grid",
        )

    @render.ui
    def county_header():
        if input.state() == "United States":
            return ui.div(
                ui.div(
                    "United States",
                    class_="county-name",
                ),
                ui.div(
                    "National overview",
                    class_="county-state",
                ),
                class_="county-header",
            )
        row = selected_row()
        if row is None:
            return ui.div()
        return ui.div(
            ui.div(
                row["county_only"],
                class_="county-name",
            ),
            ui.div(
                row["state_name"],
                class_="county-state",
            ),
            class_="county-header",
        )
    def metric_card(label, value, note):
        return ui.div(
            ui.div(label, class_="metric-label"),
            ui.div(number(value), class_="metric-value"),
            ui.div(note, class_="metric-note"),
            class_="metric-card",
        )
    @render.ui
    def active_trials_card():
        row = selected_row()
        if input.state() == "United States":
            sites = trial_sites
            if "nct_id" in sites.columns:
                value = sites["nct_id"].dropna().nunique()
            elif "active_trial_count" in county_data.columns:
                value = pd.to_numeric(
                    county_data["active_trial_count"],
                    errors="coerce",
                ).sum()
            elif "active_trials" in county_data.columns:
                value = pd.to_numeric(
                    county_data["active_trials"],
                    errors="coerce",
                ).sum()
            else:
                value = None
        else:
            if row is None:
                return ui.div()
            value = get_column(
                row,
                [
                    "active_trial_count",
                    "active_trials",
                ],
            )
        return metric_card(
            "ACTIVE TRIALS",
            value,
            "Recruiting or not yet recruiting",
        )
    @render.ui
    def trial_sites_card():
        row = selected_row()
        if input.state() == "United States":
            value = len(filtered_trial_sites())
        else:
            if row is None:
                return ui.div()
            value = get_column(
                row,
                [
                    "active_trial_site_records",
                    "trial_site_records",
                ],
            )
        return metric_card(
            "TRIAL-SITE RECORDS",
            value,
            "Trial-location records",
        )
    @render.ui
    def facility_card():
        sites = filtered_trial_sites()
        facilities = (
            sites["facility"].dropna().nunique()
            if "facility" in sites.columns
            else 0
        )
        return metric_card(
            "FACILITIES",
            facilities,
            "Unique facilities with trial records",
        )
    @render_widget
    def trial_map():
        state = input.state()
        county = input.county()
        if state == "United States":
            m = Map(center=(39.8283, -98.5795), zoom=4, scroll_wheel_zoom=True)
            try:
                data = load_state_boundaries()
                layer = GeoJSON(
                    data=data,
                    style={
                        "color": "#1F5F94",
                        "weight": 1.5,
                        "fillColor": "#EAF3F8",
                        "fillOpacity": 0.35,
                    },
                    hover_style={
                        "color": "#D9823B",
                        "weight": 2.5,
                        "fillColor": "#FDF1E7",
                        "fillOpacity": 0.65,
                    },
                )
                def state_clicked(event=None, feature=None, **kwargs):
                    feature = feature or kwargs.get("feature") or {}
                    props = kwargs.get("properties") or (feature.get("properties", {}) if isinstance(feature, dict) else {})
                    if not isinstance(props, dict):
                        props = {}
                    name = str(props.get("name", props.get("NAME", ""))).strip()
                    match = next((s for s in states if s.lower() == name.lower()), None)
                    if match:
                        clicked_state.set(match)
                layer.on_click(state_clicked)
                m.add_layer(layer)
            except Exception:
                pass
            return m
        state_rows = county_data[county_data["state_name"] == state]
        state_fips = str(state_rows.iloc[0]["state_fips"]).zfill(2) if not state_rows.empty else ""
        if county in (None, "", "All Counties"):
            m = Map(center=(39.8283, -98.5795), zoom=6, scroll_wheel_zoom=True)
            try:
                data = load_county_boundaries(state_fips)
                features = data.get("features", [])
                layer = GeoJSON(
                    data=data,
                    style={
                        "color": "#1F5F94",
                        "weight": 1.0,
                        "fillColor": "#EAF3F8",
                        "fillOpacity": 0.32,
                    },
                    hover_style={
                        "color": "#D9823B",
                        "weight": 2.0,
                        "fillColor": "#FDF1E7",
                        "fillOpacity": 0.68,
                    },
                )
                def county_clicked(event=None, feature=None, **kwargs):
                    feature = feature or kwargs.get("feature") or {}
                    props = kwargs.get("properties") or (feature.get("properties", {}) if isinstance(feature, dict) else {})
                    if not isinstance(props, dict):
                        props = {}
                    clicked_state_fips = str(props.get("STATE_FIPS", state_fips)).replace(".0", "").zfill(2)
                    clicked_county_fips = str(props.get("CNTY_FIPS", props.get("COUNTY_FIPS", ""))).replace(".0", "").zfill(3)
                    match_rows = county_data[
                        (county_data["state_fips"] == clicked_state_fips)
                        & (county_data["county_fips"] == clicked_county_fips)
                    ]
                    if not match_rows.empty:
                        clicked_county.set(str(match_rows.iloc[0]["county_only"]))
                        return
                    name = str(props.get("NAME", props.get("name", ""))).strip()
                    if not name:
                        return
                    choices = sorted(
                        county_data.loc[
                            county_data["state_name"] == state,
                            "county_only",
                        ].dropna().astype(str).unique()
                    )
                    match = next((c for c in choices if c.lower() == name.lower()), None)
                    if match:
                        clicked_county.set(match)
                layer.on_click(county_clicked)
                m.add_layer(layer)
                bounds = []
                for feature in features:
                    b = geometry_bounds(feature.get("geometry", {}))
                    if b:
                        bounds.append(b)
                if bounds:
                    m.fit_bounds(
                        [
                            [min(b[0][0] for b in bounds), min(b[0][1] for b in bounds)],
                            [max(b[1][0] for b in bounds), max(b[1][1] for b in bounds)],
                        ]
                    )
            except Exception:
                pass
            return m
        sites = verified_map_sites(filtered_trial_sites())
        if sites.empty:
            row = selected_row()
            if row is not None:
                return Map(center=(39.8283, -98.5795), zoom=6, scroll_wheel_zoom=True)
            return Map(center=(39.8283, -98.5795), zoom=6, scroll_wheel_zoom=True)
        lat = float(sites["resolved_latitude"].mean())
        lon = float(sites["resolved_longitude"].mean())
        zoom = 11 if len(sites) <= 5 else 10
        m = Map(center=(lat, lon), zoom=zoom, scroll_wheel_zoom=True)
        locations = sites.groupby(["resolved_latitude", "resolved_longitude"], dropna=False)
        for (latitude, longitude), location_sites in locations:
            facility_values = location_sites.get("facility", pd.Series(index=location_sites.index)).dropna().astype(str).str.strip().unique()
            facility = facility_values[0] if len(facility_values) else "Clinical trial site"
            city = location_sites["city"].dropna().astype(str).str.strip().iloc[0] if "city" in location_sites.columns and not location_sites["city"].dropna().empty else ""
            state_name = location_sites["state"].dropna().astype(str).str.strip().iloc[0] if "state" in location_sites.columns and not location_sites["state"].dropna().empty else ""
            address = location_sites["facility_address"].dropna().astype(str).str.strip().iloc[0] if "facility_address" in location_sites.columns and not location_sites["facility_address"].dropna().empty else ""
            trials = []
            if "nct_id" in location_sites.columns:
                for nct_id in sorted(location_sites["nct_id"].dropna().astype(str).str.strip().unique()):
                    rows = location_sites[location_sites["nct_id"].astype(str).str.strip() == nct_id]
                    title = str(rows["brief_title"].dropna().iloc[0]) if "brief_title" in rows.columns and not rows["brief_title"].dropna().empty else ""
                    label = escape(title) if title else escape(nct_id)
                    trials.append(f'<li><a href="https://clinicaltrials.gov/study/{quote(nct_id)}" target="_blank">{escape(nct_id)}</a>{" — " + label if title else ""}</li>')
            location_text = ", ".join([x for x in [address, city, state_name] if x])
            destination = (
                f'{float(location_sites["resolved_latitude"].dropna().iloc[0])},'
                f'{float(location_sites["resolved_longitude"].dropna().iloc[0])}'
            )
            transit_url = (
                "https://www.google.com/maps/dir/?api=1&destination="
                + quote(destination)
                + "&travelmode=transit"
            )
            action_html = (
                f'<a href="{transit_url}" target="_blank" '
                'style="display:inline-block;margin-top:8px;padding:7px 10px;'
                'border-radius:6px;background:#164A7A;color:white;'
                'text-decoration:none;font-weight:600">'
                'Find Transit Directions</a>'
            )
            popup_html = (
                f'<div style="min-width:300px"><b>{escape(facility)}</b><br>'
                f'<span>{escape(location_text)}</span><br>'
                '<span style="font-size:12px;color:#66788A">Verified public facility location</span>'
                '<hr><b>' + str(len(trials)) + ' trial(s)</b>'
                '<ul style="padding-left:18px;margin-bottom:4px">' +
                ("".join(trials) or "<li>No trial IDs available</li>") +
                f'</ul>{action_html}</div>'
            )
            marker = Marker(location=(float(latitude), float(longitude)), draggable=False)
            marker.popup = Popup(child=HTML(value=popup_html), close_button=True, auto_close=True)
            m.add_layer(marker)
        return m
    def national_context_card(title):
        return ui.div(
            ui.div(title, class_="context-title"),
            ui.div(
                ui.span("National view", class_="context-label"),
                ui.span(
                    "Select a county for community-level values",
                    class_="context-value",
                ),
                class_="context-row",
            ),
            class_="context-card",
        )
    @render.ui
    def economic_card():
        if input.state() == "United States":
            return national_context_card("Economic context")
        row = selected_row()
        if row is None:
            return ui.div()
        population = get_column(row, ["population"])
        income = get_column(
            row,
            ["median_income", "median_household_income"],
        )
        poverty = get_column(
            row,
            ["poverty_rate", "poverty"],
        )
        return ui.div(
            ui.div(
                "Economic",
                class_="context-title",
            ),
            ui.div(
                ui.span("Population", class_="context-label"),
                ui.span(number(population), class_="context-value"),
                class_="context-row",
            ),
            ui.div(
                ui.span(
                    "Median household income",
                    class_="context-label",
                ),
                ui.span(currency(income), class_="context-value"),
                class_="context-row",
            ),
            ui.div(
                ui.span("Poverty rate", class_="context-label"),
                ui.span(percent(poverty), class_="context-value"),
                class_="context-row",
            ),
            class_="context-card",
        )
    @render.ui
    def transportation_card():
        if input.state() == "United States":
            return national_context_card("Transportation")
        row = selected_row()
        if row is None:
            return ui.div()
        vehicle = get_column(
            row,
            [
                "no_vehicle",
                "no_vehicle_rate",
                "households_no_vehicle",
            ],
        )
        return ui.div(
            ui.div(
                "Transportation",
                class_="context-title",
            ),
            ui.div(
                ui.span(
                    "Households without a vehicle",
                    class_="context-label",
                ),
                ui.span(percent(vehicle), class_="context-value"),
                class_="context-row",
            ),
            ui.div(
                ui.span(
                    "Research relevance",
                    class_="context-label",
                ),
                ui.span(
                    (
                        "Potential mobility constraint"
                        if pd.notna(vehicle) and vehicle >= 10
                        else "Within typical range"
                        if pd.notna(vehicle)
                        else "Not available"
                    ),
                    class_="context-value",
                ),
                class_="context-row",
            ),
            class_="context-card",
        )
    @render.ui
    def connectivity_card():
        if input.state() == "United States":
            return national_context_card("Digital connectivity")
        row = selected_row()
        if row is None:
            return ui.div()
        broadband = get_column(
            row,
            [
                "broadband",
                "broadband_rate",
                "broadband_access",
            ],
        )
        return ui.div(
            ui.div(
                "Digital connectivity",
                class_="context-title",
            ),
            ui.div(
                ui.span(
                    "Broadband access",
                    class_="context-label",
                ),
                ui.span(
                    percent(broadband),
                    class_="context-value",
                ),
                class_="context-row",
            ),
            ui.div(
                ui.span(
                    "Research relevance",
                    class_="context-label",
                ),
                ui.span(
                    (
                        "Potential digital access constraint"
                        if pd.notna(broadband) and broadband < 78
                        else "Within typical range"
                        if pd.notna(broadband)
                        else "Not available"
                    ),
                    class_="context-value",
                ),
                class_="context-row",
            ),
            class_="context-card",
        )
    @render.ui
    def addressless_trials_section():
        if input.state() == "United States":
            return ui.div()
        sites = filtered_trial_sites()
        if sites.empty:
            return ui.div()
        status = trial_status_series(sites)
        verified = has_verified_public_location(sites)
        addressless = sites.loc[~verified].copy()
        if addressless.empty:
            return ui.div()
        recruiting = addressless.loc[
            status.loc[addressless.index].map(is_recruiting_status)
        ]
        not_yet = addressless.loc[
            status.loc[addressless.index].map(is_not_yet_recruiting_status)
        ]
        def trial_rows(frame):
            if frame.empty:
                return ui.div(
                    "No sites in this category.",
                    class_="addressless-empty",
                )
            cards = []
            for _, site in frame.iterrows():
                facility = escape(str(site.get("facility", "Clinical Trial Site")))
                city = escape(str(site.get("city", "")))
                state = escape(str(site.get("state", "")))
                nct = escape(str(site.get("nct_id", "")))
                title = escape(str(site.get("brief_title", "Clinical trial")))
                status_text = escape(str(site.get("recruitment_status", site.get("overall_status", "Status unavailable"))))
                cards.append(
                    ui.div(
                        ui.div(facility, class_="addressless-facility"),
                        ui.div(f"{city}, {state}" if city or state else "Location details unavailable", class_="addressless-location"),
                        ui.div(title, class_="addressless-title"),
                        ui.div(
                            ui.span(status_text, class_="addressless-status"),
                            ui.a(
                                "View on ClinicalTrials.gov",
                                href=f"https://clinicaltrials.gov/study/{nct}" if nct else "https://clinicaltrials.gov/",
                                target="_blank",
                                rel="noopener noreferrer",
                                class_="addressless-link",
                            ),
                            class_="addressless-meta",
                        ),
                        class_="addressless-card",
                    )
                )
            return ui.div(*cards, class_="addressless-list")
        return ui.div(
            ui.div("TRIAL SITES WITHOUT VERIFIED PUBLIC ADDRESSES", class_="section-eyebrow"),
            ui.div("Addressless clinical trial sites", class_="section-title"),
            ui.div(
                "These sites remain searchable and filterable even when a public street address "
                "or verified physical location is not available. Recruitment status does not determine "
                "whether an address is available.",
                class_="section-description",
            ),
            ui.div(
                ui.div(
                    ui.div("Currently recruiting", class_="addressless-subtitle"),
                    ui.div(f"{len(recruiting):,}", class_="addressless-count"),
                    trial_rows(recruiting),
                    class_="addressless-group",
                ),
                ui.div(
                    ui.div("Not yet recruiting", class_="addressless-subtitle"),
                    ui.div(f"{len(not_yet):,}", class_="addressless-count"),
                    trial_rows(not_yet),
                    class_="addressless-group",
                ),
                class_="addressless-groups",
            ),
            class_="addressless-section",
        )
    @render.ui
    def health_data_status():
        columns = ["fair_poor_health", "physical_distress", "mental_distress"]
        if all(column in county_data.columns for column in columns):
            available = int(county_data[columns].notna().any(axis=1).sum())
        else:
            available = 0
        if available:
            return ui.div(
                ui.span(class_="health-status-dot"),
                ui.span(
                    ui.strong(f"{available:,} counties"),
                    " with CDC PLACES health estimates available in the explorer.",
                ),
                class_="health-status",
            )
        return ui.div(
            ui.span(class_="health-status-dot unavailable"),
            ui.span(
                ui.strong("Health data unavailable"),
                " — run clinical_trials.py to refresh the county dataset with CDC PLACES measures.",
            ),
            class_="health-status",
        )
    def health_indicator(title, column, description, card_class):
        if input.state() == "United States":
            return ui.div(
                ui.div("HEALTH INDICATOR · PLACES", class_="signal-label"),
                ui.div(title, class_="signal-title"),
                ui.div("—", class_="signal-value"),
                ui.div(
                    "Select a county to view the community-level estimate.",
                    class_="signal-description",
                ),
                ui.div(
                    ui.div(style="width: 0%;", class_="health-meter-fill"),
                    class_="health-meter",
                ),
                ui.div(
                    "County-level estimate · age-adjusted prevalence.",
                    class_="health-footnote",
                ),
                class_=f"signal-card {card_class}",
            )
        row = selected_row()
        if row is None:
            return ui.div()
        value = get_column(row, [column])
        width = health_bar_width(value)
        return ui.div(
            ui.div("HEALTH INDICATOR · PLACES", class_="signal-label"),
            ui.div(title, class_="signal-title"),
            ui.div(percent(value), class_="signal-value"),
            ui.div(description, class_="signal-description"),
            ui.div(
                ui.div(style=f"width: {width}%;", class_="health-meter-fill"),
                class_="health-meter",
            ),
            ui.div(
                "Age-adjusted prevalence among adults.",
                class_="health-footnote",
            ),
            class_=f"signal-card {card_class}",
        )
    @render.ui
    def health_card_1():
        return health_indicator(
            "Fair / poor health",
            "fair_poor_health",
            "Adults reporting self-rated health as either fair or poor.",
            "health-primary",
        )
    @render.ui
    def health_card_2():
        return health_indicator(
            "Frequent physical distress",
            "physical_distress",
            "Adults reporting poor physical health on 14+ days in the past month.",
            "health-secondary",
        )
    @render.ui
    def health_card_3():
        return health_indicator(
            "Frequent mental distress",
            "mental_distress",
            "Adults reporting poor mental health on 14+ days in the past month.",
            "health-tertiary",
        )
app = App(
    app_ui,
    server,
)
