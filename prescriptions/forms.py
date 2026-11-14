from datetime import date
import re

from django import forms

from .pdf import (
    LAYOUT_ESCOLARIDAD,
    LAYOUT_TERAPIAS,
    PrescriptionLayoutError,
    plan_overlay,
)

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


class _PrescriptionFormBase(forms.Form):
    """Shared Galeno prescription fields and capacity validation."""

    layout = LAYOUT_TERAPIAS

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
        if not isinstance(value, str):
            raise forms.ValidationError("Ingresá un mes válido (AAAA-MM).")
        match = _MONTH_RE.fullmatch(value.strip())
        if not match:
            raise forms.ValidationError("Ingresá un mes válido (AAAA-MM).")
        year = int(match.group(1))
        month = int(match.group(2))
        if month < 1 or month > 12:
            raise forms.ValidationError("El mes debe estar entre 01 y 12.")
        try:
            return date(year, month, 1)
        except ValueError as exc:
            raise forms.ValidationError("Ingresá un mes válido (AAAA-MM).") from exc

    def clean_periodo_desde(self):
        return self._parse_month(self.cleaned_data["periodo_desde"])

    def clean_periodo_hasta(self):
        return self._parse_month(self.cleaned_data["periodo_hasta"])

    def _capacity_required_fields(self) -> tuple[str, ...]:
        raise NotImplementedError

    def clean(self):
        cleaned = super().clean()
        desde = cleaned.get("periodo_desde")
        hasta = cleaned.get("periodo_hasta")
        if isinstance(desde, date) and isinstance(hasta, date) and hasta < desde:
            self.add_error(
                "periodo_hasta",
                "El mes hasta debe ser posterior o igual a desde.",
            )

        required = self._capacity_required_fields()
        if any(
            field not in cleaned or cleaned.get(field) in (None, "")
            for field in required
        ):
            return cleaned
        if self.errors:
            return cleaned

        try:
            plan_overlay(cleaned, layout=self.layout)
        except PrescriptionLayoutError as exc:
            field = exc.field if exc.field in self.fields else None
            if field is None and exc.field.startswith("fecha"):
                field = "fecha"
            if field is None and exc.field.startswith("periodo_desde"):
                field = "periodo_desde"
            if field is None and exc.field.startswith("periodo_hasta"):
                field = "periodo_hasta"
            if field and field in self.fields:
                self.add_error(field, exc.message)
            else:
                self.add_error(None, exc.message)
        return cleaned


class TerapiasAmbulatoriasForm(_PrescriptionFormBase):
    layout = LAYOUT_TERAPIAS

    frecuencia_semanal = forms.CharField(
        label="Frecuencia semanal",
        max_length=120,
        help_text="Ej.: 2 veces por semana",
        widget=forms.TextInput(attrs={"required": True}),
    )

    def _capacity_required_fields(self) -> tuple[str, ...]:
        return (
            "fecha",
            "nombre_apellido",
            "dni",
            "edad",
            "diagnostico",
            "prestacion",
            "frecuencia_semanal",
            "periodo_desde",
            "periodo_hasta",
        )


class EscolaridadEspecialForm(_PrescriptionFormBase):
    layout = LAYOUT_ESCOLARIDAD

    prestacion = forms.CharField(
        label="Prestación",
        widget=forms.Textarea(attrs={"rows": 1, "required": True}),
    )
    jornada = forms.CharField(
        label="Jornada",
        max_length=80,
        help_text="Ej.: Simple, Doble, Completa",
        widget=forms.TextInput(attrs={"required": True}),
    )

    def _capacity_required_fields(self) -> tuple[str, ...]:
        return (
            "fecha",
            "nombre_apellido",
            "dni",
            "edad",
            "diagnostico",
            "prestacion",
            "jornada",
            "periodo_desde",
            "periodo_hasta",
        )
