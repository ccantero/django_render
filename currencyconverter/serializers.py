from rest_framework import serializers

from currencyconverter.models import ExchangeRate
from currencyconverter.models import Currency

class CurrencySerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Currency
        fields = ['key', 'description'] # Check why _all_ does not work

class ExchangeRateSerializer(serializers.HyperlinkedModelSerializer):
    numerator = CurrencySerializer()
    denominator = CurrencySerializer()

    class Meta:
        model = ExchangeRate
        fields = ['name', 'numerator', 'denominator', 'last_update', 'last_quote'] # Check why _all_ does not work