from django.urls import path

from . import views

urlpatterns = [
    #path('',views.HomePage.as_view(),name='home'),
    path('',views.ThanksPage.as_view(),name='thanks'),
    path('thanks/',views.ThanksPage.as_view(),name='thanks'),
]
