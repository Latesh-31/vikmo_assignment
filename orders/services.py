import hashlib
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.db import transaction, IntegrityError
from django.utils import timezone

from core.exceptions import (
    NotFoundError,
    ValidationError,
    InsufficientStockError,
    InvalidTransitionError,
    OrderLockedError,
    IdempotencyConflictError,
)
from core.utils import calculate_line_tax
from dealers.models import Dealer
from products.models import Product
from orders.models import (
    Order,
    OrderItem,
    OrderStatus,
    DailyOrderSequence,
    IdempotencyKey,
)


def generate_order_number() -> str:
    """Generates a sequential, concurrency-safe order number ORD-YYYYMMDD-NNNN in Asia/Kolkata timezone."""
    now_kolkata = timezone.now().astimezone(ZoneInfo("Asia/Kolkata"))
    today = now_kolkata.date()

    # Lock or create the sequence row for today
    seq, _ = DailyOrderSequence.objects.select_for_update().get_or_create(
        date=today, defaults={"last_sequence": 0}
    )
    seq.last_sequence += 1
    seq.save(update_fields=["last_sequence"])

    return f"ORD-{today.strftime('%Y%m%d')}-{seq.last_sequence:04d}"


def validate_and_calculate_items(items_data):
    """
    Validates items_data and calculates line subtotals, taxes, and totals based on current catalogue.
    Returns: (calculated_items_list, subtotal, tax_total, grand_total)
    """
    if not isinstance(items_data, list) or len(items_data) == 0:
        raise ValidationError(
            message="At least one item is required in the order.",
            details=["Items list cannot be empty."]
        )

    seen_skus = set()
    sku_list = []
    qty_map = {}

    for idx, item in enumerate(items_data):
        if not isinstance(item, dict):
            raise ValidationError(
                message=f"Item at index {idx} must be an object.",
                details=[f"Item at index {idx} must be an object."]
            )

        sku = item.get("sku")
        if not sku or not isinstance(sku, str) or not sku.strip():
            raise ValidationError(
                message=f"Item at index {idx} missing valid 'sku'.",
                details=[f"Item at index {idx} missing valid 'sku'."]
            )
        sku = sku.strip()

        if sku in seen_skus:
            raise ValidationError(
                message=f"Duplicate SKU '{sku}' in order items.",
                details=[f"Duplicate SKU '{sku}' in order items."]
            )
        seen_skus.add(sku)
        sku_list.append(sku)

        raw_qty = item.get("quantity")
        if isinstance(raw_qty, bool) or not isinstance(raw_qty, int):
            try:
                if isinstance(raw_qty, str) and raw_qty.strip().isdigit():
                    qty = int(raw_qty.strip())
                else:
                    raise ValueError()
            except Exception:
                raise ValidationError(
                    message=f"Quantity for SKU '{sku}' must be an integer >= 1.",
                    details=[f"Quantity for SKU '{sku}' must be an integer >= 1."]
                )
        else:
            qty = raw_qty

        if qty < 1:
            raise ValidationError(
                message=f"Quantity for SKU '{sku}' must be at least 1.",
                details=[f"Quantity for SKU '{sku}' must be at least 1."]
            )

        qty_map[sku] = qty

    # Fetch products from database
    products = {p.sku: p for p in Product.objects.filter(sku__in=sku_list)}
    missing_skus = [sku for sku in sku_list if sku not in products]
    if missing_skus:
        raise ValidationError(
            message=f"Unknown SKU(s) in order: {', '.join(missing_skus)}",
            details=[f"SKU '{s}' not found in catalogue." for s in missing_skus]
        )

    calculated_items = []
    subtotal = Decimal("0.00")
    tax_total = Decimal("0.00")

    for sku in sku_list:
        product = products[sku]
        qty = qty_map[sku]
        unit_price = product.price
        line_subtotal = unit_price * qty
        line_tax = calculate_line_tax(line_subtotal)
        line_total = line_subtotal + line_tax

        subtotal += line_subtotal
        tax_total += line_tax

        calculated_items.append({
            "sku": sku,
            "name": product.name,
            "quantity": qty,
            "unit_price": unit_price,
            "line_subtotal": line_subtotal,
            "line_tax": line_tax,
            "line_total": line_total,
        })

    grand_total = subtotal + tax_total
    return calculated_items, subtotal, tax_total, grand_total


