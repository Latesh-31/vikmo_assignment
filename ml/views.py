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

from .assistant_context import get_company_context
from .groq_assistant import get_groq_assistant


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
    Uses Groq LLM with tool calling per API Contract §9.
    """
    def post(self, request):
        session_id = request.data.get("session_id")
        dealer_id = request.data.get("dealer_id")
        message = (request.data.get("message") or "").strip()

        if not session_id:
            raise ValidationError("Field 'session_id' is required.")
        if not dealer_id:
            raise ValidationError("Field 'dealer_id' is required.")
        if not message:
            raise ValidationError("Field 'message' cannot be empty.")

        try:
            dealer_id = int(dealer_id)
        except (ValueError, TypeError):
            raise ValidationError("Field 'dealer_id' must be an integer.")

        assistant = get_groq_assistant()
        result = assistant.chat(session_id=session_id, dealer_id=dealer_id, message=message)

        return Response(result, status=status.HTTP_200_OK)
