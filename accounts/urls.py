from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('register/', views.register, name='register'),

    path('login/', views.WunderlustLoginView.as_view(), name='login'),

    path('login-success/', views.login_success, name='login_success'),

    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
