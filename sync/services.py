import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
import requests
from django.conf import settings
from django.db import transaction

from core.exceptions import SupplierUnavailableError
from products.models import Product


def parse_datetime(dt_str):
    if not dt_str:
        return datetime.min
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        return datetime.fromisoformat(dt_str)
    except Exception:
        return datetime.min


def validate_supplier_price(price_raw):
    """Returns Decimal if valid positive number with <= 2 decimals, else None."""
    if price_raw is None:
        return None
    try:
        val = Decimal(str(price_raw))
    except (InvalidOperation, ValueError, TypeError):
        return None

    if val <= Decimal("0"):
        return None

    if val.as_tuple().exponent < -2:
        return None

    return val.quantize(Decimal("0.01"))


def sync_supplier_catalogue():
    supplier_url = getattr(settings, "SUPPLIER_API_URL", "http://127.0.0.1:8099").rstrip("/")
    api_key = getattr(settings, "SUPPLIER_API_KEY", "")

    headers = {"X-Api-Key": api_key}
    cursor = None
    all_raw_items = []
    pages_fetched = 0
    requests_made = 0

    session = requests.Session()

    while True:
        url = f"{supplier_url}/v1/products"
        params = {"limit": 20}
        if cursor:
            params["cursor"] = cursor

        success = False
        response_body = None

        # At most 5 attempts per page
        for attempt in range(1, 6):
            requests_made += 1
            try:
                resp = session.get(url, params=params, headers=headers, timeout=20)
            except (requests.RequestException, Exception):
                if attempt == 5:
                    raise SupplierUnavailableError(
                        message="Supplier API request failed after 5 attempts.",
                        details=["Connection error to supplier API."]
                    )
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue

            if resp.status_code == 200:
                try:
                    response_body = resp.json()
                    success = True
                    break
                except Exception:
                    if attempt == 5:
                        raise SupplierUnavailableError(
                            message="Invalid JSON response from supplier API.",
                            details=["Failed to parse JSON."]
                        )
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue

            elif resp.status_code == 401:
                # Key rejected, fail immediately
                raise SupplierUnavailableError(
                    message="Supplier API key unauthorized.",
                    details=["Supplier returned HTTP 401."]
                )

            elif resp.status_code == 429:
                if attempt == 5:
                    raise SupplierUnavailableError(
                        message="Supplier API rate limit exceeded.",
                        details=["Supplier returned HTTP 429 repeatedly."]
                    )
                retry_after = resp.headers.get("Retry-After")
                try:
                    wait_seconds = float(retry_after) if retry_after else 1.0
                except (ValueError, TypeError):
                    wait_seconds = 1.0
                time.sleep(max(wait_seconds, 1.0))
                continue

            elif 500 <= resp.status_code < 600:
                if attempt == 5:
                    raise SupplierUnavailableError(
                        message=f"Supplier API server error {resp.status_code}.",
                        details=[f"Supplier returned HTTP {resp.status_code}."]
                    )
                time.sleep(0.5 * (2 ** (attempt - 1)))
                continue

            else:
                # Other 4xx or unexpected status codes
                raise SupplierUnavailableError(
                    message=f"Supplier API returned unexpected HTTP {resp.status_code}.",
                    details=[f"Status code {resp.status_code}"]
                )

        if not success or response_body is None:
            raise SupplierUnavailableError(
                message="Supplier API page fetch failed.",
                details=["Could not fetch page."]
            )

        pages_fetched += 1
        items = response_body.get("items", [])
        all_raw_items.extend(items)

        cursor = response_body.get("next_cursor")
        if not cursor:
            break

    # Process items:
    # 4. Filter invalid items: missing or empty sku, or price not positive with <= 2 decimals
    rejected = []
    valid_items = []

    for item in all_raw_items:
        supplier_sku = item.get("supplier_sku") or ""
        sku = item.get("sku")

        if not sku or not isinstance(sku, str) or not sku.strip():
            rejected.append({"supplier_sku": supplier_sku, "reason": "missing sku"})
            continue

        price_raw = item.get("price")
        validated_price = validate_supplier_price(price_raw)
        if validated_price is None:
            rejected.append({"supplier_sku": supplier_sku, "reason": "invalid price"})
            continue

        item_copy = dict(item)
        item_copy["sku"] = sku.strip()
        item_copy["price_dec"] = validated_price
        valid_items.append(item_copy)

    # 5. Duplicates across pages: keep latest updated_at
    latest_by_sku = {}
    for item in valid_items:
        sku = item["sku"]
        item_dt = parse_datetime(item.get("updated_at"))
        if sku not in latest_by_sku:
            latest_by_sku[sku] = (item_dt, item)
        else:
            prev_dt, _ = latest_by_sku[sku]
            if item_dt >= prev_dt:
                latest_by_sku[sku] = (item_dt, item)

    deduped_items = [v[1] for v in latest_by_sku.values()]

    # 6. Apply in single atomic transaction:
    created_count = 0
    updated_count = 0
    unchanged_count = 0

    with transaction.atomic():
        all_skus = [it["sku"] for it in deduped_items]
        existing_products = {p.sku: p for p in Product.objects.filter(sku__in=all_skus)}

        to_create = []
        to_update = []

        for it in deduped_items:
            sku = it["sku"]
            name = (it.get("name") or "").strip()
            category = (it.get("category") or "").strip()
            brand = (it.get("brand") or "").strip()
            vehicle_fitment = (it.get("vehicle_fitment") or "").strip()
            description = (it.get("description") or "").strip()
            price_dec = it["price_dec"]

            if sku not in existing_products:
                to_create.append(
                    Product(
                        sku=sku,
                        name=name,
                        category=category,
                        brand=brand,
                        vehicle_fitment=vehicle_fitment,
                        price=price_dec,
                        stock=0,  # Never change our stock; new products get 0
                        description=description,
                    )
                )
                created_count += 1
            else:
                p = existing_products[sku]
                # Check if any field differs
                if (
                    p.name != name
                    or p.category != category
                    or p.brand != brand
                    or p.vehicle_fitment != vehicle_fitment
                    or p.description != description
                    or p.price != price_dec
                ):
                    p.name = name
                    p.category = category
                    p.brand = brand
                    p.vehicle_fitment = vehicle_fitment
                    p.description = description
                    p.price = price_dec
                    # NEVER modify p.stock
                    to_update.append(p)
                    updated_count += 1
                else:
                    unchanged_count += 1

        if to_create:
            Product.objects.bulk_create(to_create)
        if to_update:
            Product.objects.bulk_update(
                to_update,
                fields=["name", "category", "brand", "vehicle_fitment", "price", "description", "updated_at"],
            )

    return {
        "created": created_count,
        "updated": updated_count,
        "unchanged": unchanged_count,
        "rejected": rejected,
        "pages_fetched": pages_fetched,
        "requests_made": requests_made,
    }
