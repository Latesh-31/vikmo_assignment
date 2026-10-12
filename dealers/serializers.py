from decimal import Decimal
from rest_framework import serializers
from core.exceptions import DuplicateError, ValidationError
from core.utils import money_str
from dealers.models import Dealer


class DealerSerializer(serializers.ModelSerializer):
    credit_limit = serializers.SerializerMethodField()

    class Meta:
        model = Dealer
        fields = [
            "id",
            "dealer_code",
            "name",
            "city",
            "phone",
            "email",
            "gstin",
            "credit_limit",
        ]

    def get_credit_limit(self, obj):
        return money_str(obj.credit_limit)


class DealerCreateSerializer(serializers.ModelSerializer):
    credit_limit = serializers.CharField(required=False, default="0.00")

    class Meta:
        model = Dealer
        fields = [
            "id",
            "dealer_code",
            "name",
            "city",
            "phone",
            "email",
            "gstin",
            "credit_limit",
        ]
        read_only_fields = ["id"]

    def validate_dealer_code(self, value):
        val = value.strip()
        if not val:
            raise ValidationError("dealer_code cannot be empty.")
        return val

    def validate_name(self, value):
        val = value.strip()
        if not val:
            raise ValidationError("name cannot be empty.")
        return val

    def validate_credit_limit(self, value):
        if value is None or value == "":
            return Decimal("0.00")
        try:
            val = Decimal(str(value))
        except Exception:
            raise ValidationError("credit_limit must be a valid decimal number.")
        if val < Decimal("0.00"):
            raise ValidationError("credit_limit cannot be negative.")
        return val.quantize(Decimal("0.01"))
