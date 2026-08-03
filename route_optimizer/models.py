from django.db import models

# Create your models here.

from django.db import models


class FuelStation(models.Model):
    opis_id = models.IntegerField(db_index=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=2, db_index=True)

    rack_id = models.IntegerField(
        null=True,
        blank=True,
    )

    retail_price = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        db_index=True,
    )

    latitude = models.FloatField(db_index=True)
    longitude = models.FloatField(db_index=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["latitude", "longitude"]
            ),
            models.Index(
                fields=["state", "retail_price"]
            ),
        ]