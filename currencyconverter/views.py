from django.shortcuts import render
from django.views import generic

from currencyconverter.models import ExchangeRate

# Create your views here.
class ListExchangeRates(generic.ListView):
    model = ExchangeRate