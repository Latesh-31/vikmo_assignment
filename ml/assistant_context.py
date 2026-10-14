"""
VIKMO DealerDesk — AI Assistant Context Service
Loads company and product data for context-aware responses.
"""

import csv
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from django.conf import settings
from django.db.models import Q

from products.models import Product
from dealers.models import Dealer


class CompanyContext:
    """Company and catalogue context for AI assistant."""

    def __init__(self):
        self._catalogue_cache: Optional[List[Dict]] = None
        self._dealers_cache: Optional[List[Dict]] = None
        self._categories_cache: Optional[List[str]] = None
        self._brands_cache: Optional[List[str]] = None
        self._vehicles_cache: Optional[List[str]] = None
        self._company_info = self._load_company_info()

    def _load_company_info(self) -> Dict[str, Any]:
        """Company information for the assistant."""
        return {
            "name": "VIKMO DealerDesk",
            "tagline": "Distributor Operating System for Motorcycle Parts",
            "description": (
                "VIKMO DealerDesk is a modern ERP and order management platform "
                "designed for motorcycle parts distributors and dealers. We connect "
                "suppliers with a network of dealers across India, providing real-time "
                "inventory visibility, automated reorder suggestions, and AI-powered "
                "parts lookup."
            ),
            "capabilities": [
                "Real-time parts catalogue with 600+ SKUs",
                "Multi-dealer order management (Draft → Confirmed → Dispatched → Delivered)",
                "Automated stock deduction with concurrency safety",
                "Demand forecasting with σ-based safety stock (1.65σ × √L)",
                "Supplier catalogue sync with 5-retry policy and atomic rollback",
                "AI Assistant for parts search, stock checks, and order creation",
                "GST-compliant invoicing (18% per line item)",
            ],
            "contact": {
                "support_email": "support@vikmo.example.com",
                "support_phone": "+91-80-XXXX-XXXX",
                "hq_address": "Bengaluru, Karnataka, India",
            },
            "policies": {
                "payment_terms": "Net 30 days for approved dealers",
                "minimum_order": "₹1,000",
                "shipping": "Free on orders above ₹10,000; otherwise ₹150 flat",
                "returns": "Within 7 days for defective parts; restocking fee 10%",
                "gst": "18% on all parts (included in invoice breakdown)",
            },
        }

    def _load_catalogue_from_csv(self) -> List[Dict]:
        """Load catalogue data from CSV for context."""
        path = settings.DATA_DIR / "catalogue.csv"
        if not path.exists():
            return []

        catalogue = []
        with open(path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                catalogue.append({
                    "sku": row["sku"].strip(),
                    "name": row["name"].strip(),
                    "category": row["category"].strip(),
                    "brand": row["brand"].strip(),
                    "vehicle_fitment": row["vehicle_fitment"].strip(),
                    "price": row["price"].strip(),
                    "stock": int(row["stock"].strip()) if row.get("stock") else 0,
                    "description": row.get("description", "").strip(),
                })
        return catalogue

    def _load_dealers_from_csv(self) -> List[Dict]:
        """Load dealers data from CSV for context."""
        path = settings.DATA_DIR / "dealers.csv"
        if not path.exists():
            return []

        dealers = []
        with open(path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                dealers.append({
                    "dealer_code": row["dealer_code"].strip(),
                    "name": row["name"].strip(),
                    "city": row.get("city", "").strip(),
                    "phone": row.get("phone", "").strip(),
                    "email": row.get("email", "").strip(),
                    "gstin": row.get("gstin", "").strip(),
                    "credit_limit": row.get("credit_limit", "0.00").strip(),
                })
        return dealers

    def get_catalogue(self) -> List[Dict]:
        """Get full catalogue (cached)."""
        if self._catalogue_cache is None:
            self._catalogue_cache = self._load_catalogue_from_csv()
        return self._catalogue_cache

    def get_dealers(self) -> List[Dict]:
        """Get all dealers (cached)."""
        if self._dealers_cache is None:
            self._dealers_cache = self._load_dealers_from_csv()
        return self._dealers_cache

    def get_categories(self) -> List[str]:
        """Get unique categories."""
        if self._categories_cache is None:
            cats = set()
            for p in self.get_catalogue():
                cats.add(p["category"])
            self._categories_cache = sorted(cats)
        return self._categories_cache

    def get_brands(self) -> List[str]:
        """Get unique brands."""
        if self._brands_cache is None:
            brands = set()
            for p in self.get_catalogue():
                brands.add(p["brand"])
            self._brands_cache = sorted(brands)
        return self._brands_cache

    def get_vehicles(self) -> List[str]:
        """Get unique vehicle fitments."""
        if self._vehicles_cache is None:
            vehicles = set()
            for p in self.get_catalogue():
                v = p["vehicle_fitment"]
                if v and v.lower() != "universal":
                    vehicles.add(v)
            self._vehicles_cache = sorted(vehicles)
        return self._vehicles_cache

    def search_catalogue(
        self,
        query: str = "",
        category: str = "",
        vehicle: str = "",
        brand: str = "",
        limit: int = 10,
    ) -> List[Dict]:
        """Search catalogue with filters."""
        results = self.get_catalogue()
        query_lower = query.lower().strip()

        if query_lower:
            results = [
                p for p in results
                if (
                    query_lower in p["name"].lower()
                    or query_lower in p["sku"].lower()
                    or query_lower in p["brand"].lower()
                    or query_lower in p["category"].lower()
                    or query_lower in p["vehicle_fitment"].lower()
                    or query_lower in p["description"].lower()
                )
            ]

        if category:
            results = [p for p in results if category.lower() in p["category"].lower() or p["category"].lower() in category.lower()]

        if vehicle:
            results = [p for p in results if vehicle.lower() in p["vehicle_fitment"].lower()]

        if brand:
            results = [p for p in results if p["brand"].lower() == brand.lower()]

        # Sort by relevance: exact SKU match first, then name match, then others
        def relevance(p):
            if query_lower == p["sku"].lower():
                return 0
            if query_lower in p["name"].lower():
                return 1
            if query_lower in p["vehicle_fitment"].lower():
                return 2
            return 3

        results.sort(key=relevance)
        return results[:limit]

    def get_product_by_sku(self, sku: str) -> Optional[Dict]:
        """Get single product by SKU."""
        sku_upper = sku.upper().strip()
        for p in self.get_catalogue():
            if p["sku"].upper() == sku_upper:
                return p
        return None

    def get_dealer_by_id(self, dealer_id: int) -> Optional[Dict]:
        """Get dealer by ID from database."""
        try:
            dealer = Dealer.objects.get(id=dealer_id)
            return {
                "id": dealer.id,
                "dealer_code": dealer.dealer_code,
                "name": dealer.name,
                "city": dealer.city,
                "phone": dealer.phone,
                "email": dealer.email,
                "gstin": dealer.gstin,
                "credit_limit": str(dealer.credit_limit),
            }
        except Dealer.DoesNotExist:
            return None

    def get_dealer_by_code(self, code: str) -> Optional[Dict]:
        """Get dealer by code from CSV."""
        code_upper = code.upper().strip()
        for d in self.get_dealers():
            if d["dealer_code"].upper() == code_upper:
                return d
        return None

    def get_low_stock_products(self, threshold: int = 15) -> List[Dict]:
        """Get products with low stock."""
        return [p for p in self.get_catalogue() if 0 < p["stock"] < threshold]

    def get_out_of_stock_products(self) -> List[Dict]:
        """Get products with zero stock."""
        return [p for p in self.get_catalogue() if p["stock"] == 0]

    def get_stats_summary(self) -> Dict[str, Any]:
        """Get summary statistics for context."""
        catalogue = self.get_catalogue()
        dealers = self.get_dealers()

        total_products = len(catalogue)
        total_dealers = len(dealers)
        low_stock = len([p for p in catalogue if 0 < p["stock"] < 15])
        out_of_stock = len([p for p in catalogue if p["stock"] == 0])
        total_value = sum(float(p["price"]) * p["stock"] for p in catalogue)

        return {
            "total_products": total_products,
            "total_dealers": total_dealers,
            "low_stock_count": low_stock,
            "out_of_stock_count": out_of_stock,
            "total_inventory_value": round(total_value, 2),
            "categories": self.get_categories(),
            "brands": self.get_brands()[:20],  # Top 20
        }

    def format_product_for_reply(self, product: Dict) -> str:
        """Format a product for chat reply."""
        stock_status = "Out of Stock" if product["stock"] == 0 else (
            f"Low Stock ({product['stock']})" if product["stock"] < 15 else f"{product['stock']} in stock"
        )
        return (
            f"• {product['name']} ({product['sku']}) — ₹{product['price']} — "
            f"{stock_status} — {product['category']} — Fits: {product['vehicle_fitment']}"
        )

    def format_dealer_for_reply(self, dealer: Dict) -> str:
        """Format a dealer for chat reply."""
        location = f" ({dealer['city']})" if dealer.get("city") else ""
        return f"• {dealer['name']} [{dealer['dealer_code']}] {location}"

    def build_system_prompt(self) -> str:
        """Build system prompt with company context."""
        stats = self.get_stats_summary()
        info = self._company_info

        return f"""You are the AI Assistant for {info['name']} — {info['tagline']}.

COMPANY CONTEXT:
{info['description']}

KEY CAPABILITIES:
{chr(10).join(f"- {c}" for c in info['capabilities'])}

CURRENT INVENTORY SNAPSHOT:
- Total Products: {stats['total_products']}
- Total Dealers: {stats['total_dealers']}
- Low Stock Items (<15): {stats['low_stock_count']}
- Out of Stock: {stats['out_of_stock_count']}
- Inventory Value: ₹{stats['total_inventory_value']:,.2f}
- Categories: {', '.join(stats['categories'])}
- Top Brands: {', '.join(stats['brands'])}

POLICIES:
- Payment: {info['policies']['payment_terms']}
- Minimum Order: {info['policies']['minimum_order']}
- Shipping: {info['policies']['shipping']}
- Returns: {info['policies']['returns']}
- GST: {info['policies']['gst']}

AVAILABLE TOOLS (you can invoke these via tool_calls in your response):
1. search_parts(query, vehicle?, category?, brand?) — Search parts catalogue
2. check_stock(sku) — Check real-time stock for a SKU
3. create_draft_order(dealer_id, items) — Create a draft order for a dealer

RESPONSE FORMAT:
- Be concise and helpful
- Use ₹ for currency with 2 decimals
- Reference SKUs when mentioning parts
- If creating orders, confirm details before proceeding
- For stock questions, use check_stock tool
- For part searches, use search_parts tool
- For orders, use create_draft_order tool

When the user asks about parts, stock, or orders, prefer using tools over general knowledge.
If unsure, ask clarifying questions.
"""

    def build_context_summary(self) -> str:
        """Build a brief context summary for the assistant."""
        stats = self.get_stats_summary()
        return (
            f"VIKMO DealerDesk — {stats['total_products']} parts across {len(stats['categories'])} categories, "
            f"{stats['total_dealers']} dealers. "
            f"Stock: {stats['low_stock_count']} low, {stats['out_of_stock_count']} out. "
            f"Categories: {', '.join(stats['categories'])}. "
            f"Top brands: {', '.join(stats['brands'][:10])}."
        )


# Global instance
company_context = CompanyContext()


def get_company_context() -> CompanyContext:
    """Get the global company context instance."""
    return company_context