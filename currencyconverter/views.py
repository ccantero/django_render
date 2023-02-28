from django.shortcuts import render
from django.views import generic

from currencyconverter.models import Currency,ExchangeRate
from currencyconverter.forms import UVAForm
from currencyconverter.serializers import CurrencySerializer,ExchangeRateSerializer, CurrencyDetailSerializer

from rest_framework import viewsets
from rest_framework import permissions

class UVAFormView(generic.FormView):
    template_name = 'currencyconverter/uvaform.html'
    form_class = UVAForm
    success_url = '/thanks/'

    def form_valid(self, form):
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        green_quote = 1.0
        uva_quote = 1.0
        blue_quote = 1.0

        if len(ExchangeRate.objects.filter(key__iexact="USD_OFFICIAL")) == 1:
            a_exchangerate = ExchangeRate.objects.filter(key__iexact="USD_OFFICIAL")[0]
            green_quote = a_exchangerate.last_quote

        if len(ExchangeRate.objects.filter(key__iexact="USD_BLUE")) == 1:
            a_exchangerate = ExchangeRate.objects.filter(key__iexact="USD_BLUE")[0]
            blue_quote = a_exchangerate.last_quote

        if len(ExchangeRate.objects.filter(key__iexact="ARS_UVA")) == 1:
            a_exchangerate = ExchangeRate.objects.filter(key__iexact="ARS_UVA")[0]
            uva_quote = a_exchangerate.last_quote

        if self.request.GET.get('cuota') :
            # I have receieved on URL
            context['cuota'] = self.request.GET.get('cuota')
            context['cuota_calculada'] = float(self.request.GET.get('cuota')) * uva_quote
        elif self.request.COOKIES.get('_cuota__') and self.request.COOKIES.get('_cuota__') != "undefined":
            context['cuota'] = self.request.COOKIES.get('_cuota__')
            context['cuota_calculada'] = float(self.request.COOKIES.get('_cuota__')) * uva_quote
        else:
            context['cuota'] = 0.0
            context['cuota_calculada'] = 0.0

        if self.request.GET.get('saldo'):
            # I have receieved on URL
            context['saldo'] = self.request.GET.get('saldo')
            context['saldo_calculado_usd'] = float(self.request.GET.get('saldo')) * uva_quote / green_quote
            context['saldo_calculado_usd_blue'] = float(self.request.GET.get('saldo')) * uva_quote / blue_quote
        elif self.request.COOKIES.get('_deuda__') and self.request.COOKIES.get('_deuda__') != "undefined":
            context['saldo'] = self.request.COOKIES.get('_deuda__')
            context['saldo_calculado_usd'] = float(self.request.COOKIES.get('_deuda__')) * uva_quote / green_quote
            context['saldo_calculado_usd_blue'] = float(self.request.COOKIES.get('_deuda__')) * uva_quote / blue_quote
        else:
            context['saldo'] = 0.0
            context['saldo_calculado_usd'] = 0.0
            context['saldo_calculado_usd_blue'] = 0.0

        return context

from rest_framework.renderers import TemplateHTMLRenderer, JSONRenderer

class CurrencyViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows currencies to be viewed or edited.
    """
    queryset = Currency.objects.all().order_by('-key')
    serializer_class = CurrencyDetailSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    http_method_names = ['get','post']

    def get_serializer_class(self):
        if self.action == 'list':
            return CurrencySerializer

        return super().get_serializer_class()

class ExchangeRatesViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows ExchangeRates to be viewed or edited.
    """
    queryset = ExchangeRate.objects.all().order_by('-key')
    serializer_class = ExchangeRateSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    http_method_names = ['get','post']

class ExchangeRatesHTMLViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """
    schema=None # Avoid to be included on Swagger page
    queryset = ExchangeRate.objects.all().order_by('-key')
    serializer_class = ExchangeRateSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    renderer_classes = (TemplateHTMLRenderer,)
    template_name = "currencyconverter/exchangerate_list.html"
    
from django.utils import timezone
from django.http import JsonResponse
from datetime import datetime

import requests

def get_ARSUVA_rate():
    response = requests.get('https://www.bancociudad.com.ar/institucional/herramientas/getCotizaciones')
    data = response.json()
    uva_value = data['data']['Uva']['compra'].replace('$','').strip().replace(',','.')
    quote = float(uva_value)
    return quote

def update_ARSUSD_rate(now):
    response = requests.get('https://www.dolarsi.com/api/api.php?type=valoresprincipales')
    json_obj = response.json()
    for obj in json_obj:
        if obj['casa']['nombre'] == 'Dolar Blue':
            data = obj['casa']
            quote_blue = float(data['compra'].replace(',','.'))
        
        if obj['casa']['nombre'] == 'Dolar Oficial':
            data = obj['casa']
            quote_green = float(data['compra'].replace(',','.'))

    for key in ['USD_OFFICIAL','USD_BLUE']:
        query_set = ExchangeRate.objects.filter(key__iexact=key)
        if len(query_set) == 1:
            a_exchangerate = query_set[0]
            if key == 'USD_OFFICIAL':
                a_exchangerate.last_quote = quote_green
            
            if key == 'USD_BLUE':
                a_exchangerate.last_quote = quote_blue

            a_exchangerate.last_update = now
            a_exchangerate.save()

def update_rates(request):
    now = timezone.now()
    for key in ['ARS_UVA', 'USD_OFFICIAL','USD_BLUE']:
        query_set = ExchangeRate.objects.filter(key__iexact=key)
        if len(query_set) == 1:
            a_exchangerate = query_set[0]
            last_update = a_exchangerate.last_update
            dt_begin = datetime.fromtimestamp(last_update.timestamp())
            dt_end = datetime.fromtimestamp(now.timestamp())
            difference = dt_end - dt_begin
            seconds = difference.total_seconds()
            if seconds > 360:
                if key == 'ARS_UVA':
                    new_quote = get_ARSUVA_rate()
                    a_exchangerate.last_quote = new_quote
                    a_exchangerate.last_update = now
                    a_exchangerate.save()
                else:
                    update_ARSUSD_rate(now)

    data = {
		'ajax_answer': True
	}
    
    return JsonResponse(data)