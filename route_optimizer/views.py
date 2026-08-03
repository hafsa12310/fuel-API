from django.shortcuts import render

# Create your views here.
from requests import RequestException

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    RouteRequestSerializer,
)
from .services import (
    RoutingError,
    build_result,
)


class OptimizedRouteView(APIView):
    def post(self, request):
        serializer = RouteRequestSerializer(
            data=request.data
        )

        serializer.is_valid(
            raise_exception=True
        )

        try:
            result = build_result(
                **serializer.validated_data
            )

            return Response(result)

        except RoutingError as error:
            return Response(
                {
                    "detail": str(error)
                },
                status=(
                    status
                    .HTTP_422_UNPROCESSABLE_ENTITY
                ),
            )

        except RequestException:
            return Response(
                {
                    "detail": (
                        "Routing provider "
                        "is unavailable"
                    )
                },
                status=(
                    status
                    .HTTP_503_SERVICE_UNAVAILABLE
                ),
            )