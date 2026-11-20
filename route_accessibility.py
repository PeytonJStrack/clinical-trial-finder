import os
from typing import Any

import requests
from dotenv import load_dotenv


load_dotenv()

TRANSITLAND_API_KEY = os.getenv("TRANSITLAND_API_KEY")

STREET_ROUTING_URL = (
    "https://transit.land/api/v2/routing/valhalla/route"
)

TRANSIT_ROUTING_URL = (
    "https://transit.land/api/v2/routing/otp/plan"
)

REQUEST_TIMEOUT = 30


def _check_api_key() -> None:
    if not TRANSITLAND_API_KEY:
        raise ValueError(
            "TRANSITLAND_API_KEY is not set. "
            "Add it to your .env file."
        )


def _seconds_to_minutes(
    seconds: float | int | None,
) -> float | None:
    if seconds is None:
        return None

    return round(float(seconds) / 60, 1)


def _meters_to_miles(
    meters: float | int | None,
) -> float | None:
    if meters is None:
        return None

    return round(float(meters) / 1609.344, 1)


def get_driving_route(
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
) -> dict[str, Any]:

    _check_api_key()

    request_body = {
        "locations": [
            {
                "lat": origin_lat,
                "lon": origin_lon,
            },
            {
                "lat": destination_lat,
                "lon": destination_lon,
            },
        ],
        "costing": "auto",
        "units": "miles",
    }

    response = requests.post(
        STREET_ROUTING_URL,
        headers={
            "apikey": TRANSITLAND_API_KEY,
            "Content-Type": "application/json",
        },
        json=request_body,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()
    trip = data.get("trip", {})
    summary = trip.get("summary", {})

    return {
        "available": True,
        "duration_minutes": _seconds_to_minutes(
            summary.get("time")
        ),
        "distance_miles": summary.get("length"),
    }


def _parse_transit_legs(
    itinerary: dict[str, Any],
) -> list[dict[str, Any]]:

    legs = []

    for leg in itinerary.get("legs", []):
        mode = leg.get("mode")

        leg_data = {
            "mode": mode,
            "duration_minutes": _seconds_to_minutes(
                leg.get("duration")
            ),
            "distance_miles": _meters_to_miles(
                leg.get("distance")
            ),
        }

        if mode not in {"WALK", "BICYCLE", "CAR"}:
            leg_data["route"] = (
                leg.get("route")
                or leg.get("routeShortName")
                or leg.get("routeLongName")
            )

        legs.append(leg_data)

    return legs


def get_transit_route(
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
) -> dict[str, Any]:

    _check_api_key()

    params = {
        "fromPlace": f"{origin_lat},{origin_lon}",
        "toPlace": f"{destination_lat},{destination_lon}",

        "maxWalkingDistance": 1609,

        "maxTransferWalkingDistance": 800,

        "maxItineraries": 5,
    }

    response = requests.get(
        TRANSIT_ROUTING_URL,
        headers={
            "apikey": TRANSITLAND_API_KEY,
        },
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    plan = data.get("plan", {})
    itineraries = plan.get("itineraries", [])

    if not itineraries:
        return {
            "available": False,
            "duration_minutes": None,
            "transfers": None,
            "walking_minutes": None,
            "walking_miles": None,
            "legs": [],
        }

    transit_itineraries = [
        itinerary
        for itinerary in itineraries
        if any(
            leg.get("mode") not in {
                "WALK",
                "BICYCLE",
                "CAR",
            }
            for leg in itinerary.get("legs", [])
        )
    ]

    if transit_itineraries:
        itinerary = transit_itineraries[0]
        uses_transit = True
    else:
        itinerary = itineraries[0]
        uses_transit = False

    legs = _parse_transit_legs(itinerary)

    walking_minutes = 0.0
    walking_miles = 0.0
    transit_leg_count = 0

    for leg in legs:
        if leg["mode"] == "WALK":
            walking_minutes += leg["duration_minutes"] or 0
            walking_miles += leg["distance_miles"] or 0
        elif leg["mode"] not in {
            "BICYCLE",
            "CAR",
        }:
            transit_leg_count += 1

    transfers = max(transit_leg_count - 1, 0)

    return {
        "available": uses_transit,
        "duration_minutes": _seconds_to_minutes(
            itinerary.get("duration")
        ),
        "transfers": transfers if uses_transit else None,
        "walking_minutes": round(walking_minutes, 1),
        "walking_miles": round(walking_miles, 1),
        "legs": legs,
    }


def get_trial_accessibility(
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
) -> dict[str, Any]:

    driving = get_driving_route(
        origin_lat,
        origin_lon,
        destination_lat,
        destination_lon,
    )

    transit = get_transit_route(
        origin_lat,
        origin_lon,
        destination_lat,
        destination_lon,
    )

    return {
        "driving": driving,
        "transit": transit,
    }