def create_draft_order(dealer_id, items_data, idempotency_key=None, raw_body=None) -> Order:
    """Creates a DRAFT order with full idempotency support."""
    # Validate dealer
    if dealer_id is None:
        raise ValidationError(
            message="dealer_id is required.",
            details=["dealer_id is required."]
        )

    try:
        dealer = Dealer.objects.filter(id=dealer_id).first()
    except Exception:
        raise ValidationError(
            message="Invalid dealer_id.",
            details=["dealer_id must be a valid ID."]
        )

    if not dealer:
        raise ValidationError(
            message=f"Dealer with id {dealer_id} does not exist.",
            details=[f"Dealer with id {dealer_id} does not exist."]
        )

    calculated_items, subtotal, tax_total, grand_total = validate_and_calculate_items(items_data)

    request_hash = ""
    if idempotency_key:
        if raw_body is not None:
            if isinstance(raw_body, str):
                request_hash = hashlib.sha256(raw_body.encode("utf-8")).hexdigest()
            else:
                request_hash = hashlib.sha256(raw_body).hexdigest()
        else:
            request_hash = hashlib.sha256(f"{dealer_id}:{items_data}".encode("utf-8")).hexdigest()

    with transaction.atomic():
        if idempotency_key:
            existing_key = IdempotencyKey.objects.select_for_update().filter(key=idempotency_key).first()
            if existing_key:
                if existing_key.request_hash != request_hash:
                    raise IdempotencyConflictError(
                        message="Idempotency key reused with different request payload.",
                        details=["Idempotency key reused with different request payload."]
                    )
                return existing_key.order

        order_number = generate_order_number()

        order = Order.objects.create(
            order_number=order_number,
            dealer=dealer,
            status=OrderStatus.DRAFT,
            subtotal=subtotal,
            tax_total=tax_total,
            grand_total=grand_total,
        )

        item_objects = [
            OrderItem(
                order=order,
                sku=it["sku"],
                name=it["name"],
                quantity=it["quantity"],
                unit_price=it["unit_price"],
                line_subtotal=it["line_subtotal"],
                line_tax=it["line_tax"],
                line_total=it["line_total"],
            )
            for it in calculated_items
        ]
        OrderItem.objects.bulk_create(item_objects)

        if idempotency_key:
            try:
                IdempotencyKey.objects.create(
                    key=idempotency_key,
                    request_hash=request_hash,
                    order=order,
                )
            except IntegrityError:
                # Concurrent request created this key just now
                existing = IdempotencyKey.objects.filter(key=idempotency_key).first()
                if existing and existing.request_hash != request_hash:
                    raise IdempotencyConflictError(
                        message="Idempotency key reused with different request payload.",
                        details=["Idempotency key reused with different request payload."]
                    )
                if existing and existing.order:
                    return existing.order

        return order


def update_draft_order(order_number: str, items_data) -> Order:
    """Replaces all items in a DRAFT order and recalculates prices from current catalogue."""
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(order_number=order_number).first()
        if not order:
            raise NotFoundError(f"Order '{order_number}' not found.")

        if order.status != OrderStatus.DRAFT:
            raise OrderLockedError(
                message=f"Order '{order_number}' is not in DRAFT status and cannot be edited.",
                details=[f"Order status is {order.status}."]
            )

        calculated_items, subtotal, tax_total, grand_total = validate_and_calculate_items(items_data)

        order.items.all().delete()

        item_objects = [
            OrderItem(
                order=order,
                sku=it["sku"],
                name=it["name"],
                quantity=it["quantity"],
                unit_price=it["unit_price"],
                line_subtotal=it["line_subtotal"],
                line_tax=it["line_tax"],
                line_total=it["line_total"],
            )
            for it in calculated_items
        ]
        OrderItem.objects.bulk_create(item_objects)

        order.subtotal = subtotal
        order.tax_total = tax_total
        order.grand_total = grand_total
        order.save(update_fields=["subtotal", "tax_total", "grand_total", "updated_at"])

        return order


