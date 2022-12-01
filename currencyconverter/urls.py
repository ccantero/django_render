from django.urls import path
from currencyconverter import views

app_name = 'exchangerates'

urlpatterns = [
	path('',views.ListExchangeRates.as_view(),name='all'),
	path('calculadora_uva/',views.UVAFormView.as_view(), {'cuota':0, 'saldo':0}, name='calculadora'),
]