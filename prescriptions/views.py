from datetime import timedelta

from django.http import HttpResponse
from django.shortcuts import render
from django.utils.http import content_disposition_header
from django.views import View

from profile.passkeys import _consume_rate_limit

from .forms import EscolaridadEspecialForm, TerapiasAmbulatoriasForm
from .pdf import LAYOUT_ESCOLARIDAD, LAYOUT_TERAPIAS, fill_prescription_pdf

GALENO_PDF_SCOPE = "galeno_pdf"
GALENO_PDF_LIMIT = 20
GALENO_PDF_WINDOW = timedelta(minutes=10)


def _galeno_identity(request):
    try:
        value = request.META.get("REMOTE_ADDR")
    except Exception:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _galeno_rate_limited(request):
    """Return a 429 response when this PDF POST must be denied."""
    identity = _galeno_identity(request)
    if identity is None:
        return HttpResponse(status=429)
    try:
        allowed = _consume_rate_limit(
            GALENO_PDF_SCOPE,
            identity,
            GALENO_PDF_LIMIT,
            window=GALENO_PDF_WINDOW,
        )
    except Exception:
        return HttpResponse(status=429)
    if not allowed:
        return HttpResponse(status=429)
    return None


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
        limited = _galeno_rate_limited(request)
        if limited is not None:
            return limited

        form = self.form_class(request.POST)
        if not form.is_valid():
            return render(
                request, self.template_name, self._context(form), status=400
            )

        pdf_bytes = fill_prescription_pdf(form.cleaned_data, layout=self.layout)
        filename = f"{self.filename_prefix}_{form.cleaned_data['dni']}.pdf"
        try:
            disposition = content_disposition_header(
                as_attachment=True, filename=filename
            )
        except Exception:
            return HttpResponse(status=400)
        if not disposition or "\r" in disposition or "\n" in disposition:
            return HttpResponse(status=400)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = disposition
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
