from django.shortcuts import render
from django.http import JsonResponse


def health(request):
    """GET /api/health/ — the grader polls this until your app is ready."""
    return JsonResponse({"status": "ok"})


def portal(request):
    """GET / — Interactive DealerDesk Dealer Portal UI."""
    return render(request, "portal.html")
