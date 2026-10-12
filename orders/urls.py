from django.urls import path
from orders.views import (
    OrderListCreateView,
    OrderDetailUpdateView,
    OrderConfirmView,
    OrderDispatchView,
    OrderDeliverView,
    OrderCancelView,
)

urlpatterns = [
    path("orders/", OrderListCreateView.as_view(), name="order-list-create"),
    path("orders/<str:order_number>/", OrderDetailUpdateView.as_view(), name="order-detail-update"),
    path("orders/<str:order_number>/confirm/", OrderConfirmView.as_view(), name="order-confirm"),
    path("orders/<str:order_number>/dispatch/", OrderDispatchView.as_view(), name="order-dispatch"),
    path("orders/<str:order_number>/deliver/", OrderDeliverView.as_view(), name="order-deliver"),
    path("orders/<str:order_number>/cancel/", OrderCancelView.as_view(), name="order-cancel"),
]
