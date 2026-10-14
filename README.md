# VIKMO DealerDesk

**Track:** `aiml` (AI / ML Track & Django Track)  
**Video Walkthrough Link:** [https://youtu.be/EfTsi7MmsK8](https://youtu.be/EfTsi7MmsK8)  

DealerDesk is an ERP & order management backend for motorcycle parts dealers and suppliers, built with Django 4.2+ and Django REST Framework on PostgreSQL.

---

## Features Implemented

1. **Products (§4) & Inventory (§5)**
   - Product catalog with pagination and query filters: `search` (case-insensitive substring on sku, name, brand), `category` (exact match), and `vehicle` (substring on vehicle_fitment).
   - Validation for positive pricing with at most 2 decimal places. Duplicate SKU returns `409 DUPLICATE`.
   - Inventory update via `PUT /api/inventory/{sku}/` setting exact non-negative stock counts.
   - Partial updates via `PATCH /api/products/{sku}/` with immutable SKU.

2. **Dealers (§6)**
   - Dealer management with paginated listing and creation.
   - Duplicate dealer code check returning `409 DUPLICATE`.

3. **Order Engine (§7)**
   - Concurrency-safe order creation with sequential numbering `ORD-YYYYMMDD-NNNN` based on creation date in `Asia/Kolkata` using `DailyOrderSequence` row locks.
   - Strict idempotency support via `Idempotency-Key` header with SHA-256 request hashing. Duplicate requests return original order; conflicting bodies return `409 IDEMPOTENCY_CONFLICT`.
   - Pricing & GST: `line_tax = (line_subtotal * Decimal('0.18')).quantize(Decimal('0.01'), ROUND_HALF_UP)` calculated per line item.
   - Status workflow: `DRAFT` → `CONFIRMED` → `DISPATCHED` → `DELIVERED`, and cancellation (`CANCELLED`).
   - All-or-nothing confirm with database row locks (`select_for_update`) across all order line products in sorted order to avoid deadlocks and prevent overselling. Short stock returns `409 INSUFFICIENT_STOCK` detailing all short items.
   - Order editing via `PUT /api/orders/{order_number}/` allowed only in `DRAFT`; non-DRAFT edits return `409 ORDER_LOCKED`.
   - Cancelling a confirmed order restores stock exactly once.

4. **Supplier Sync (§8)**
   - Paginated catalogue sync from external supplier API with cursor traversal until exhausted.
   - Robust retry policy: up to 5 attempts per page, honouring `Retry-After` on `429`, and exponential backoff on `5xx`/connection errors. Immediate failure on `401`.
   - All-or-nothing rollback returning `502 SUPPLIER_UNAVAILABLE` if any page cannot be fetched.
   - Automatic deduplication across pages by latest `updated_at` timestamp.
   - Validation of supplier items (skipping malformed items into `rejected` list).
   - Atomic database sync creating new parts at stock 0 and updating modified fields while never modifying DealerDesk stock.

5. **Dealer Assistant (§9)**
   - Intelligent chat assistant endpoint `POST /api/assistant/chat/` with tool calling: `search_parts`, `check_stock`, and `create_draft_order`.
   - Session tracking and citation of active catalog SKUs.

6. **Forecasting & Reorder Engine (§10)**
   - Forecast generated and committed at `ml/forecast.csv` (160 rows: 40 SKUs across 4 future weeks).
   - Reorder suggestions endpoint `GET /api/reorder-suggestions/` calculating lead-time demand, sample standard deviation $\sigma$ over last 12 weeks, safety stock $\lceil 1.65 \times \sigma \times \sqrt{L} \rceil$, reorder points, and live required reorder quantities based on current stock.

---

## Quick Start

### 1. Requirements
- Python 3.11+
- PostgreSQL

### 2. Setup Virtual Environment
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Environment Configuration
Copy `.env.example` to `.env` and set `DATABASE_URL`:
```bash
cp .env.example .env
```
Ensure `.env` contains:
```env
DATABASE_URL=postgres://<user>:<password>@localhost:5432/dealerdesk
SUPPLIER_API_URL=http://127.0.0.1:8099
SUPPLIER_API_KEY=dev-supplier-key
```

### 4. Database Migrations & Seed
```bash
python manage.py migrate --noinput
python manage.py seed_data
```

### 5. Run Server
```bash
python manage.py runserver 0.0.0.0:8000 --noreload
```

---

## Running Verification & Smoke Tests

### Start Supplier Mock (for supplier sync tests)
```bash
python supplier_mock/mock_supplier.py --calm
```

### Run Assignment Smoke Test
```bash
# Test Django track (core, order engine, supplier sync)
python smoke_test.py --base-url http://localhost:8000 --track django

# Test all parts (including assistant & forecast)
python smoke_test.py --base-url http://localhost:8000 --all
```

### Run Concurrency & Edge Cases Test Suite
```bash
python test_suite.py
```
