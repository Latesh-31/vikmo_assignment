from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.http import Http404
from django.core.exceptions import ValidationError as DjangoValidationError


class BaseAppException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "VALIDATION_ERROR"
    default_message = "A validation error occurred."

    def __init__(self, message=None, code=None, details=None, status_code=None):
        if status_code is not None:
            self.status_code = status_code
        self.code = code or self.default_code
        self.message = message or self.default_message
        self.details = details if isinstance(details, list) else ([] if details is None else [details])
        super().__init__(detail=self.message, code=self.code)


class ValidationError(BaseAppException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "VALIDATION_ERROR"
    default_message = "Validation error."


class NotFoundError(BaseAppException):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "NOT_FOUND"
    default_message = "Resource not found."


class DuplicateError(BaseAppException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "DUPLICATE"
    default_message = "Resource already exists."


class InsufficientStockError(BaseAppException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "INSUFFICIENT_STOCK"
    default_message = "Insufficient stock available."


class InvalidTransitionError(BaseAppException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "INVALID_TRANSITION"
    default_message = "Status transition is not allowed."


class OrderLockedError(BaseAppException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "ORDER_LOCKED"
    default_message = "Order cannot be edited in its current status."


class IdempotencyConflictError(BaseAppException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "IDEMPOTENCY_CONFLICT"
    default_message = "Idempotency key reused with different request payload."


class SupplierUnavailableError(BaseAppException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "SUPPLIER_UNAVAILABLE"
    default_message = "Supplier API is unavailable."


def flatten_errors(detail):
    details = []
    if isinstance(detail, list):
        for item in detail:
            details.extend(flatten_errors(item))
    elif isinstance(detail, dict):
        for field, item in detail.items():
            for msg in flatten_errors(item):
                details.append(f"{field}: {msg}" if field != "non_field_errors" else msg)
    else:
        details.append(str(detail))
    return details


def custom_exception_handler(exc, context):
    if isinstance(exc, BaseAppException):
        return Response(
            {
                "error": {
                    "code": exc.code,
                    "message": str(exc.message),
                    "details": exc.details if isinstance(exc.details, list) else [],
                }
            },
            status=exc.status_code,
        )

    if isinstance(exc, Http404):
        return Response(
            {
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Resource not found.",
                    "details": [],
                }
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, DjangoValidationError):
        return Response(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Validation error.",
                    "details": [str(exc)],
                }
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Let DRF handle standard exceptions first to determine status_code
    response = exception_handler(exc, context)

    if response is not None:
        err_code = "VALIDATION_ERROR"
        if response.status_code == status.HTTP_404_NOT_FOUND:
            err_code = "NOT_FOUND"
            msg = "Resource not found."
            details = []
        elif response.status_code == status.HTTP_400_BAD_REQUEST:
            err_code = "VALIDATION_ERROR"
            details = flatten_errors(response.data)
            msg = details[0] if details else "Validation error."
        elif response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
            err_code = "METHOD_NOT_ALLOWED"
            msg = "Method not allowed."
            details = []
        else:
            msg = str(response.data) if isinstance(response.data, (str, list)) else "An error occurred."
            details = flatten_errors(response.data) if isinstance(response.data, (dict, list)) else []

        return Response(
            {
                "error": {
                    "code": err_code,
                    "message": msg,
                    "details": details if isinstance(details, list) else [],
                }
            },
            status=response.status_code,
        )

    return None
