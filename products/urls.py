from django.urls import path
from products.views import (
    ProductListCreateView,
    ProductDetailView,
    InventoryUpdateView,
)

urlpatterns = [
    path("products/", ProductListCreateView.as_view(), name="product-list-create"),
    path("products/<str:sku>/", ProductDetailView.as_view(), name="product-detail"),
    path("inventory/<str:sku>/", InventoryUpdateView.as_view(), name="inventory-update"),
]
