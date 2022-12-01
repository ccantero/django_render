from django import forms

class UVAForm(forms.Form):
    amount_cuota = forms.FloatField()
    amount_deuda = forms.FloatField()

    def send_email(self):
        # send email using the self.cleaned_data dictionary
        pass