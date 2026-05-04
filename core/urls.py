from django.urls import path
from django.contrib.auth import views as auth_views

from . import views

urlpatterns = [
    path('',views.HomePage.as_view(),name='home'),
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/demo/', views.dashboard_demo, name='dashboard_demo'),
    path('dashboard/dust/', views.dust_dashboard, name='dust_dashboard'),
    path('dashboard/dust/detail/', views.dust_detail, name='dust_detail'),
    path('dashboard/dust/corrections/new/', views.manual_correction_new, name='manual_correction_new'),
    path('dashboard/dust/corrections/<str:status>/', views.manual_corrections, name='manual_corrections'),
    path('dashboard/dust/corrections/detail/<int:correction_id>/', views.manual_correction_detail, name='manual_correction_detail'),
    path('bot/status/', views.bot_status, name='bot_status'),
    path('bot/stop/', views.bot_stop, name='bot_stop'),
    path('bot/resume/', views.bot_resume, name='bot_resume'),
    path('me',views.AboutMePage.as_view(),name='aboutMe'),
    path('thanks/',views.ThanksPage.as_view(),name='thanks'),
    path('telegramapi/listener/',views.listener,name='listener'),
    path('telegramapi/test_speaker/<int:chat_id>/',views.test_speaker,name='test_speaker'),
]
