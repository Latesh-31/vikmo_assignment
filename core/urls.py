from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("dashboard/metrics/", views.dashboard_metrics),
]