def confirm_order(order_number: str) -> Order:
    """Transition DRAFT -> CONFIRMED with concurrency-safe all-or-nothing stock deduction."""
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(order_number=order_number).first()
        if not order:
            raise NotFoundError(f"Order '{order_number}' not found.")

        if order.status != OrderStatus.DRAFT:
            raise InvalidTransitionError(
                message=f"Cannot confirm order in status '{order.status}'. Allowed only from DRAFT.",
                details=[f"Order '{order_number}' status is {order.status}."]
            )

        items = list(order.items.all())
        skus = sorted([it.sku for it in items])
        # Concurrency safety: acquire row locks on all required products in sorted order to avoid deadlock
        products = {p.sku: p for p in Product.objects.select_for_update().filter(sku__in=skus)}

        short_lines = []
        for it in items:
            product = products.get(it.sku)
            available = product.stock if product else 0
            if available < it.quantity:
                short_lines.append({
                    "sku": it.sku,
                    "name": product.name if product else it.name,
                    "available": available,
                    "requested": it.quantity,
                })

        if short_lines:
            messages = [
                f"Insufficient stock for {s['name']}. Available: {s['available']}, Requested: {s['requested']}"
                for s in short_lines
            ]
            details = [
                {"sku": s["sku"], "requested": s["requested"], "available": s["available"]}
                for s in short_lines
            ]
            raise InsufficientStockError(
                message=". ".join(messages),
                details=details,
            )

        # Deduct stock
        for it in items:
            product = products[it.sku]
            product.stock -= it.quantity
            product.save(update_fields=["stock", "updated_at"])

        order.status = OrderStatus.CONFIRMED
        order.save(update_fields=["status", "updated_at"])
        return order


def dispatch_order(order_number: str) -> Order:
    """Transition CONFIRMED -> DISPATCHED."""
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(order_number=order_number).first()
        if not order:
            raise NotFoundError(f"Order '{order_number}' not found.")

        if order.status != OrderStatus.CONFIRMED:
            raise InvalidTransitionError(
                message=f"Cannot dispatch order in status '{order.status}'. Allowed only from CONFIRMED.",
                details=[f"Order '{order_number}' status is {order.status}."]
            )

        order.status = OrderStatus.DISPATCHED
        order.save(update_fields=["status", "updated_at"])
        return order


def deliver_order(order_number: str) -> Order:
    """Transition DISPATCHED -> DELIVERED."""
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(order_number=order_number).first()
        if not order:
            raise NotFoundError(f"Order '{order_number}' not found.")

        if order.status != OrderStatus.DISPATCHED:
            raise InvalidTransitionError(
                message=f"Cannot deliver order in status '{order.status}'. Allowed only from DISPATCHED.",
                details=[f"Order '{order_number}' status is {order.status}."]
            )

        order.status = OrderStatus.DELIVERED
        order.save(update_fields=["status", "updated_at"])
        return order


def cancel_order(order_number: str) -> Order:
    """Transition DRAFT -> CANCELLED or CONFIRMED -> CANCELLED (restores stock exactly once)."""
    with transaction.atomic():
        order = Order.objects.select_for_update().filter(order_number=order_number).first()
        if not order:
            raise NotFoundError(f"Order '{order_number}' not found.")

        if order.status not in (OrderStatus.DRAFT, OrderStatus.CONFIRMED):
            raise InvalidTransitionError(
                message=f"Cannot cancel order in status '{order.status}'. Allowed only from DRAFT or CONFIRMED.",
                details=[f"Order '{order_number}' status is {order.status}."]
            )

        if order.status == OrderStatus.CONFIRMED:
            items = list(order.items.all())
            skus = sorted([it.sku for it in items])
            products = {p.sku: p for p in Product.objects.select_for_update().filter(sku__in=skus)}
            for it in items:
                product = products.get(it.sku)
                if product:
                    product.stock += it.quantity
                    product.save(update_fields=["stock", "updated_at"])

        order.status = OrderStatus.CANCELLED
        order.save(update_fields=["status", "updated_at"])
        return order
