from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from products.models import Product
from dealers.models import Dealer
from orders.models import Order


def health(request):
    """GET /api/health/ — the grader polls this until your app is ready."""
    return JsonResponse({"status": "ok"})


def portal(request):
    """GET / — Interactive DealerDesk Dealer Portal UI."""
    return render(request, "portal.html")


@require_GET
def dashboard_metrics(request):
    """GET /api/dashboard/metrics/ — Dashboard overview metrics.
    
    Optional query param: dealer_id — filters orders and metrics to a specific dealer.
    If omitted, shows global metrics.
    """
    dealer_id = request.GET.get('dealer_id')
    
    # Base querysets
    products_qs = Product.objects.all()
    dealers_qs = Dealer.objects.all()
    orders_qs = Order.objects.select_related('dealer')
    
    if dealer_id:
        try:
            dealer_id = int(dealer_id)
            orders_qs = orders_qs.filter(dealer_id=dealer_id)
        except (ValueError, TypeError):
            pass  # Ignore invalid dealer_id, fall back to global
    
    total_products = products_qs.count()
    total_dealers = dealers_qs.count()
    total_orders = orders_qs.count()
    low_stock_count = products_qs.filter(stock__lt=15, stock__gt=0).count()
    out_of_stock_count = products_qs.filter(stock=0).count()

    # Recent orders (last 10)
    recent_orders_qs = orders_qs.order_by('-created_at')[:10]
    recent_orders = [
        {
            'order_number': o.order_number,
            'dealer_name': o.dealer.name,
            'status': o.status,
            'grand_total': str(o.grand_total),
            'created_at': o.created_at.isoformat(),
        }
        for o in recent_orders_qs
    ]

    return JsonResponse({
        'total_products': total_products,
        'total_dealers': total_dealers,
        'total_orders': total_orders,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'recent_orders': recent_orders,
    })
