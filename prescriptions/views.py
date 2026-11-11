from django.http import HttpResponse
from django.shortcuts import render
from django.views import View

from .forms import TerapiasAmbulatoriasForm
from .pdf import fill_prescription_pdf


class TerapiasAmbulatoriasView(View):
    template_name = "prescriptions/form.html"
    form_class = TerapiasAmbulatoriasForm

    def get(self, request):
        return render(request, self.template_name, {"form": self.form_class()})

    def post(self, request):
        form = self.form_class(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form}, status=400)

        pdf_bytes = fill_prescription_pdf(form.cleaned_data)
        dni = form.cleaned_data["dni"]
        filename = f"prescripcion_terapias_{dni}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
