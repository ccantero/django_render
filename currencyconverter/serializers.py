from rest_framework import serializers

from currencyconverter.models import ExchangeRate
from currencyconverter.models import Currency

class CurrencySerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Currency
        fields = ['key', 'description'] # Check why _all_ does not work

class ExchangeRateSerializer(serializers.HyperlinkedModelSerializer):
    numerator = serializers.PrimaryKeyRelatedField(queryset=Currency.objects.all())
    denominator = serializers.PrimaryKeyRelatedField(queryset=Currency.objects.all())
    last_update = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S")


    class Meta:
        model = ExchangeRate
        depth = 1
        fields = ['key', 'description', 'numerator', 'denominator', 'last_update', 'last_quote'] # Check why _all_ does not work
