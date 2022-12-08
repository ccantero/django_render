from django.urls import include, path
from currencyconverter import views
from rest_framework import routers

router = routers.DefaultRouter()
router.register(r'json/currencies', views.CurrencyViewSet)
router.register(r'json/exchangerates', views.ExchangeRatesViewSet, basename='exchangerate')


app_name = 'currencyconverter'

urlpatterns = [
	path('', include(router.urls)),
	path('calculadora_uva/',views.UVAFormView.as_view(), {'cuota':0, 'saldo':0}, name='calculadora'),
	path('exchangerates/',views.ExchangeRatesHTMLViewSet.as_view({'get': 'list'}), name='exchangerate-list'),
	path('exchangerates/<slug:key>/', views.ExchangeRateUpdateView.as_view(), name='exchangerate-detail'),
]