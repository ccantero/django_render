from django.shortcuts import render
from django.views.generic import TemplateView

class ThanksPage(TemplateView):
    template_name = 'thanks.html'

class HomePage(TemplateView):
    template_name = 'index.html'

# Create your views here.
def index(request):
    return render(request, 'render_app/index.html', {})