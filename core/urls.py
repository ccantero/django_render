from django.urls import path

from . import views

urlpatterns = [
    path('',views.HomePage.as_view(),name='home'),
    path('me',views.AboutMePage.as_view(),name='aboutMe'),
    path('thanks/',views.ThanksPage.as_view(),name='thanks'),
    path('telegramapi/listener/',views.listener,name='listener'),
    path('telegramapi/test_speaker/<int:chat_id>/',views.test_speaker,name='test_speaker'),
]
