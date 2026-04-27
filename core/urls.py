from django.urls import path
from django.contrib.auth import views as auth_views

from . import views

urlpatterns = [
    path('',views.HomePage.as_view(),name='home'),
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('bot/status/', views.bot_status, name='bot_status'),
    path('bot/stop/', views.bot_stop, name='bot_stop'),
    path('bot/resume/', views.bot_resume, name='bot_resume'),
    path('me',views.AboutMePage.as_view(),name='aboutMe'),
    path('thanks/',views.ThanksPage.as_view(),name='thanks'),
    path('telegramapi/listener/',views.listener,name='listener'),
    path('telegramapi/test_speaker/<int:chat_id>/',views.test_speaker,name='test_speaker'),
]
