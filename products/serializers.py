from rest_framework import serializers
from decimal import Decimal
from core.exceptions import DuplicateError, ValidationError
from core.utils import money_str, validate_price
from products.models import Product


class ProductSerializer(serializers.ModelSerializer):
    price = serializers.SerializerMethodField()
    stock = serializers.IntegerField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "sku",
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "stock",
            "description",
        ]

    def get_price(self, obj):
        return money_str(obj.price)


class ProductCreateSerializer(serializers.ModelSerializer):
    price = serializers.CharField()

    class Meta:
        model = Product
        fields = [
            "sku",
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "description",
        ]

    def validate_sku(self, value):
        val = value.strip()
        if not val:
            raise ValidationError("SKU cannot be empty.")
        return val

    def validate_price(self, value):
        return validate_price(value)

    def validate_name(self, value):
        if not value or not value.strip():
            raise ValidationError("Product name cannot be empty.")
        return value.strip()

    def create(self, validated_data):
        validated_data["stock"] = 0
        return super().create(validated_data)


class ProductUpdateSerializer(serializers.ModelSerializer):
    price = serializers.CharField(required=False)

    class Meta:
        model = Product
        fields = [
            "name",
            "category",
            "brand",
            "vehicle_fitment",
            "price",
            "description",
        ]

    def validate_price(self, value):
        return validate_price(value)
