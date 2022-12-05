from django.urls import include, path
from currencyconverter import views
from rest_framework import routers

router = routers.DefaultRouter()
router.register(r'currencies', views.CurrencyViewSet)
router.register(r'exchangerates', views.ExchangeRatesViewSet)

app_name = 'exchangerates'

urlpatterns = [
	#path('',views.ListExchangeRates.as_view(),name='all'),
	path('', include(router.urls)),
	path('calculadora_uva/',views.UVAFormView.as_view(), {'cuota':0, 'saldo':0}, name='calculadora'),
	path('api-auth/', include('rest_framework.urls', namespace='rest_framework'))
]