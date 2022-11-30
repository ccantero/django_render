from django.urls import path
from currencyconverter import views

app_name = 'exchangerates'

urlpatterns = [
	path('',views.ListExchangeRates.as_view(),name='all')
]