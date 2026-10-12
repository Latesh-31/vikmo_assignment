# VIKMO DealerDesk — Implementation Plan

## Project Overview
- **Framework**: Django 4.2+ with Django REST Framework
- **Database**: PostgreSQL (required)
- **Language**: Python 3.11+
- **Track**: Django (full implementation) — §4,5,6,7,8 required; §9,10 optional
- **Starter**: Minimal Django project with health check, settings, empty seed_data

---

## Phase 1: Foundation & Data Models

### 1.1 Create Django Apps
```
core/           # Existing - keep for health, add models here or split
products/       # Products & Inventory
dealers/        # Dealers
orders/         # Orders (complex business logic)
sync/           # Supplier sync
```

**Decision**: Keep models in `core/models.py` for simplicity, or split by domain. I'll split for maintainability.

### 1.2 Models

**Product** (`products/models.py`)
```python
sku (CharField, unique, max_length=20, primary_key)
name, category, brand, vehicle_fitment (CharField)
price (DecimalField, max_digits=10, decimal_places=2)
stock (PositiveIntegerField, default=0)
description (TextField, blank=True)
created_at, updated_at (DateTimeField auto)
```

**Dealer** (`dealers/models.py`)
```python
id (BigAutoField, pk)
dealer_code (CharField, unique, max_length=20)
name, city, phone, email, gstin (CharField, blank=True)
credit_limit (DecimalField, max_digits=12, decimal_places=2)
created_at (DateTimeField auto)
```

**Order** (`orders/models.py`)
```python
order_number (CharField, unique, max_length=30)  # ORD-YYYYMMDD-NNNN
dealer (FK to Dealer)
status (CharField, choices: DRAFT, CONFIRMED, DISPATCHED, DELIVERED, CANCELLED)
subtotal, tax_total, grand_total (DecimalField, 10, 2)
created_at, updated_at (DateTimeField)
```

**OrderItem** (`orders/models.py`)
```python
order (FK to Order, related_name='items')
sku (CharField, max_length=20)  # Not FK to allow historical pricing
name (CharField)  # Snapshot at confirm time
quantity (PositiveIntegerField)
unit_price (DecimalField, 10, 2)  # Locked at confirm
line_subtotal, line_tax, line_total (DecimalField, 10, 2)
```

**IdempotencyKey** (`orders/models.py`)
```python
key (CharField, unique, max_length=64)
request_hash (CharField, max_length=64)  # SHA256 of request body
order (FK to Order, nullable)
created_at (DateTimeField auto)
```

### 1.3 Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

---

## Phase 2: Seed Data Command

### 2.1 Implement `seed_data` (idempotent)
- Load `catalogue.csv` → Products (upsert on sku, preserve stock only if new)
- Load `dealers.csv` → Dealers (upsert on dealer_code)
- Load `lead_times.csv` → LeadTime model (if needed for forecasting)
- Use `bulk_create` with `ignore_conflicts=True` + update existing
- Running twice must not duplicate

---

## Phase 3: Products API (§4)

### 3.1 Serializers
- `ProductSerializer`: all fields, price as string "1459.50"
- `ProductCreateSerializer`: exclude stock (defaults to 0)

### 3.2 Views
- `ProductListCreateAPIView`:
  - GET: paginated, filters (search, category, vehicle)
  - POST: validate price > 0, max 2 decimals; duplicate SKU → 409 DUPLICATE
- `ProductDetailAPIView`:
  - GET: 200 or 404
  - PATCH: partial update, SKU immutable

### 3.3 URLs
```
/api/products/
/api/products/{sku}/
```

---

## Phase 4: Inventory API (§5)

### 4.1 View
- `InventoryUpdateAPIView` (PUT):
  - Body: `{quantity: int >= 0, reason: string}`
  - Sets stock to exact value
  - Unknown SKU → 404
  - Response: `{sku, quantity}`

### 4.2 URL
```
/api/inventory/{sku}/
```

---

## Phase 5: Dealers API (§6)

