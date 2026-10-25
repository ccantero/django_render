from django.urls import path
from django.contrib.auth import views as auth_views

from . import views
from profile import passkeys

urlpatterns = [
    path('',views.HomePage.as_view(),name='home'),
    path('health/', views.health, name='health'),
    path('version/', views.version, name='version'),
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('security/passkeys/', passkeys.manage, name='passkey_manage'),
    path('passkeys/reauthenticate/', passkeys.reauthenticate, name='passkey_reauthenticate'),
    path('passkeys/registration/begin/', passkeys.RegistrationBeginView.as_view(), name='passkey_registration_begin'),
    path('passkeys/registration/complete/', passkeys.RegistrationCompleteView.as_view(), name='passkey_registration_complete'),
    path('passkeys/enrollment/step-up/begin/', passkeys.EnrollmentStepUpBeginView.as_view(), name='passkey_enrollment_step_up_begin'),
    path('passkeys/enrollment/step-up/complete/', passkeys.EnrollmentStepUpCompleteView.as_view(), name='passkey_enrollment_step_up_complete'),
    path('passkeys/authentication/begin/', passkeys.AuthenticationBeginView.as_view(), name='passkey_authentication_begin'),
    path('passkeys/authentication/complete/', passkeys.AuthenticationCompleteView.as_view(), name='passkey_authentication_complete'),
    path('passkeys/<int:credential_id>/revoke/', passkeys.revoke, name='passkey_revoke'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('bot/status/', views.bot_status, name='bot_status'),
    path('bot/stop/', views.bot_stop, name='bot_stop'),
    path('bot/resume/', views.bot_resume, name='bot_resume'),
    path('me',views.AboutMePage.as_view(),name='aboutMe'),
    path('thanks/',views.ThanksPage.as_view(),name='thanks'),
    path('telegramapi/listener/',views.listener,name='listener'),
    path('telegramapi/test_speaker/<int:chat_id>/',views.test_speaker,name='test_speaker'),
]
