from django.urls import path

from dashboard import views


urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/analytics/", views.dashboard_analytics, name="dashboard_analytics"),
    path("dashboard/demo/", views.dashboard_demo, name="dashboard_demo"),
    path("dashboard/dust/", views.dust_dashboard, name="dust_dashboard"),
    path("dashboard/dust/detail/", views.dust_detail, name="dust_detail"),
    path("dashboard/dust/corrections/new/", views.manual_correction_new, name="manual_correction_new"),
    path("dashboard/dust/corrections/<str:status>/", views.manual_corrections, name="manual_corrections"),
    path("dashboard/dust/corrections/detail/<int:correction_id>/", views.manual_correction_detail, name="manual_correction_detail"),
]
