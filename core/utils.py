from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from core.exceptions import ValidationError


def money_str(value) -> str:
    if value is None:
        return "0.00"
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return f"{value:.2f}"


def calculate_line_tax(line_subtotal: Decimal) -> Decimal:
    tax = line_subtotal * Decimal("0.18")
    return tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validate_price(price_raw) -> Decimal:
    """Validates that price is a positive number with at most 2 decimal places."""
    try:
        val = Decimal(str(price_raw))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(
            message="Price must be a valid positive decimal number.",
            details=["Price must be a valid decimal number."]
        )

    if val <= Decimal("0"):
        raise ValidationError(
            message="Price must be greater than zero.",
            details=["Price must be greater than zero."]
        )

    # Check decimal places
    # as_tuple().exponent: -2 means 2 decimal places, -3 means 3 decimal places, 0 means integer
    if val.as_tuple().exponent < -2:
        raise ValidationError(
            message="Price can have at most 2 decimal places.",
            details=["Price can have at most 2 decimal places."]
        )

    return val.quantize(Decimal("0.01"))
