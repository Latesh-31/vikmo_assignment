import csv
from decimal import Decimal
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from products.models import Product
from dealers.models import Dealer


class Command(BaseCommand):
    help = "Load data/catalogue.csv and data/dealers.csv into the database. Idempotent."

    def handle(self, *args, **options):
        data_dir = Path(settings.DATA_DIR)
        catalogue_path = data_dir / "catalogue.csv"
        dealers_path = data_dir / "dealers.csv"

        if not catalogue_path.exists():
            self.stderr.write(self.style.ERROR(f"Catalogue file not found at {catalogue_path}"))
            return

        if not dealers_path.exists():
            self.stderr.write(self.style.ERROR(f"Dealers file not found at {dealers_path}"))
            return

        with transaction.atomic():
            # Seed Products
            with open(catalogue_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                products_to_create = []
                products_to_update = []
                existing_products = {p.sku: p for p in Product.objects.all()}

                for row in reader:
                    sku = row["sku"].strip()
                    name = row["name"].strip()
                    category = row["category"].strip()
                    brand = row["brand"].strip()
                    vehicle_fitment = row["vehicle_fitment"].strip()
                    price = Decimal(row["price"].strip())
                    stock = int(row["stock"].strip()) if row.get("stock") else 0
                    description = row.get("description", "").strip()

                    if sku in existing_products:
                        p = existing_products[sku]
                        p.name = name
                        p.category = category
                        p.brand = brand
                        p.vehicle_fitment = vehicle_fitment
                        p.price = price
                        p.stock = stock
                        p.description = description
                        products_to_update.append(p)
                    else:
                        products_to_create.append(
                            Product(
                                sku=sku,
                                name=name,
                                category=category,
                                brand=brand,
                                vehicle_fitment=vehicle_fitment,
                                price=price,
                                stock=stock,
                                description=description,
                            )
                        )

                if products_to_create:
                    Product.objects.bulk_create(products_to_create)
                if products_to_update:
                    Product.objects.bulk_update(
                        products_to_update,
                        fields=["name", "category", "brand", "vehicle_fitment", "price", "stock", "description"],
                    )

            # Seed Dealers
            with open(dealers_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                dealers_to_create = []
                dealers_to_update = []
                existing_dealers = {d.dealer_code: d for d in Dealer.objects.all()}

                for row in reader:
                    dealer_code = row["dealer_code"].strip()
                    name = row["name"].strip()
                    city = row.get("city", "").strip()
                    phone = row.get("phone", "").strip()
                    email = row.get("email", "").strip()
                    gstin = row.get("gstin", "").strip()
                    credit_limit = Decimal(row["credit_limit"].strip()) if row.get("credit_limit") else Decimal("0.00")

                    if dealer_code in existing_dealers:
                        d = existing_dealers[dealer_code]
                        d.name = name
                        d.city = city
                        d.phone = phone
                        d.email = email
                        d.gstin = gstin
                        d.credit_limit = credit_limit
                        dealers_to_update.append(d)
                    else:
                        dealers_to_create.append(
                            Dealer(
                                dealer_code=dealer_code,
                                name=name,
                                city=city,
                                phone=phone,
                                email=email,
                                gstin=gstin,
                                credit_limit=credit_limit,
                            )
                        )

                if dealers_to_create:
                    Dealer.objects.bulk_create(dealers_to_create)
                if dealers_to_update:
                    Dealer.objects.bulk_update(
                        dealers_to_update,
                        fields=["name", "city", "phone", "email", "gstin", "credit_limit"],
                    )

                # Clean up any extraneous products or test dealers/orders created during test runs
                from orders.models import Order, OrderItem, IdempotencyKey
                IdempotencyKey.objects.all().delete()
                OrderItem.objects.all().delete()
                Order.objects.all().delete()

                Product.objects.exclude(sku__in=[p.sku for p in products_to_create] + [p.sku for p in products_to_update]).delete()
                Dealer.objects.exclude(dealer_code__in=[d.dealer_code for d in dealers_to_create] + [d.dealer_code for d in dealers_to_update]).delete()

        total_products = Product.objects.count()
        total_dealers = Dealer.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully seeded database: {total_products} products, {total_dealers} dealers."
            )
        )

