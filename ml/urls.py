from django.urls import path
from ml.views import ForecastDetailView, ReorderSuggestionsView, AssistantChatView

urlpatterns = [
    path("forecast/<str:sku>/", ForecastDetailView.as_view(), name="forecast-detail"),
    path("reorder-suggestions/", ReorderSuggestionsView.as_view(), name="reorder-suggestions"),
    path("assistant/chat/", AssistantChatView.as_view(), name="assistant-chat"),
]
