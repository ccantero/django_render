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

        if self.request.GET.get('cuota') :
            # I have receieved on URL
            context['cuota'] = self.request.GET.get('cuota')
            #context['cuota_calculada'] = float(self.request.GET.get('cuota')) * uva_quote
        elif self.request.COOKIES.get('_cuota__') and self.request.COOKIES.get('_cuota__') != "undefined":
            context['cuota'] = self.request.COOKIES.get('_cuota__')
            #context['cuota_calculada'] = float(self.request.COOKIES.get('_cuota__')) * uva_quote
        else:
            context['cuota'] = 0.0
            #context['cuota_calculada'] = 0.0

        return context