# VIKMO DealerDesk — Technical Decisions (DECISIONS.md)

**Track:** Django Track  
**Candidate Name:** Latesh K  
**Repository:** VIKMO DealerDesk Implementation  

---

### Question 1: Where exactly is overselling prevented? Cite the code, and explain what would happen without it when two confirms arrive together.

**Code Citation:** [`orders/services.py:276-326`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/orders/services.py#L276-L326)

**Explanation:**  
Overselling is prevented inside the `confirm_order` function using database-level row locking with `select_for_update()` inside `transaction.atomic()`:
```python
order = Order.objects.select_for_update().filter(order_number=order_number).first()
...
skus = sorted([it.sku for it in items])
products = {p.sku: p for p in Product.objects.select_for_update().filter(sku__in=skus)}
```
1. Products are queried with `select_for_update()` in deterministic sorted order by SKU (`orders/services.py:288-290`), preventing deadlocks across multi-item transactions.
2. In-memory stock checks are evaluated only *after* acquiring row-level exclusive locks (`orders/services.py:293-302`).
3. If any line is short, an `InsufficientStockError` (`409 INSUFFICIENT_STOCK`) is raised, causing the transaction to roll back with zero deductions (`orders/services.py:304-316`).

**What would happen without it:**  
Without `select_for_update()`, two concurrent requests verifying stock of `5` for orders of quantity `4` would both read `stock = 5` concurrently in a read-committed snapshot. Both would pass validation, perform `product.stock = 5 - 4 = 1`, and the second commit would overwrite the first, resulting in 8 units sold while database stock only registers 1 deducted (or negative stock `-3`), causing overselling and inventory corruption.

---

### Question 2: How do you calculate and round GST? What would go wrong with floats, or with Decimal's default rounding?

**Code Citation:** [`core/utils.py:14-16`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/core/utils.py#L14-L16) and [`orders/services.py:126-135`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/orders/services.py#L126-L135)

```python
def calculate_line_tax(line_subtotal: Decimal) -> Decimal:
    tax = line_subtotal * Decimal("0.18")
    return tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

**Why floats fail:**  
Binary floating-point arithmetic (IEEE 754) cannot accurately represent base-10 fractions (e.g., `0.18`, `0.01`). Floats accumulate precision artifacts (e.g. `4378.50 * 0.18 = 788.1300000000001` or `788.1299999999999`). When summing multiple line items, the cumulative error drifts by multiple paise, violating tax invoice reconciliation.

**Why Decimal's default rounding fails:**  
Python's standard `Decimal` context defaults to `ROUND_HALF_EVEN` (banker's rounding), which rounds ties to the nearest even last digit (e.g., `2.5 -> 2`, `3.5 -> 4`). Indian GST regulations and commercial invoices strictly mandate arithmetic half-up rounding (`ROUND_HALF_UP`), where half-paise fractions (`0.005`) always round upwards to the next full paisa (`0.01`).

---

### Question 3: How do you guarantee unique order numbers and idempotent order creation when duplicate requests arrive at the same moment?

**Code Citation:**  
- Order number generation: [`orders/services.py:30-41`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/orders/services.py#L30-L41)  
- Idempotency resolution: [`orders/services.py:177-189`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/orders/services.py#L177-L189) and [`orders/services.py:213-230`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/orders/services.py#L213-L230)

**Unique Order Numbers:**  
Generated via `generate_order_number()`:
```python
seq, _ = DailyOrderSequence.objects.select_for_update().get_or_create(
    date=today, defaults={"last_sequence": 0}
)
seq.last_sequence += 1
seq.save(update_fields=["last_sequence"])
```
The `DailyOrderSequence` model locks the row for today's date in `Asia/Kolkata` time using `select_for_update()`. Every concurrent order creation is serialized at the sequence counter level, guaranteeing strictly consecutive sequence numbers (`ORD-YYYYMMDD-0001`, `ORD-YYYYMMDD-0002`...) with zero collisions.

**Idempotency Guarantee:**  
When an `Idempotency-Key` header is supplied, a SHA-256 hash of the request body is computed. Inside `transaction.atomic()`:
1. `IdempotencyKey.objects.select_for_update().filter(key=idempotency_key).first()` checks for prior registration.
2. If found and the payload hash matches, the existing order is immediately returned with HTTP 200/201.
3. If found and the payload hash differs, an `IdempotencyConflictError` (`409 IDEMPOTENCY_CONFLICT`) is raised.
4. If two identical requests race before either record exists, the database unique primary key constraint on `key` catches `IntegrityError` on the second commit (`orders/services.py:220-229`), reloads the committed row, verifies the hash, and returns the original order.

---

### Question 4: Explain your schema: each model, its relationships, and the on_delete choice for every foreign key, with your reasons.

**Code Citation:**  
- [`products/models.py:4-19`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/products/models.py#L4-L19)  
- [`dealers/models.py:5-20`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/dealers/models.py#L5-L20)  
- [`orders/models.py:13-65`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/orders/models.py#L13-L65)

1. **`Product`**:
   - `sku` (CharField, PK): Natural unique identifier.
   - Fields: `name`, `category`, `brand`, `vehicle_fitment`, `price` (DecimalField 12,2), `stock` (IntegerField >= 0), `description`.

2. **`Dealer`**:
   - `id` (BigAutoField, PK), `dealer_code` (CharField, unique), `name`, `city`, `phone`, `email`, `gstin`, `credit_limit` (DecimalField 14,2).

3. **`Order`**:
   - `order_number` (CharField, PK): `ORD-YYYYMMDD-NNNN`.
   - `dealer` (`ForeignKey(Dealer, on_delete=models.PROTECT)`):
     - **Reason for `PROTECT`**: Orders represent binding financial and legal invoices. Deleting a dealer must never delete historical orders or orphan transactions. `PROTECT` prevents inadvertent deletion of dealers with order history.
   - `status`, `subtotal`, `tax_total`, `grand_total` (DecimalField 12,2), `created_at`, `updated_at`.

4. **`OrderItem`**:
   - `id` (BigAutoField, PK).
   - `order` (`ForeignKey(Order, on_delete=models.CASCADE, related_name="items")`):
     - **Reason for `CASCADE`**: Order items exist strictly as parts of an Order aggregate. Deleting or replacing an order's items should clean up line items.
   - `sku` and `name` are snapshot CharFields, not foreign keys to `Product`.
     - **Reason**: Decoupling `OrderItem` from live `Product` records ensures catalog updates, descriptions, or future price modifications never alter confirmed historical order records.

5. **`DailyOrderSequence`**:
   - `date` (DateField, PK), `last_sequence` (PositiveIntegerField). Dedicated row-lock target for collision-free numbering.

6. **`IdempotencyKey`**:
   - `key` (CharField, PK), `request_hash` (CharField 64), `order` (`ForeignKey(Order, on_delete=models.CASCADE)`).
     - **Reason for `CASCADE`**: Idempotency records track requests targeting orders; removing an order purges its idempotency entry.

---

### Question 5: Where are status transitions enforced, and how do you guarantee a cancel restores stock exactly once?

**Code Citation:** [`orders/services.py:274-390`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/orders/services.py#L274-L390)

**Enforcement Location:**  
Status transitions are strictly enforced in dedicated service functions inside atomic transactions:
- `confirm_order`: verifies `order.status == OrderStatus.DRAFT` (`orders/services.py:281`). Rejects all others with `409 INVALID_TRANSITION`.
- `dispatch_order`: verifies `order.status == OrderStatus.CONFIRMED` (`orders/services.py:336`). Rejects all others with `409 INVALID_TRANSITION`.
- `deliver_order`: verifies `order.status == OrderStatus.DISPATCHED` (`orders/services.py:352`). Rejects all others with `409 INVALID_TRANSITION`.
- `cancel_order`: verifies `order.status in (OrderStatus.DRAFT, OrderStatus.CONFIRMED)` (`orders/services.py:368-372`). If already `DISPATCHED`, `DELIVERED`, or `CANCELLED`, raises `InvalidTransitionError` (`409 INVALID_TRANSITION`).

**Restoring Stock Exactly Once:**  
Inside `cancel_order()`:
```python
with transaction.atomic():
    order = Order.objects.select_for_update().filter(order_number=order_number).first()
    ...
    if order.status == OrderStatus.CONFIRMED:
        # Restore stock under product row locks
        items = list(order.items.all())
        skus = sorted([it.sku for it in items])
        products = {p.sku: p for p in Product.objects.select_for_update().filter(sku__in=skus)}
        for it in items:
            p = products.get(it.sku)
            if p:
                p.stock += it.quantity
                p.save(update_fields=["stock", "updated_at"])

    order.status = OrderStatus.CANCELLED
    order.save(update_fields=["status", "updated_at"])
```
Because the order status is checked under a row lock and updated to `CANCELLED`, any subsequent cancellation request fails the status check (`status == CANCELLED` is not allowed) and is rejected with `409 INVALID_TRANSITION`, ensuring stock can never be refunded more than once.

---

### Question 6: How does your supplier sync handle rate limits, failures and duplicates? How do you guarantee it changes nothing when the feed can't be fully fetched?

**Code Citation:** [`sync/services.py:46-165`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/sync/services.py#L46-L165)

1. **Rate Limits (`429`):**  
   [`sync/services.py:84-96`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/sync/services.py#L84-L96): Extracts the `Retry-After` header value, sleeps for the specified number of seconds (`time.sleep(max(wait_seconds, 1.0))`), and repeats the request.
2. **Transient Failures (`5xx` & Network Drops):**  
   [`sync/services.py:98-106`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/sync/services.py#L98-L106): Retries up to 5 attempts per page with exponential backoff (`0.5 * 2 ** (attempt - 1)`).
3. **Unauthorized (`401`):**  
   [`sync/services.py:77-82`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/sync/services.py#L77-L82): Fails immediately without retrying.
4. **All-or-Nothing Guarantee:**  
   The synchronization workflow splits into two distinct phases: (1) network retrieval into memory, and (2) database transaction application. If *any* page fails after 5 attempts, `SupplierUnavailableError` (`502 SUPPLIER_UNAVAILABLE`) is raised immediately *before* opening the database transaction. `with transaction.atomic():` ([`sync/services.py:166`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/sync/services.py#L166)) is only reached when all pages have been successfully retrieved.
5. **Deduplication:**  
   [`sync/services.py:145-155`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/sync/services.py#L145-L155): Items across pages sharing the same SKU are tracked in a dictionary; entries are replaced if and only if the item has an equal or newer parsed ISO `updated_at` timestamp.

---

### Question 7: How does the sync decide between created, updated and unchanged, and why does a second run change nothing?

**Code Citation:** [`sync/services.py:166-221`](file:///Users/lateshk/Documents/GitHub/vikmo_assignment/sync/services.py#L166-L221)

**Decision Logic:**  
Existing products are pre-fetched by SKU:
```python
existing_products = {p.sku: p for p in Product.objects.filter(sku__in=all_skus)}
```
For each valid, deduplicated supplier feed item:
1. **`created`**: If `sku not in existing_products`, a new `Product` instance is created with `stock = 0` (DealerDesk warehouse stock is never derived from supplier stock).
2. **`updated`**: If the SKU exists and any of `name`, `category`, `brand`, `vehicle_fitment`, `description`, or `price` differs from current values, those fields are updated. Product `stock` remains untouched.
3. **`unchanged`**: If the SKU exists and all catalog fields and prices match exactly, no update occurs.

**Why a second run changes nothing:**  
Because the first sync created missing products and updated differing fields, all feed items on the second run match the database records exactly. All items evaluate to `unchanged`, resulting in `created: 0, updated: 0`, producing an idempotent operation.

---

### Question 8: What is the weakest part of your submission, and what would you do with two more days?

1. **Weakest Part:**  
   The natural language parts retrieval in the Assistant endpoint relies on relational database multi-column pattern matching (`Q` objects across name, category, brand, vehicle fitment). While accurate for exact model keywords (e.g. "Pulsar 150", "brake pad"), it lacks semantic understanding for informal dealer colloquialisms, typos, or cross-compatibility aliases (e.g., "twin spark 150", "front disc shoes").

2. **What I would do with two more days:**  
   - **Semantic Search with `pgvector`:** Enable the `vector` extension in PostgreSQL and index product embeddings generated using a lightweight embedding model to provide cosine similarity retrieval combined with full-text search (`SearchRank`).
   - **Streaming Supplier Ingestion:** For production catalogs with 100,000+ items, replace in-memory page aggregation with a batched queue or staging table worker pattern so memory consumption remains constant regardless of feed size.
   - **Ledger-Based Inventory Tracking:** Introduce an immutable `StockMovement` ledger table recording every quantity adjustment, order reservation, and return with audit attribution.
