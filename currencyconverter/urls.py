from django.urls import include, path
from currencyconverter import views
from rest_framework import routers

router = routers.DefaultRouter()
router.register(r'json/currencies', views.CurrencyViewSet)
router.register(r'json/exchangerates', views.ExchangeRatesViewSet)


app_name = 'currencyconverter'

urlpatterns = [
	path('manifest.json', views.pwa_manifest, name='pwa-manifest'),
	path('service-worker.js', views.pwa_service_worker, name='pwa-service-worker'),
	path('', include(router.urls)),
	path('calculadora_uva/',views.UVAFormView.as_view(), {'cuota':0, 'saldo':0}, name='calculadora'),
	path('exchangerates/',views.ExchangeRatesHTMLViewSet.as_view({'get': 'list'}), name='cotizaciones'),
	path('ajax/update_rates', views.update_rates, name='update_rates')
]
