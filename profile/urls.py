from django.urls import include, path
from rest_framework import routers
from profile import views

router = routers.DefaultRouter()
router.register('profiles', views.UserProfileViewSet)

app_name = 'profiles'

urlpatterns = [
    path('login/', views.UserLoginApiView.as_view()),
    path('', include(router.urls)),
]