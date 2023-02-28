from django.urls import include, path
from rest_framework import routers
from profile import views

router = routers.DefaultRouter()
router.register('profile', views.UserProfileViewSet)

app_name = 'profile'

urlpatterns = [
    path('login/', views.UserLoginApiView.as_view()),
    path('', include(router.urls)),
]