from django.urls import path
from dashboard.bot_diagnostics_api import BotHealthAPIView, ETHInventoryAPIView

from dashboard import views


urlpatterns = [
    path("api/bot/health", BotHealthAPIView.as_view(), name="bot-api-health"),
    path("api/bot/inventory/ETHUSDT", ETHInventoryAPIView.as_view(), name="bot-api-eth-inventory"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/analytics/", views.dashboard_analytics, name="dashboard_analytics"),
    path("dashboard/exit-status/", views.dashboard_exit_status, name="dashboard_exit_status"),
    path("dashboard/churn/", views.dashboard_churn, name="dashboard_churn"),
    path("dashboard/operational-kpis/", views.dashboard_operational_kpis, name="dashboard_operational_kpis"),
    path("dashboard/demo/", views.dashboard_demo, name="dashboard_demo"),
    path("dashboard/dust/", views.dust_dashboard, name="dust_dashboard"),
    path("dashboard/dust/detail/", views.dust_detail, name="dust_detail"),
    path("dashboard/dust/corrections/new/", views.manual_correction_new, name="manual_correction_new"),
    path("dashboard/dust/corrections/<str:status>/", views.manual_corrections, name="manual_corrections"),
    path("dashboard/dust/corrections/detail/<int:correction_id>/", views.manual_correction_detail, name="manual_correction_detail"),
]
