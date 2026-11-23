from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('register/', views.register, name='register'),

    path('login/', views.WunderlustLoginView.as_view(), name='login'),

    path('login-success/', views.login_success, name='login_success'),

    path('profile/', views.profile, name='profile'),

    path('profile/avatar/', views.update_avatar, name='update_avatar'),

    path('settings/', views.account_settings, name='account_settings'),

    path('support/', views.support, name='support'),

    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]
