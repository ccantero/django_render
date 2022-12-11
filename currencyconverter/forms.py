from django import forms
from currencyconverter import models

class UVAForm(forms.Form):
    amount_cuota = forms.FloatField()
    amount_deuda = forms.FloatField()