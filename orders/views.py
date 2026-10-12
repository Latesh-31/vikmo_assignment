from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from core.exceptions import NotFoundError, ValidationError
from core.pagination import StandardPageNumberPagination
from orders.models import Order
from orders.serializers import OrderSerializer
from orders.services import (
    create_draft_order,
    update_draft_order,
    confirm_order,
    dispatch_order,
    deliver_order,
    cancel_order,
)


class OrderListCreateView(APIView):
    pagination_class = StandardPageNumberPagination

    def get(self, request):
        queryset = Order.objects.all().prefetch_related("items").order_by("-created_at")

        dealer_id = request.query_params.get("dealer_id")
        if dealer_id:
            try:
                queryset = queryset.filter(dealer_id=int(dealer_id))
            except ValueError:
                raise ValidationError("dealer_id query param must be an integer.")

        order_status = request.query_params.get("status")
        if order_status:
            queryset = queryset.filter(status=order_status)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        if page is not None:
            serializer = OrderSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = OrderSerializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request):
        if not isinstance(request.data, dict):
            raise ValidationError("Request body must be a JSON object.")

        dealer_id = request.data.get("dealer_id")
        items_data = request.data.get("items")

        idempotency_key = request.headers.get("Idempotency-Key") or request.META.get("HTTP_IDEMPOTENCY_KEY")
        if idempotency_key:
            idempotency_key = idempotency_key.strip()

        order = create_draft_order(
            dealer_id=dealer_id,
            items_data=items_data,
            idempotency_key=idempotency_key,
            raw_body=request.body,
        )
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


class OrderDetailUpdateView(APIView):
    def get(self, request, order_number):
        order = Order.objects.filter(order_number=order_number).prefetch_related("items").first()
        if not order:
            raise NotFoundError(f"Order '{order_number}' not found.")
        return Response(OrderSerializer(order).data)

    def put(self, request, order_number):
        if not isinstance(request.data, dict) or "items" not in request.data:
            raise ValidationError(
                message="Field 'items' is required in request body.",
                details=["Field 'items' is required in request body."]
            )

        items_data = request.data.get("items")
        order = update_draft_order(order_number=order_number, items_data=items_data)
        return Response(OrderSerializer(order).data)


class OrderConfirmView(APIView):
    def post(self, request, order_number):
        order = confirm_order(order_number)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)


class OrderDispatchView(APIView):
    def post(self, request, order_number):
        order = dispatch_order(order_number)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)


class OrderDeliverView(APIView):
    def post(self, request, order_number):
        order = deliver_order(order_number)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)


class OrderCancelView(APIView):
    def post(self, request, order_number):
        order = cancel_order(order_number)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)
