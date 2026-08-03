import hashlib
import math
import requests

from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from shapely.geometry import LineString, Point

from .models import FuelStation


MILES_PER_METER = 1 / 1609.344
EARTH_RADIUS_MILES = 3958.7613


class RoutingError(Exception):
    pass


@dataclass
class StationCandidate:
    station: FuelStation
    route_mile: float
    detour_miles: float


class ORSClient:
    def __init__(self):
        if not settings.ORS_API_KEY:
            raise RoutingError(
                "ORS_API_KEY is not configured"
            )

        self.headers = {
            "Authorization": settings.ORS_API_KEY,
            "Content-Type": "application/json",
        }

    def geocode(self, text):
        normalized_text = text.lower().strip()

        cache_key = (
            "geo:"
            + hashlib.sha256(
                normalized_text.encode()
            ).hexdigest()
        )

        cached_result = cache.get(cache_key)

        if cached_result:
            return cached_result

        response = requests.get(
            f"{settings.ORS_BASE_URL}/geocode/search",
            params={
                "api_key": settings.ORS_API_KEY,
                "text": text,
                "boundary.country": "US",
                "size": 1,
            },
            timeout=8,
        )

        response.raise_for_status()

        features = response.json().get(
            "features",
            [],
        )

        if not features:
            raise RoutingError(
                f"Location not found in USA: {text}"
            )

        longitude, latitude = (
            features[0]["geometry"]["coordinates"]
        )

        result = {
            "lat": latitude,
            "lon": longitude,
            "label": (
                features[0]
                .get("properties", {})
                .get("label", text)
            ),
        }

        cache.set(
            cache_key,
            result,
            settings.ROUTE_CACHE_SECONDS,
        )

        return result

    def route(self, start, finish):
        payload = {
            "coordinates": [
                [
                    start["lon"],
                    start["lat"],
                ],
                [
                    finish["lon"],
                    finish["lat"],
                ],
            ],
            "instructions": False,
            "geometry": True,
        }

        response = requests.post(
            (
                f"{settings.ORS_BASE_URL}"
                "/v2/directions/"
                "driving-car/geojson"
            ),
            headers=self.headers,
            json=payload,
            timeout=15,
        )

        response.raise_for_status()

        data = response.json()

        features = data.get("features", [])

        if not features:
            raise RoutingError(
                "No driving route was found"
            )

        feature = features[0]
        summary = feature[
            "properties"
        ]["summary"]

        return {
            "geometry": feature["geometry"],
            "distance_miles": (
                summary["distance"]
                * MILES_PER_METER
            ),
            "duration_seconds": (
                summary["duration"]
            ),
        }


def haversine(
    latitude_one,
    longitude_one,
    latitude_two,
    longitude_two,
):
    """
    Calculate the distance between two coordinates
    in miles.
    """

    lat1 = math.radians(latitude_one)
    lat2 = math.radians(latitude_two)

    latitude_difference = math.radians(
        latitude_two - latitude_one
    )

    longitude_difference = math.radians(
        longitude_two - longitude_one
    )

    value = (
        math.sin(
            latitude_difference / 2
        ) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(
            longitude_difference / 2
        ) ** 2
    )

    return (
        2
        * EARTH_RADIUS_MILES
        * math.asin(math.sqrt(value))
    )


def route_candidates(
    route_geometry,
    route_distance_miles,
    corridor_miles=15,
):
    """
    Find fuel stations close to the route.
    """

    coordinates = route_geometry.get(
        "coordinates",
        [],
    )

    if not coordinates:
        raise RoutingError(
            "Route geometry is missing"
        )

    route_line = LineString(coordinates)

    min_longitude, min_latitude, (
        max_longitude
    ), max_latitude = route_line.bounds

    middle_latitude = (
        min_latitude + max_latitude
    ) / 2

    latitude_padding = (
        corridor_miles / 69
    )

    longitude_scale = max(
        0.2,
        abs(
            math.cos(
                math.radians(
                    middle_latitude
                )
            )
        ),
    )

    longitude_padding = (
        corridor_miles
        / (69 * longitude_scale)
    )

    stations = FuelStation.objects.filter(
        latitude__range=(
            min_latitude - latitude_padding,
            max_latitude + latitude_padding,
        ),
        longitude__range=(
            min_longitude - longitude_padding,
            max_longitude + longitude_padding,
        ),
    )

    candidates = []

    for station in stations.iterator(
        chunk_size=1000
    ):
        station_point = Point(
            station.longitude,
            station.latitude,
        )

        route_progress = route_line.project(
            station_point,
            normalized=True,
        )

        nearest_route_point = (
            route_line.interpolate(
                route_progress,
                normalized=True,
            )
        )

        detour_miles = haversine(
            station.latitude,
            station.longitude,
            nearest_route_point.y,
            nearest_route_point.x,
        )

        if detour_miles > corridor_miles:
            continue

        route_mile = (
            route_progress
            * route_distance_miles
        )

        candidates.append(
            StationCandidate(
                station=station,
                route_mile=route_mile,
                detour_miles=detour_miles,
            )
        )

    candidates.sort(
        key=lambda candidate: (
            candidate.route_mile,
            float(
                candidate
                .station
                .retail_price
            ),
        )
    )

    return candidates


