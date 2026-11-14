from django.urls import path

from .views import (
    EscolaridadEspecialView,
    GalenoPrescriptionsHubView,
    TerapiasAmbulatoriasView,
)

app_name = "prescriptions"

urlpatterns = [
    path(
        "prescripciones-galeno/",
        GalenoPrescriptionsHubView.as_view(),
        name="galeno_hub",
    ),
    path(
        "terapias-ambulatorias/",
        TerapiasAmbulatoriasView.as_view(),
        name="terapias_ambulatorias",
    ),
    path(
        "escolaridad-especial/",
        EscolaridadEspecialView.as_view(),
        name="escolaridad_especial",
    ),
]
