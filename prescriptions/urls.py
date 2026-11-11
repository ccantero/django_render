from django.urls import path

from .views import TerapiasAmbulatoriasView

app_name = "prescriptions"

urlpatterns = [
    path("", TerapiasAmbulatoriasView.as_view(), name="terapias_ambulatorias"),
]