### 5.1 Serializers
- `DealerSerializer`: all fields, credit_limit as string
- `DealerCreateSerializer`: dealer_code, name required

### 5.2 Views
- `DealerListCreateAPIView`: GET paginated, POST create
- `DealerDetailAPIView`: GET by id

### 5.3 URL
```
/api/dealers/
/api/dealers/{id}/
```

---

## Phase 6: Orders API (§7) — CORE COMPLEXITY

### 6.1 Serializers
- `OrderItemSerializer`: sku, name, quantity, unit_price, line_subtotal, line_tax, line_total (all money as strings)
- `OrderSerializer`: all order fields + nested items
- `OrderCreateSerializer`: dealer_id, items[{sku, quantity}]
- `OrderUpdateSerializer`: items[] (replaces all)

### 6.2 Views & Business Logic

**POST /api/orders/** — Create DRAFT
- Validate: dealer exists, ≥1 item, qty≥1, SKUs exist, no duplicate SKUs
- Calculate line_subtotal = unit_price × qty (current catalogue price)
- line_tax = line_subtotal × 0.18, ROUND_HALF_UP per line
- line_total = line_subtotal + line_tax
- subtotal = Σline_subtotal, tax_total = Σline_tax, grand_total = subtotal + tax_total
- Generate order_number: ORD-YYYYMMDD-NNNN (Asia/Kolkata date, daily sequence)
- Idempotency-Key header support:
  - Same key + same body → return existing (200 or 201)
  - Same key + different body → 409 IDEMPOTENCY_CONFLICT
  - Use atomic transaction + select_for_update on IdempotencyKey
- **Concurrency**: Use `select_for_update(nowait=True)` on IdempotencyKey

**GET /api/orders/** — List with pagination, filters (dealer_id, status)

**GET /api/orders/{order_number}/** — Detail

**PUT /api/orders/{order_number}/** — Replace items (DRAFT only)
- Validate same as create
- Recalculate all prices from current catalogue
- 409 ORDER_LOCKED if not DRAFT

**Status Transitions** (all POST):
- `/confirm/` : DRAFT → CONFIRMED
  - **All-or-nothing stock check**: For each line, verify stock ≥ qty
  - If any fail: 409 INSUFFICIENT_STOCK with details for ALL short lines
  - Use `select_for_update()` on Product rows to lock stock
  - Deduct stock, lock unit_price, set status CONFIRMED
- `/dispatch/` : CONFIRMED → DISPATCHED
- `/deliver/` : DISPATCHED → DELIVERED
- `/cancel/` :
  - DRAFT → CANCELLED (no stock change)
  - CONFIRMED → CANCELLED (restore stock exactly once)
  - DISPATCHED/DELIVERED/CANCELLED → 409 INVALID_TRANSITION

### 6.3 Concurrency Strategy
- Stock deduction: `Product.objects.select_for_update().filter(sku__in=skus)`
- Order number generation: Use a `DailyOrderSequence` model with `select_for_update`
- Idempotency: Unique constraint on key + request_hash; atomic upsert

### 6.4 GST Calculation (ROUND_HALF_UP)
```python
from decimal import Decimal, ROUND_HALF_UP
line_tax = (line_subtotal * Decimal('0.18')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
```

---

## Phase 7: Supplier Sync (§8)

### 7.1 Sync Service (`sync/services.py`)
```python
def sync_supplier() -> dict:
    # 1. Fetch all pages with cursor pagination
    # 2. Retry logic: max 5 attempts per request
    #    - 429: wait Retry-After seconds, retry same request
    #    - 5xx/connection error: exponential backoff, retry
    #    - 401: fail immediately → 502 SUPPLIER_UNAVAILABLE
    # 3. Collect all items, deduplicate by sku (keep latest updated_at)
    # 4. Filter invalid: missing/empty sku, price not positive with ≤2 decimals
    # 5. All-or-nothing: if any request fails after 5 attempts → rollback, 502
    # 6. Apply changes in single transaction:
    #    - new SKU → create Product(stock=0)
    #    - existing SKU: update name, category, brand, vehicle_fitment, description, price if changed
    #    - never change stock
    # 7. Return counts: created, updated, unchanged, rejected, pages_fetched, requests_made
```

### 7.2 View
- `POST /api/sync/supplier/` — runs sync, returns 200 with summary or 502

### 7.3 Configuration
- Settings: `SUPPLIER_API_URL`, `SUPPLIER_API_KEY`
- Timeout: must complete within 120 seconds

---

## Phase 8: Dealer Assistant (§9) — OPTIONAL (AI/ML Track)

### 8.1 If implementing:
- Choose LLM provider (Gemini recommended - free tier)
- Add provider SDK to requirements.txt
- Implement tool calling: `search_parts`, `check_stock`, `create_draft_order`
- Session memory: store conversation history per session_id
- Response format: reply, cited_skus, tool_calls, actions

### 8.2 Tools
```python
def search_parts(query: str, vehicle: str = None) -> list[Product]
def check_stock(sku: str) -> int
def create_draft_order(dealer_id: int, items: list) -> Order
```

---

## Phase 9: Forecasting & Reorder (§10) — OPTIONAL (AI/ML Track)

### 9.1 Forecast Generation
- Train model on `sales_history.csv` + `promo_calendar.csv` + `festival_calendar.csv`
- Generate `ml/forecast.csv` with 160 rows (40 SKUs × 4 weeks)
- Weeks: 2026-09-28, 2026-10-05, 2026-10-12, 2026-10-19

### 9.2 Endpoints
- `GET /api/forecast/{sku}/` — 4 weeks from forecast.csv
- `GET /api/reorder-suggestions/` — 40 entries with formula:
  - L = lead_time_weeks
  - lead_time_demand = sum forecast_units for first L weeks
  - sigma = sample std dev of last 12 weeks units_sold
  - safety_stock = ceil(1.65 × sigma × √L)
  - reorder_point = lead_time_demand + safety_stock
  - reorder_qty = max(0, ceil(reorder_point - current_stock))

---

## Phase 10: Testing & Verification

### 10.1 Smoke Test
```bash
python manage.py migrate --noinput
python manage.py seed_data
python manage.py seed_data  # idempotent
python manage.py runserver 0.0.0.0:8000 --noreload
python smoke_test.py --base-url http://localhost:8000 --track django
```

### 10.2 Key Test Scenarios
1. Health check passes
2. Products: 600 seeded, pagination, filters, CRUD
3. Dealers: 25 seeded, create with duplicate code → 409
4. Inventory: PUT updates stock, reflects in product
5. Orders: DRAFT creation, validation errors, money format
6. Order lifecycle: confirm (stock -2), cancel (stock restored), invalid transitions
7. Stock concurrency: parallel confirm requests don't oversell
7. Idempotency: same key same body = idempotent, different body = 409
8. Order number format: ORD-YYYYMMDD-NNNN, daily sequence
9. Supplier sync: run against mock_supplier.py
10. Error response shapes match contract exactly

---

## File Structure (Final)
```
dealerdesk/
├── manage.py
├── requirements.txt
├── .env.example
├── data/                    # Provided (grader replaces)
│   ├── catalogue.csv
│   ├── dealers.csv
│   ├── sales_history.csv
│   ├── promo_calendar.csv
│   ├── lead_times.csv
│   ├── festival_calendar.csv
│   └── DATA_README.md
├── dealerdesk/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── core/
│   ├── __init__.py
│   ├── apps.py
│   ├── views.py              # health check
│   └── management/commands/seed_data.py
├── products/
│   ├── __init__.py
│   ├── models.py
│   ├── serializers.py
│   ├── views.py
│   └── urls.py
├── dealers/
│   ├── __init__.py
│   ├── models.py
│   ├── serializers.py
│   ├── views.py
│   └── urls.py
├── orders/
│   ├── __init__.py
│   ├── models.py
│   ├── serializers.py
│   ├── views.py
│   ├── services.py           # order_number gen, stock logic, GST
│   └── urls.py
├── sync/
│   ├── __init__.py
│   ├── services.py           # supplier sync logic
│   ├── views.py
│   └── urls.py
├── ml/                       # Optional
│   ├── forecast.csv          # Committed
│   ├── train_forecast.py
│   └── reorder.py
└── supplier_mock/            # Provided (for local testing)
    └── mock_supplier.py
```

---

## Requirements.txt Additions
```
# Core (already in starter)
Django>=4.2,<6
djangorestframework>=3.15
psycopg[binary]>=3.1
dj-database-url>=2.1
python-dotenv>=1.0
requests>=2.31

# For supplier sync
tenacity>=8.0  # retry logic (or implement manually)

# For AI Assistant (optional)
google-genai>=1.0  # if using Gemini
# or openai>=1.0 / anthropic>=0.3 / groq>=0.4

# For Forecasting (optional)
pandas>=2.0
scikit-learn>=1.3
numpy>=1.24
```

---

## Implementation Order (Recommended)

1. **Setup & Models** (Phase 1-2) — Foundation
2. **Products + Inventory + Dealers** (Phase 3-5) — Straightforward CRUD
3. **Orders Core** (Phase 6) — Most complex, do early
4. **Supplier Sync** (Phase 7) — External API integration
5. **Testing & Polish** (Phase 10) — Run smoke test, fix issues
6. **Optional: Assistant/Forecast** (Phase 8-9) — If time permits

---

## Critical Implementation Details

### Money Formatting
```python
def money_str(value: Decimal) -> str:
    return f"{value:.2f}"  # Always exactly 2 decimals
```

### Date/Time
- `TIME_ZONE = "Asia/Kolkata"` in settings
- Use `timezone.now()` for timestamps
- Order number date: `timezone.now().astimezone(ZoneInfo("Asia/Kolkata")).date()`

### Pagination
```python
# DRF default pagination
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}
# Allow page_size query param up to 100
```

### Error Response Shape
```json
{"error": {"code": "VALIDATION_ERROR", "message": "...", "details": [...]}}
```
Always include `details` as list (empty if not applicable).

### Decimal Precision
- All money: `DecimalField(max_digits=12, decimal_places=2)` in DB
- Calculations: use `Decimal` throughout, quantize at each step

---

## Risk Areas & Mitigations

| Risk | Mitigation |
|------|------------|
| Stock concurrency | `select_for_update()` on Product rows during confirm |
| Order number collisions | `DailyOrderSequence` model with `select_for_update()` |
| Idempotency race | Unique constraint on (key, request_hash), atomic upsert |
| Supplier sync timeout | Batch requests, limit pages, 120s total budget |
| GST rounding | `Decimal.quantize(Decimal('0.01'), ROUND_HALF_UP)` per line |
| Seed idempotency | `update_or_create` or `bulk_create` + `bulk_update` |

---

## Quick Start Commands
```bash
# 1. Copy starter to repo root
cp -r starter/* .
cp -r ../data .

# 2. Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Database
# Set DATABASE_URL in .env (Neon/Supabase/local Postgres)

# 4. Run
python manage.py migrate
python manage.py seed_data
python manage.py runserver 0.0.0.0:8000

# 5. Test
python smoke_test.py --base-url http://localhost:8000 --track django

# 6. Supplier sync test (separate terminal)
python supplier_mock/mock_supplier.py --calm
# Set SUPPLIER_API_URL=http://127.0.0.1:8099 SUPPLIER_API_KEY=dev-supplier-key
python manage.py shell -c "from sync.services import sync_supplier; print(sync_supplier())"
```

---

## Next Steps
1. Create the Django apps and models
2. Implement seed_data
3. Build Products/Dealers/Inventory APIs
4. Build Orders API with full business logic
5. Build Supplier Sync
6. Run smoke test iteratively