from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from sync.services import sync_supplier_catalogue


class SupplierSyncView(APIView):
    def post(self, request):
        result = sync_supplier_catalogue()
        return Response(result, status=status.HTTP_200_OK)
