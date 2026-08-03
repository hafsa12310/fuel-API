from rest_framework import serializers


class RouteRequestSerializer(
    serializers.Serializer
):
    start = serializers.CharField(
        max_length=300
    )

    finish = serializers.CharField(
        max_length=300
    )

    max_range_miles = serializers.FloatField(
        default=500,
        min_value=50,
        max_value=1000,
    )

    mpg = serializers.FloatField(
        default=10,
        min_value=1,
        max_value=100,
    )