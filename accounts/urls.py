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

    path('timezone/', views.update_timezone, name='update_timezone'),

    path('support/', views.support, name='support'),

    path('friends/', views.friends, name='friends'),
    path('users/search/', views.user_search, name='user_search'),
    path('u/<str:username>/', views.public_profile, name='public_profile'),
    path('u/<str:username>/follow/', views.follow_toggle, name='follow_toggle'),
    path('u/<str:username>/report/', views.report_user, name='report_user'),

    path('password-reset/', views.WunderlustPasswordResetView.as_view(), name='password_reset'),
    path('password-reset/sent/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),

    path('logout/', views.WunderlustLogoutView.as_view(), name='logout'),
]
