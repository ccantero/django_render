from decimal import Decimal

from django import forms

from core.models import ManualCorrection


class ManualCorrectionRequestForm(forms.ModelForm):
	class Meta:
		model = ManualCorrection
		fields = [
			"correction_type",
			"symbol",
			"asset",
			"quantity",
			"price_usdt",
			"reason",
			"source_detection_id",
			"review_note",
		]
		widgets = {
			"correction_type": forms.Select(attrs={"class": "form-control"}),
			"symbol": forms.TextInput(attrs={"class": "form-control"}),
			"asset": forms.TextInput(attrs={"class": "form-control"}),
			"quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.000000000000000001"}),
			"price_usdt": forms.NumberInput(attrs={"class": "form-control", "step": "0.000000000000000001"}),
			"reason": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
			"source_detection_id": forms.NumberInput(attrs={"class": "form-control"}),
			"review_note": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
		}

	def clean_quantity(self):
		quantity = self.cleaned_data["quantity"]
		if quantity <= Decimal("0"):
			raise forms.ValidationError("Quantity must be positive.")
		return quantity

	def clean_price_usdt(self):
		price_usdt = self.cleaned_data["price_usdt"]
		if price_usdt <= Decimal("0"):
			raise forms.ValidationError("Price USDT must be positive.")
		return price_usdt
