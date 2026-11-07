from datetime import date

from django import forms


class TerapiasAmbulatoriasForm(forms.Form):
    fecha = forms.DateField(
        label="Fecha",
        widget=forms.DateInput(attrs={"type": "date", "required": True}),
    )
    nombre_apellido = forms.CharField(
        label="Nombre y apellido",
        max_length=120,
        widget=forms.TextInput(attrs={"autocomplete": "name", "required": True}),
    )
    dni = forms.CharField(
        label="DNI",
        max_length=20,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "required": True}),
    )
    edad = forms.IntegerField(
        label="Edad",
        min_value=0,
        max_value=130,
        widget=forms.NumberInput(attrs={"required": True}),
    )
    diagnostico = forms.CharField(
        label="Diagnóstico",
        widget=forms.Textarea(attrs={"rows": 3, "required": True}),
    )
    prestacion = forms.CharField(
        label="Prestación",
        widget=forms.Textarea(attrs={"rows": 2, "required": True}),
    )
    frecuencia_semanal = forms.CharField(
        label="Frecuencia semanal",
        max_length=120,
        help_text="Ej.: 2 veces por semana",
        widget=forms.TextInput(attrs={"required": True}),
    )
    periodo_desde = forms.CharField(
        label="Periodo desde",
        help_text="Mes / año de inicio",
        widget=forms.TextInput(attrs={"type": "month", "required": True}),
    )
    periodo_hasta = forms.CharField(
        label="Periodo hasta",
        help_text="Mes / año de fin",
        widget=forms.TextInput(attrs={"type": "month", "required": True}),
    )

    @staticmethod
    def _parse_month(value: str) -> date:
        year_s, month_s = value.split("-", 1)
        return date(int(year_s), int(month_s), 1)

    def clean_periodo_desde(self):
        return self._parse_month(self.cleaned_data["periodo_desde"])

    def clean_periodo_hasta(self):
        return self._parse_month(self.cleaned_data["periodo_hasta"])

    def clean(self):
        cleaned = super().clean()
        desde = cleaned.get("periodo_desde")
        hasta = cleaned.get("periodo_hasta")
        if isinstance(desde, date) and isinstance(hasta, date) and hasta < desde:
            self.add_error(
                "periodo_hasta",
                "El mes hasta debe ser posterior o igual a desde.",
            )
        return cleaned
