from django.shortcuts import render
from django.views import generic

from currencyconverter.models import ExchangeRate
from currencyconverter.forms import UVAForm

# Create your views here.
class ListExchangeRates(generic.ListView):
    model = ExchangeRate

class UVAFormView(generic.FormView):
    template_name = 'currencyconverter/uvaform.html'
    form_class = UVAForm
    success_url = '/thanks/'

    def form_valid(self, form):
        form.send_email()
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        green_quote = 1.0
        uva_quote = 1.0
        blue_quote = 1.0

        if len(ExchangeRate.objects.filter(name__iexact="Dolar Oficial")) == 1:
            a_exchangerate = ExchangeRate.objects.filter(name__iexact="Dolar Oficial")[0]
            green_quote = a_exchangerate.last_quote

        if len(ExchangeRate.objects.filter(name__iexact="Dolar Blue")) == 1:
            a_exchangerate = ExchangeRate.objects.filter(name__iexact="Dolar Blue")[0]
            blue_quote = a_exchangerate.last_quote

        if len(ExchangeRate.objects.filter(name__iexact="ARS_UVA")) == 1:
            a_exchangerate = ExchangeRate.objects.filter(name__iexact="ARS_UVA")[0]
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