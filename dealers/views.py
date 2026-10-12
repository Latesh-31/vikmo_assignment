from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from core.exceptions import NotFoundError
from core.pagination import StandardPageNumberPagination
from dealers.models import Dealer
from dealers.serializers import DealerSerializer, DealerCreateSerializer


class DealerListCreateView(APIView):
    pagination_class = StandardPageNumberPagination

    def get(self, request):
        queryset = Dealer.objects.all().order_by("id")
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        if page is not None:
            serializer = DealerSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = DealerSerializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request):
        if not isinstance(request.data, dict):
            raise ValidationError("Request body must be a JSON object.")
        dealer_code = request.data.get("dealer_code")
        if dealer_code and isinstance(dealer_code, str) and Dealer.objects.filter(dealer_code=dealer_code.strip()).exists():
            from core.exceptions import DuplicateError
            raise DuplicateError(f"Dealer with code '{dealer_code.strip()}' already exists.")

        serializer = DealerCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dealer = serializer.save()
        return Response(DealerSerializer(dealer).data, status=status.HTTP_201_CREATED)


class DealerDetailView(APIView):
    def get(self, request, id):
        dealer = Dealer.objects.filter(id=id).first()
        if not dealer:
            raise NotFoundError(f"Dealer with id {id} not found.")
        return Response(DealerSerializer(dealer).data)
