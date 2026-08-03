import csv
import io
import requests

from django.core.management.base import BaseCommand
from route_optimizer.models import FuelStation


CENSUS_URL = (
    "https://geocoding.geo.census.gov/"
    "geocoder/locations/addressbatch"
)


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument(
            "--replace",
            action="store_true",
        )

    def handle(
        self,
        csv_path,
        replace,
        **kwargs,
    ):
        if replace:
            FuelStation.objects.all().delete()

        with open(
            csv_path,
            newline="",
            encoding="utf-8-sig",
        ) as file:
            rows = list(csv.DictReader(file))

        payload = io.StringIO()
        writer = csv.writer(payload)

        for index, row in enumerate(rows):
            writer.writerow([
                index,
                row["Address"],
                row["City"],
                row["State"],
                "",
            ])

        files = {
            "addressFile": (
                "addresses.csv",
                payload.getvalue(),
                "text/csv",
            )
        }

        response = requests.post(
            CENSUS_URL,
            data={
                "benchmark": "Public_AR_Current"
            },
            files=files,
            timeout=180,
        )

        response.raise_for_status()

        matched_locations = {}

        for result in csv.reader(
            io.StringIO(response.text)
        ):
            if (
                len(result) >= 6
                and result[2].lower() == "match"
            ):
                longitude, latitude = (
                    result[5].split(",")
                )

                matched_locations[
                    int(result[0])
                ] = (
                    float(latitude),
                    float(longitude),
                )

        stations = []

        for index, row in enumerate(rows):
            if index not in matched_locations:
                continue

            latitude, longitude = (
                matched_locations[index]
            )

            stations.append(
                FuelStation(
                    opis_id=int(
                        row["OPIS Truckstop ID"]
                    ),
                    name=row["Truckstop Name"],
                    address=row["Address"],
                    city=row["City"],
                    state=row["State"],
                    rack_id=(
                        int(row["Rack ID"])
                        if row["Rack ID"]
                        else None
                    ),
                    retail_price=row[
                        "Retail Price"
                    ],
                    latitude=latitude,
                    longitude=longitude,
                )
            )

        FuelStation.objects.bulk_create(
            stations,
            ignore_conflicts=True,
            batch_size=1000,
        )