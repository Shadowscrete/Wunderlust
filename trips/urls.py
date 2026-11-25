from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_home, name='dashboard_home'),
    path('traveler/', views.traveler_dashboard, name='traveler_dashboard'),
    path('admin/', views.admin_dashboard, name='admin_dashboard'),
    path('trips/', views.trip_list, name='trip_list'),
    path('preparation/', views.preparation_overview, name='preparation_overview'),
    path('travel-information/', views.travel_information_overview, name='travel_information_overview'),
    path('trips/new/', views.trip_create, name='trip_create'),
    path('trips/<int:trip_id>/', views.trip_detail, name='trip_detail'),
    path('trips/<int:trip_id>/edit/', views.trip_edit, name='trip_edit'),
    path('trips/<int:trip_id>/delete/', views.trip_delete, name='trip_delete'),
    path('trips/<int:trip_id>/flights/<int:flight_id>/status/', views.flight_status, name='flight_status'),
    path('trips/<int:trip_id>/members/<int:user_id>/remove/', views.trip_remove_member, name='trip_remove_member'),
    path('trips/<int:trip_id>/invite/', views.trip_invite, name='trip_invite'),
    path('checklist/<int:item_id>/toggle/', views.checklist_toggle, name='checklist_toggle'),
    path('checklist/<int:item_id>/quantity/', views.checklist_quantity_update, name='checklist_quantity_update'),
    path('join/<str:invite_code>/', views.trip_join, name='trip_join'),
    path('activities/', views.activity_list, name='activity_list'),
    path('notifications/live-count/', views.live_notification_count, name='live_notification_count'),
    path('notifications/<int:notification_id>/read/', views.notification_mark_read, name='notification_mark_read'),
]