def choose_best_station(
    reachable_stations,
    current_mile,
    remaining_range,
):
    """
    Prefer cheaper stations later in the
    vehicle's reachable range.
    """

    preferred_start = (
        current_mile
        + remaining_range * 0.65
    )

    preferred_stations = [
        candidate
        for candidate in reachable_stations
        if (
            candidate.route_mile
            >= preferred_start
        )
    ]

    if preferred_stations:
        return min(
            preferred_stations,
            key=lambda candidate: (
                float(
                    candidate
                    .station
                    .retail_price
                ),
                candidate.detour_miles,
                -candidate.route_mile,
            ),
        )

    return max(
        reachable_stations,
        key=lambda candidate:
            candidate.route_mile,
    )


def choose_stops(
    candidates,
    route_distance_miles,
    max_range_miles,
    mpg,
):
    """
    Select fuel stops until the destination
    becomes reachable.
    """

    current_mile = 0.0

    # Assume the vehicle starts with
    # a full tank.
    remaining_range = max_range_miles

    selected_stops = []
    total_cost = 0.0

    used_station_ids = set()

    while (
        route_distance_miles
        - current_mile
        > remaining_range
    ):
        reachable_stations = []

        for candidate in candidates:
            if (
                candidate.station.id
                in used_station_ids
            ):
                continue

            if (
                candidate.route_mile
                <= current_mile + 1
            ):
                continue

            main_route_distance = (
                candidate.route_mile
                - current_mile
            )

            distance_to_station = (
                main_route_distance
                + candidate.detour_miles
            )

            if (
                distance_to_station
                <= remaining_range
            ):
                reachable_stations.append(
                    candidate
                )

        if not reachable_stations:
            raise RoutingError(
                "No reachable fuel station was "
                "found before the vehicle runs "
                "out of fuel"
            )

        selected_station = (
            choose_best_station(
                reachable_stations,
                current_mile,
                remaining_range,
            )
        )

        main_route_distance = (
            selected_station.route_mile
            - current_mile
        )

        # Travel from the current point to
        # the station.
        remaining_range -= (
            main_route_distance
            + selected_station.detour_miles
        )

        remaining_route_distance = (
            route_distance_miles
            - selected_station.route_mile
        )

        # Fuel required before returning
        # from the station to the main route.
        desired_range_at_station = min(
            max_range_miles,
            remaining_route_distance
            + selected_station.detour_miles,
        )

        missing_range = max(
            0,
            desired_range_at_station
            - remaining_range,
        )

        gallons_purchased = (
            missing_range / mpg
        )

        price_per_gallon = float(
            selected_station
            .station
            .retail_price
        )

        stop_cost = (
            gallons_purchased
            * price_per_gallon
        )

        remaining_range += (
            gallons_purchased * mpg
        )

        # Return from the fuel station to
        # the main route.
        remaining_range -= (
            selected_station.detour_miles
        )

        current_mile = (
            selected_station.route_mile
        )

        total_cost += stop_cost

        used_station_ids.add(
            selected_station.station.id
        )

        selected_stops.append({
            "station": (
                selected_station.station
            ),
            "route_mile": (
                selected_station.route_mile
            ),
            "detour_miles": (
                selected_station.detour_miles
            ),
            "gallons": gallons_purchased,
            "cost": stop_cost,
        })

    return selected_stops, total_cost


def build_result(
    start,
    finish,
    max_range_miles=500,
    mpg=10,
):
    """
    Main function called by the API view.
    """

    client = ORSClient()

    start_location = client.geocode(start)
    finish_location = client.geocode(
        finish
    )

    route_data = client.route(
        start_location,
        finish_location,
    )

    candidates = route_candidates(
        route_geometry=route_data[
            "geometry"
        ],
        route_distance_miles=route_data[
            "distance_miles"
        ],
    )

    fuel_stops, total_cost = (
        choose_stops(
            candidates=candidates,
            route_distance_miles=(
                route_data[
                    "distance_miles"
                ]
            ),
            max_range_miles=(
                max_range_miles
            ),
            mpg=mpg,
        )
    )

    stops_response = []

    for stop in fuel_stops:
        station = stop["station"]

        stops_response.append({
            "station_id": station.id,
            "name": station.name,
            "address": station.address,
            "city": station.city,
            "state": station.state,
            "latitude": station.latitude,
            "longitude": station.longitude,
            "retail_price_per_gallon": (
                float(
                    station.retail_price
                )
            ),
            "route_mile": round(
                stop["route_mile"],
                2,
            ),
            "detour_miles": round(
                stop["detour_miles"],
                2,
            ),
            "gallons_purchased": round(
                stop["gallons"],
                3,
            ),
            "estimated_cost": round(
                stop["cost"],
                2,
            ),
        })

    total_distance = route_data[
        "distance_miles"
    ]

    return {
        "start": start_location,
        "finish": finish_location,
        "route": {
            "type": "Feature",
            "geometry": route_data[
                "geometry"
            ],
            "properties": {
                "distance_miles": round(
                    total_distance,
                    2,
                ),
                "duration_seconds": round(
                    route_data[
                        "duration_seconds"
                    ]
                ),
                "duration_hours": round(
                    route_data[
                        "duration_seconds"
                    ] / 3600,
                    2,
                ),
            },
        },
        "fuel_stops": stops_response,
        "summary": {
            "distance_miles": round(
                total_distance,
                2,
            ),
            "max_range_miles": (
                max_range_miles
            ),
            "mpg": mpg,
            "number_of_fuel_stops": len(
                stops_response
            ),
            "trip_fuel_consumed_gallons": (
                round(
                    total_distance / mpg,
                    3,
                )
            ),
            "estimated_en_route_fuel_cost": (
                round(total_cost, 2)
            ),
            "starting_tank_assumption": (
                "Vehicle starts with a "
                "full tank"
            ),
        },
    }