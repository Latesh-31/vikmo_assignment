import csv
import io
from django.db.models import Q
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from core.exceptions import NotFoundError, ValidationError, DuplicateError
from core.pagination import StandardPageNumberPagination
from products.models import Product
from products.serializers import (
    ProductSerializer,
    ProductCreateSerializer,
    ProductUpdateSerializer,
)


class ProductListCreateView(APIView):
    pagination_class = StandardPageNumberPagination

    def get(self, request):
        queryset = Product.objects.all().order_by("sku")

        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(sku__icontains=search) | Q(name__icontains=search) | Q(brand__icontains=search)
            )

        category = request.query_params.get("category")
        if category:
            queryset = queryset.filter(category=category)

        vehicle = request.query_params.get("vehicle")
        if vehicle:
            queryset = queryset.filter(vehicle_fitment__icontains=vehicle)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        if page is not None:
            serializer = ProductSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = ProductSerializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request):
        if not isinstance(request.data, dict):
            raise ValidationError("Request body must be a JSON object.")
        sku = request.data.get("sku")
        if sku and isinstance(sku, str) and Product.objects.filter(sku=sku.strip()).exists():
            raise DuplicateError(f"Product with SKU '{sku.strip()}' already exists.")

        serializer = ProductCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = serializer.save()
        return Response(ProductSerializer(product).data, status=status.HTTP_201_CREATED)


class ProductDetailView(APIView):
    def get_object(self, sku):
        product = Product.objects.filter(sku=sku).first()
        if not product:
            raise NotFoundError(f"Product with SKU '{sku}' not found.")
        return product

    def get(self, request, sku):
        product = self.get_object(sku)
        return Response(ProductSerializer(product).data)

    def patch(self, request, sku):
        product = self.get_object(sku)
        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        data.pop("sku", None)  # SKU is immutable

        serializer = ProductUpdateSerializer(product, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ProductSerializer(product).data)


class InventoryUpdateView(APIView):
    def put(self, request, sku):
        product = Product.objects.filter(sku=sku).first()
        if not product:
            raise NotFoundError(f"Product with SKU '{sku}' not found.")

        if "quantity" not in request.data:
            raise ValidationError(
                message="Field 'quantity' is required.",
                details=["Field 'quantity' is required."]
            )

        raw_qty = request.data.get("quantity")
        if isinstance(raw_qty, bool) or not isinstance(raw_qty, int):
            # Check if it is a string representing an integer
            try:
                if isinstance(raw_qty, str) and raw_qty.strip().isdigit():
                    qty = int(raw_qty.strip())
                else:
                    raise ValueError()
            except Exception:
                raise ValidationError(
                    message="Quantity must be a non-negative integer.",
                    details=["Quantity must be a non-negative integer."]
                )
        else:
            qty = raw_qty

        if qty < 0:
            raise ValidationError(
                message="Quantity must be greater than or equal to 0.",
                details=["Quantity must be greater than or equal to 0."]
            )

        product.stock = qty
        product.save(update_fields=["stock", "updated_at"])
        return Response({"sku": product.sku, "quantity": product.stock}, status=status.HTTP_200_OK)


class ProductBulkUploadView(APIView):
    """
    POST /api/products/bulk-upload/
    Accepts multipart/form-data with a 'file' field containing CSV.
    CSV columns: sku, name, category, brand, vehicle_fitment, price, stock, description
    Returns: { created: N, updated: M, errors: [...] }
    """
    def post(self, request):
        if "file" not in request.FILES:
            raise ValidationError("No file uploaded. Expected 'file' in multipart/form-data.")

        uploaded_file = request.FILES["file"]
        if not uploaded_file.name.endswith(".csv"):
            raise ValidationError("File must be a CSV.")

        try:
            decoded = uploaded_file.read().decode("utf-8")
        except UnicodeDecodeError:
            raise ValidationError("CSV file must be UTF-8 encoded.")

        reader = csv.DictReader(io.StringIO(decoded))
        required_fields = {"sku", "name", "category", "brand", "vehicle_fitment", "price", "stock"}
        missing = required_fields - set(reader.fieldnames or [])
        if missing:
            raise ValidationError(f"CSV missing required columns: {', '.join(sorted(missing))}")

        created = 0
        updated = 0
        errors = []

        for i, row in enumerate(reader, start=2):  # start=2 accounts for header row
            try:
                sku = row["sku"].strip()
                name = row["name"].strip()
                category = row["category"].strip()
                brand = row["brand"].strip()
                vehicle_fitment = row["vehicle_fitment"].strip()
                price = row["price"].strip()
                stock = int(row["stock"].strip()) if row.get("stock") else 0
                description = row.get("description", "").strip()

                if not sku:
                    errors.append(f"Row {i}: SKU is required")
                    continue

                if Product.objects.filter(sku=sku).exists():
                    p = Product.objects.get(sku=sku)
                    p.name = name
                    p.category = category
                    p.brand = brand
                    p.vehicle_fitment = vehicle_fitment
                    p.price = price
                    p.stock = stock
                    p.description = description
                    p.save()
                    updated += 1
                else:
                    Product.objects.create(
                        sku=sku,
                        name=name,
                        category=category,
                        brand=brand,
                        vehicle_fitment=vehicle_fitment,
                        price=price,
                        stock=stock,
                        description=description,
                    )
                    created += 1

            except Exception as e:
                errors.append(f"Row {i}: {str(e)}")

        return Response(
            {"created": created, "updated": updated, "errors": errors},
            status=status.HTTP_200_OK if not errors else status.HTTP_207_MULTI_STATUS
        )
