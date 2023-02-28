from rest_framework import serializers

from currencyconverter.models import ExchangeRate
from currencyconverter.models import Currency

class CurrencySerializer(serializers.HyperlinkedModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="currencyconverter:currency-detail")

    class Meta:
        model = Currency
        fields = ['key','url'] # Check why _all_ does not work

class CurrencyDetailSerializer(CurrencySerializer):
    class Meta(CurrencySerializer.Meta):
        fields = CurrencySerializer.Meta.fields + ['description']

class ExchangeRateSerializer(serializers.HyperlinkedModelSerializer):
    numerator = serializers.PrimaryKeyRelatedField(queryset=Currency.objects.all())
    denominator = serializers.PrimaryKeyRelatedField(queryset=Currency.objects.all())
    #last_update = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S")
    url = serializers.HyperlinkedIdentityField(view_name="currencyconverter:exchangerate-detail")

    class Meta:
        model = ExchangeRate
        fields = ['key', 'url', 'description', 'numerator', 'denominator', 'last_update', 'last_quote'] # Check why _all_ does not work