import concurrent.futures
import decimal
import json
import uuid
import requests
import unittest

BASE_URL = "http://localhost:8000"


class DealerDeskComprehensiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = requests.Session()
        resp = cls.s.get(f"{BASE_URL}/api/health/")
        assert resp.status_code == 200

    def test_01_health(self):
        r = self.s.get(f"{BASE_URL}/api/health/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})

    def test_02_product_filters(self):
        # Category filter
        r = self.s.get(f"{BASE_URL}/api/products/?category=Brakes&page_size=10")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(all(item["category"] == "Brakes" for item in data["results"]))

        # Search filter
        r = self.s.get(f"{BASE_URL}/api/products/?search=bajaj")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertGreater(data["count"], 0)

        # Vehicle filter
        r = self.s.get(f"{BASE_URL}/api/products/?vehicle=pulsar")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(all("pulsar" in item["vehicle_fitment"].lower() for item in data["results"]))

    def test_03_create_product_validation(self):
        # Negative price -> 400
        r = self.s.post(f"{BASE_URL}/api/products/", json={
            "sku": f"TNEG-{uuid.uuid4().hex[:4]}", "name": "Test", "category": "Test", "brand": "Test",
            "vehicle_fitment": "Universal", "price": "-10.00"
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "VALIDATION_ERROR")

        # More than 2 decimals -> 400
        r = self.s.post(f"{BASE_URL}/api/products/", json={
            "sku": f"TDEC-{uuid.uuid4().hex[:4]}", "name": "Test", "category": "Test", "brand": "Test",
            "vehicle_fitment": "Universal", "price": "10.555"
        })
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "VALIDATION_ERROR")

        # Create valid
        sku = f"TNEW-{uuid.uuid4().hex[:6]}"
        r = self.s.post(f"{BASE_URL}/api/products/", json={
            "sku": sku, "name": "Valid Test Part", "category": "Brakes", "brand": "Endurance",
            "vehicle_fitment": "Universal", "price": "500.00"
        })
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["stock"], 0)
        self.assertEqual(r.json()["price"], "500.00")

        # Duplicate SKU -> 409 DUPLICATE
        r = self.s.post(f"{BASE_URL}/api/products/", json={
            "sku": sku, "name": "Valid Test Part", "category": "Brakes", "brand": "Endurance",
            "vehicle_fitment": "Universal", "price": "500.00"
        })
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"]["code"], "DUPLICATE")

    def test_04_inventory_and_patch(self):
        sku = f"TINV-{uuid.uuid4().hex[:6]}"
        self.s.post(f"{BASE_URL}/api/products/", json={
            "sku": sku, "name": "Inv Part", "category": "Brakes", "brand": "Endurance",
            "vehicle_fitment": "Universal", "price": "500.00"
        })
        # Update inventory
        r = self.s.put(f"{BASE_URL}/api/inventory/{sku}/", json={"quantity": 10, "reason": "initial count"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["quantity"], 10)

        # Negative inventory -> 400
        r = self.s.put(f"{BASE_URL}/api/inventory/{sku}/", json={"quantity": -5})
        self.assertEqual(r.status_code, 400)

        # PATCH product price
        r = self.s.patch(f"{BASE_URL}/api/products/{sku}/", json={"price": "550.00"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["price"], "550.00")

    def test_05_idempotency_order_creation(self):
        # Create dealer
        d_code = f"DLR-{uuid.uuid4().hex[:6]}"
        dealer_res = self.s.post(f"{BASE_URL}/api/dealers/", json={"dealer_code": d_code, "name": "Idem Dealer"}).json()
        dealer_id = dealer_res["id"]

        sku = f"TORD-{uuid.uuid4().hex[:6]}"
        self.s.post(f"{BASE_URL}/api/products/", json={
            "sku": sku, "name": "Order Part", "category": "Brakes", "brand": "Endurance",
            "vehicle_fitment": "Universal", "price": "500.00"
        })

        headers = {"Idempotency-Key": f"key-{uuid.uuid4().hex}"}
        payload = {"dealer_id": dealer_id, "items": [{"sku": sku, "quantity": 2}]}

        r1 = self.s.post(f"{BASE_URL}/api/orders/", json=payload, headers=headers)
        self.assertIn(r1.status_code, [200, 201])
        order_num = r1.json()["order_number"]

        # Same key, same body -> returns original order
        r2 = self.s.post(f"{BASE_URL}/api/orders/", json=payload, headers=headers)
        self.assertIn(r2.status_code, [200, 201])
        self.assertEqual(r2.json()["order_number"], order_num)

        # Same key, different body -> 409 IDEMPOTENCY_CONFLICT
        diff_payload = {"dealer_id": dealer_id, "items": [{"sku": sku, "quantity": 3}]}
        r3 = self.s.post(f"{BASE_URL}/api/orders/", json=diff_payload, headers=headers)
        self.assertEqual(r3.status_code, 409)
        self.assertEqual(r3.json()["error"]["code"], "IDEMPOTENCY_CONFLICT")

    def test_06_order_lifecycle_and_locking(self):
        d_code = f"DLR-{uuid.uuid4().hex[:6]}"
        dealer_id = self.s.post(f"{BASE_URL}/api/dealers/", json={"dealer_code": d_code, "name": "Lifecycle Dealer"}).json()["id"]

        sku = f"TLIFE-{uuid.uuid4().hex[:6]}"
        self.s.post(f"{BASE_URL}/api/products/", json={
            "sku": sku, "name": "Lifecycle Part", "category": "Brakes", "brand": "Endurance",
            "vehicle_fitment": "Universal", "price": "200.00"
        })
        self.s.put(f"{BASE_URL}/api/inventory/{sku}/", json={"quantity": 5})

        r = self.s.post(f"{BASE_URL}/api/orders/", json={
            "dealer_id": dealer_id,
            "items": [{"sku": sku, "quantity": 3}]
        })
        order_num = r.json()["order_number"]

        # PUT replace items while DRAFT
        r_put = self.s.put(f"{BASE_URL}/api/orders/{order_num}/", json={
            "items": [{"sku": sku, "quantity": 2}]
        })
        self.assertEqual(r_put.status_code, 200)
        self.assertEqual(r_put.json()["items"][0]["quantity"], 2)

        # Confirm
        r_conf = self.s.post(f"{BASE_URL}/api/orders/{order_num}/confirm/")
        self.assertEqual(r_conf.status_code, 200)
        self.assertEqual(r_conf.json()["status"], "CONFIRMED")
        # Stock decreased by 2 -> 3
        self.assertEqual(self.s.get(f"{BASE_URL}/api/products/{sku}/").json()["stock"], 3)

        # Try to PUT after CONFIRM -> 409 ORDER_LOCKED
        r_lock = self.s.put(f"{BASE_URL}/api/orders/{order_num}/", json={
            "items": [{"sku": sku, "quantity": 1}]
        })
        self.assertEqual(r_lock.status_code, 409)
        self.assertEqual(r_lock.json()["error"]["code"], "ORDER_LOCKED")

        # Dispatch
        r_disp = self.s.post(f"{BASE_URL}/api/orders/{order_num}/dispatch/")
        self.assertEqual(r_disp.status_code, 200)
        self.assertEqual(r_disp.json()["status"], "DISPATCHED")

        # Try cancel from DISPATCHED -> 409 INVALID_TRANSITION
        r_cant_cancel = self.s.post(f"{BASE_URL}/api/orders/{order_num}/cancel/")
        self.assertEqual(r_cant_cancel.status_code, 409)
        self.assertEqual(r_cant_cancel.json()["error"]["code"], "INVALID_TRANSITION")

        # Deliver
        r_deliv = self.s.post(f"{BASE_URL}/api/orders/{order_num}/deliver/")
        self.assertEqual(r_deliv.status_code, 200)
        self.assertEqual(r_deliv.json()["status"], "DELIVERED")

    def test_07_concurrency_stock_deduction(self):
        """10 threads try to confirm an order of quantity 2 each, when stock is only 6. Exactly 3 must succeed."""
        sku = f"CONC-{uuid.uuid4().hex[:6]}"
        self.s.post(f"{BASE_URL}/api/products/", json={
            "sku": sku, "name": "Conc SKU", "category": "Brakes", "brand": "Test",
            "vehicle_fitment": "Universal", "price": "100.00"
        })
        self.s.put(f"{BASE_URL}/api/inventory/{sku}/", json={"quantity": 6})
        d_code = f"DLR-{uuid.uuid4().hex[:6]}"
        dealer_id = self.s.post(f"{BASE_URL}/api/dealers/", json={"dealer_code": d_code, "name": "Conc Dealer"}).json()["id"]

        # Create 10 draft orders of qty 2
        order_numbers = []
        for _ in range(10):
            res = self.s.post(f"{BASE_URL}/api/orders/", json={
                "dealer_id": dealer_id,
                "items": [{"sku": sku, "quantity": 2}]
            }).json()
            order_numbers.append(res["order_number"])

        def try_confirm(ord_num):
            s = requests.Session()
            resp = s.post(f"{BASE_URL}/api/orders/{ord_num}/confirm/")
            return resp.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            statuses = list(executor.map(try_confirm, order_numbers))

        success_count = statuses.count(200)
        fail_count = statuses.count(409)

        self.assertEqual(success_count, 3, f"Expected exactly 3 confirms to succeed, got {success_count}")
        self.assertEqual(fail_count, 7, f"Expected 7 confirms to fail with 409, got {fail_count}")

        # Check final stock
        final_stock = self.s.get(f"{BASE_URL}/api/products/{sku}/").json()["stock"]
        self.assertEqual(final_stock, 0, f"Stock should be 0, got {final_stock}")


if __name__ == "__main__":
    unittest.main()
