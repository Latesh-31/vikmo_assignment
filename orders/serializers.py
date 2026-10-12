from rest_framework import serializers
from core.utils import money_str
from orders.models import Order, OrderItem


class OrderItemSerializer(serializers.ModelSerializer):
    unit_price = serializers.SerializerMethodField()
    line_subtotal = serializers.SerializerMethodField()
    line_tax = serializers.SerializerMethodField()
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            "sku",
            "name",
            "quantity",
            "unit_price",
            "line_subtotal",
            "line_tax",
            "line_total",
        ]

    def get_unit_price(self, obj):
        return money_str(obj.unit_price)

    def get_line_subtotal(self, obj):
        return money_str(obj.line_subtotal)

    def get_line_tax(self, obj):
        return money_str(obj.line_tax)

    def get_line_total(self, obj):
        return money_str(obj.line_total)


class OrderSerializer(serializers.ModelSerializer):
    dealer_id = serializers.IntegerField(source="dealer.id")
    items = OrderItemSerializer(many=True, read_only=True)
    subtotal = serializers.SerializerMethodField()
    tax_total = serializers.SerializerMethodField()
    grand_total = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "order_number",
            "dealer_id",
            "status",
            "items",
            "subtotal",
            "tax_total",
            "grand_total",
            "created_at",
            "updated_at",
        ]

    def get_subtotal(self, obj):
        return money_str(obj.subtotal)

    def get_tax_total(self, obj):
        return money_str(obj.tax_total)

    def get_grand_total(self, obj):
        return money_str(obj.grand_total)
