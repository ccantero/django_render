from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from .forms import EscolaridadEspecialForm, TerapiasAmbulatoriasForm
from .pdf import LAYOUT_ESCOLARIDAD, LAYOUT_TERAPIAS, fill_prescription_pdf


class GalenoPrescriptionsHubView(View):
    """Shared entry point for Galeno prescription forms."""

    template_name = "prescriptions/hub.html"

    def get(self, request):
        return render(request, self.template_name)


class _PrescriptionFormView(View):
    template_name = "prescriptions/form.html"
    form_class = TerapiasAmbulatoriasForm
    layout = LAYOUT_TERAPIAS
    filename_prefix = "prescripcion_terapias"
    page_title = "Terapias ambulatorias"
    page_eyebrow = "Galeno · Rehabilitación"
    page_lede = (
        "Completá los datos y descargá la prescripción médica en PDF lista para firmar."
    )

    def _context(self, form):
        return {
            "form": form,
            "page_title": self.page_title,
            "page_eyebrow": self.page_eyebrow,
            "page_lede": self.page_lede,
        }

    def get(self, request):
        return render(request, self.template_name, self._context(self.form_class()))

    def post(self, request):
        form = self.form_class(request.POST)
        if not form.is_valid():
            return render(
                request, self.template_name, self._context(form), status=400
            )

        pdf_bytes = fill_prescription_pdf(form.cleaned_data, layout=self.layout)
        dni = form.cleaned_data["dni"]
        filename = f"{self.filename_prefix}_{dni}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class TerapiasAmbulatoriasView(_PrescriptionFormView):
    form_class = TerapiasAmbulatoriasForm
    layout = LAYOUT_TERAPIAS
    filename_prefix = "prescripcion_terapias"
    page_title = "Terapias ambulatorias"
    page_eyebrow = "Galeno · Rehabilitación"


class EscolaridadEspecialView(_PrescriptionFormView):
    form_class = EscolaridadEspecialForm
    layout = LAYOUT_ESCOLARIDAD
    filename_prefix = "prescripcion_escolaridad"
    page_title = "Escolaridad especial"
    page_eyebrow = "Galeno · Educativas"
    page_lede = (
        "Completá los datos y descargá la prescripción de escolaridad especial "
        "en PDF lista para firmar."
    )
