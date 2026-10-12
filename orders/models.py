from django.db import models


class OrderStatus(models.TextChoices):
    DRAFT = "DRAFT", "DRAFT"
    CONFIRMED = "CONFIRMED", "CONFIRMED"
    DISPATCHED = "DISPATCHED", "DISPATCHED"
    DELIVERED = "DELIVERED", "DELIVERED"
    CANCELLED = "CANCELLED", "CANCELLED"


class Order(models.Model):
    order_number = models.CharField(max_length=64, primary_key=True)
    dealer = models.ForeignKey("dealers.Dealer", on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(
        max_length=32,
        choices=OrderStatus.choices,
        default=OrderStatus.DRAFT,
        db_index=True,
    )
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order_number} ({self.status})"


class OrderItem(models.Model):
    id = models.BigAutoField(primary_key=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    sku = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    line_tax = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.order_id} - {self.sku} x {self.quantity}"


class DailyOrderSequence(models.Model):
    date = models.DateField(primary_key=True)
    last_sequence = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.date}: {self.last_sequence}"


class IdempotencyKey(models.Model):
    key = models.CharField(max_length=255, primary_key=True)
    request_hash = models.CharField(max_length=64)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.key} -> {self.order_id}"
