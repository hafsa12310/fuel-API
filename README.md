# Fuel Route Optimizer API

A Django REST API that calculates driving routes between US locations and recommends fuel stops based on vehicle range and station prices.

## Features

- Retrieves driving routes using OpenRouteService.
- Finds fuel stations within approximately 15 miles of the route.
- Selects reachable stops using a price-aware heuristic.
- Supports configurable vehicle range and fuel efficiency.
- Returns GeoJSON route geometry and estimated fuel costs.
- Imports fuel-station data from CSV.

## Tech Stack

Python, Django, Django REST Framework, SQLite, Shapely, Requests, and python-dotenv.

## Local Setup

### 1. Create a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows:

```bash
.venv\Scripts\activate
```

### 2. Install Dependencies

```bash
python -m pip install "Django>=6.0,<6.1" djangorestframework requests shapely python-dotenv
```

### 3. Set Up the Database

```bash
python manage.py migrate
```

### 4. Import Fuel Stations

```bash
python manage.py import_fuel_prices data/fuel-prices.csv
```

To replace existing records:

```bash
python manage.py import_fuel_prices data/fuel-prices.csv --replace
```

### 5. Start the Server

```bash
python manage.py runserver
```

The endpoint will be available at:

```text
http://127.0.0.1:8000/api/route/
```

## API Usage

### Request

```http
POST /api/route/
```

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `start` | string | Yes | — | Starting US location |
| `finish` | string | Yes | — | Destination US location |
| `max_range_miles` | number | No | `500` | Vehicle range in miles |
| `mpg` | number | No | `10` | Vehicle fuel efficiency |

### Example

```bash
curl -X POST http://127.0.0.1:8000/api/route/ \
  -H "Content-Type: application/json" \
  -d '{
    "start": "Chicago, IL",
    "finish": "Dallas, TX",
    "max_range_miles": 500,
    "mpg": 10
  }'
```

### Response

A successful request returns:

- Resolved start and destination locations.
- GeoJSON route geometry.
- Selected fuel stops and station prices.
- Estimated gallons purchased and cost per stop.
- Total distance, fuel consumption, and en-route fuel cost.

### Errors

| Status | Meaning |
| --- | --- |
| `400 Bad Request` | Missing or invalid request fields |
| `422 Unprocessable Entity` | Location, route, or reachable station not found |
| `503 Service Unavailable` | Routing provider request failed |

## Fuel-Stop Selection

1. Resolve the start and destination.
2. Request a driving route.
3. Find nearby fuel stations.
4. Identify stations reachable with the remaining fuel.
5. Prefer cheaper stations near the end of the reachable range.
6. Repeat until the destination is reachable.

## Limitations

- The vehicle starts with a full tank.
- Fuel prices come from the CSV and are not live.
- Stop selection does not guarantee the cheapest possible trip.
- Routes use the `driving-car` profile.
- Station detours are approximate.
- Route calculations exclude station detours.

## Project Structure

```text
config/                         Django settings and root URLs
data/fuel-prices.csv            Fuel-station dataset
route_optimizer/
  management/commands/
    import_fuel_prices.py       CSV importer
  models.py                     Fuel-station model
  serializers.py                Request validation
  services.py                   Route and fuel calculations
  urls.py                       API URLs
  views.py                      Request handling
manage.py                       Django management entry point
```
