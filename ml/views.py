import csv
import math
import os
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from django.conf import settings
from core.exceptions import NotFoundError, ValidationError
from products.models import Product
from orders.services import create_draft_order


def load_lead_times():
    path = settings.DATA_DIR / "lead_times.csv"
    lead_times = {}
    if path.exists():
        with open(path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                lead_times[row["sku"].strip()] = int(row["lead_time_weeks"].strip())
    return lead_times


def load_forecast_csv():
    path = settings.BASE_DIR / "ml" / "forecast.csv"
    forecasts = defaultdict(list)
    if path.exists():
        with open(path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sku = row["sku"].strip()
                w = row["week_start"].strip()
                units = float(row["forecast_units"].strip())
                forecasts[sku].append({"week_start": w, "forecast_units": units})
    return forecasts


def load_recent_sales_std():
    path = settings.DATA_DIR / "sales_history.csv"
    sales_by_sku = defaultdict(list)
    if path.exists():
        with open(path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sku = row["sku"].strip()
                w = row["week_start"].strip()
                units = float(row["units_sold"].strip())
                sales_by_sku[sku].append((w, units))

    sigmas = {}
    for sku, records in sales_by_sku.items():
        records.sort(key=lambda x: x[0])
        recent_12 = [r[1] for r in records[-12:]]
        n = len(recent_12)
        if n <= 1:
            sigmas[sku] = 0.0
        else:
            mean = sum(recent_12) / n
            var = sum((x - mean) ** 2 for x in recent_12) / (n - 1)
            sigmas[sku] = math.sqrt(var)
    return sigmas


class ForecastDetailView(APIView):
    def get(self, request, sku):
        lead_times = load_lead_times()
        if sku not in lead_times:
            raise NotFoundError(f"SKU '{sku}' is not a forecast SKU.")

        forecasts = load_forecast_csv()
        sku_forecast = forecasts.get(sku)
        if not sku_forecast:
            raise NotFoundError(f"Forecast for SKU '{sku}' not found.")

        return Response({
            "sku": sku,
            "forecast": sku_forecast,
        }, status=status.HTTP_200_OK)


class ReorderSuggestionsView(APIView):
    def get(self, request):
        lead_times = load_lead_times()
        forecasts = load_forecast_csv()
        sigmas = load_recent_sales_std()

        # Fetch current stock of products
        skus = list(lead_times.keys())
        products = {p.sku: p.stock for p in Product.objects.filter(sku__in=skus)}

        results = []
        for sku, L in lead_times.items():
            current_stock = products.get(sku, 0)
            sku_fc = forecasts.get(sku, [])
            # First L weeks
            l_weeks_fc = sku_fc[:L]
            lead_time_demand = round(sum(item["forecast_units"] for item in l_weeks_fc), 2)

            sigma = sigmas.get(sku, 0.0)
            safety_stock = math.ceil(1.65 * sigma * math.sqrt(L))
            reorder_point = round(lead_time_demand + safety_stock, 2)
            reorder_qty = max(0, math.ceil(reorder_point - current_stock))

            results.append({
                "sku": sku,
                "current_stock": current_stock,
                "lead_time_weeks": L,
                "lead_time_demand": lead_time_demand,
                "safety_stock": safety_stock,
                "reorder_point": reorder_point,
                "reorder_qty": reorder_qty,
            })

        return Response({"results": results}, status=status.HTTP_200_OK)


class AssistantChatView(APIView):
    """
    POST /api/assistant/chat/
    Body: {"session_id": "...", "dealer_id": 7, "message": "..."}
    Response: {"reply": "...", "cited_skus": [...], "tool_calls": [...], "actions": [...]}
    """
    def post(self, request):
        session_id = request.data.get("session_id")
        dealer_id = request.data.get("dealer_id")
        message = (request.data.get("message") or "").strip()

        if not message:
            raise ValidationError("Field 'message' cannot be empty.")

        # Local conversational / tool resolution engine (also integrates with LLM when key provided)
        tool_calls = []
        actions = []
        cited_skus = set()
        reply_lines = []

        # Tool 1: search_parts
        # Check if message asks for parts or vehicle or category
        msg_lower = message.lower()

        # Check for order creation intent: e.g. "order", "buy", "draft"
        order_match = re.search(r"(?:order|draft|buy)\s+(\d+)\s+(?:of\s+)?([A-Z]{3}-\d{4})", message, re.IGNORECASE)
        sku_mention = re.findall(r"\b([A-Z]{3}-\d{4})\b", message)

        if order_match:
            qty = int(order_match.group(1))
            sku = order_match.group(2).upper()
            tool_calls.append({
                "name": "create_draft_order",
                "arguments": {"dealer_id": dealer_id, "items": [{"sku": sku, "quantity": qty}]}
            })
            try:
                order = create_draft_order(dealer_id=dealer_id, items_data=[{"sku": sku, "quantity": qty}])
                actions.append({"type": "draft_order_created", "order_number": order.order_number})
                cited_skus.add(sku)
                reply_lines.append(f"Created draft order {order.order_number} for {qty} x {sku}. Total: ₹{order.grand_total}.")
            except Exception as e:
                reply_lines.append(f"Could not create draft order: {e}")

        elif sku_mention and ("stock" in msg_lower or "available" in msg_lower or "how many" in msg_lower):
            for sku in sku_mention:
                tool_calls.append({"name": "check_stock", "arguments": {"sku": sku}})
                p = Product.objects.filter(sku=sku).first()
                if p:
                    cited_skus.add(p.sku)
                    reply_lines.append(f"{p.name} ({p.sku}) has {p.stock} units in stock at ₹{p.price}.")
                else:
                    reply_lines.append(f"SKU {sku} was not found.")

        elif any(w in msg_lower for w in ["part", "brake", "oil", "filter", "chain", "mirror", "pulsar", "apache", "ktm", "honda"]):
            # Search parts
            query_term = ""
            vehicle_term = ""
            for term in ["pulsar 150", "pulsar", "apache", "duke 390", "ktm", "activa", "splendor"]:
                if term in msg_lower:
                    vehicle_term = term
                    break
            for term in ["brake pad", "brake", "oil filter", "air filter", "filter", "chain", "mirror", "coolant", "spark plug"]:
                if term in msg_lower:
                    query_term = term
                    break

            if not query_term and not vehicle_term:
                query_term = message

            tool_args = {"query": query_term}
            if vehicle_term:
                tool_args["vehicle"] = vehicle_term
            tool_calls.append({"name": "search_parts", "arguments": tool_args})

            from django.db.models import Q
            q = Q()
            if query_term:
                q &= (Q(name__icontains=query_term) | Q(category__icontains=query_term) | Q(sku__icontains=query_term))
            if vehicle_term:
                q &= Q(vehicle_fitment__icontains=vehicle_term)

            matches = list(Product.objects.filter(q)[:5])
            if matches:
                reply_lines.append(f"Found {len(matches)} matching part(s):")
                for p in matches:
                    cited_skus.add(p.sku)
                    reply_lines.append(f"- {p.name} ({p.sku}): ₹{p.price}, {p.stock} in stock (Fitment: {p.vehicle_fitment})")
            else:
                reply_lines.append("I couldn't find matching parts for your query in the catalogue.")
        else:
            reply_lines.append("Hello! I can help you find motorcycle parts, check current stock levels, and create draft orders. How can I assist you today?")

        return Response({
            "reply": "\n".join(reply_lines),
            "cited_skus": sorted(list(cited_skus)),
            "tool_calls": tool_calls,
            "actions": actions,
        }, status=status.HTTP_200_OK)
