from django.urls import path
from sync.views import SupplierSyncView

urlpatterns = [
    path("sync/supplier/", SupplierSyncView.as_view(), name="supplier-sync"),
]
