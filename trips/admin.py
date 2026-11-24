from django.contrib import admin
from .models import Flight, Activity, Checklist, GroupMember, GroupTrip, ItineraryDay, Notification, TravelInfo, Trip, TripPlace


class ActivityInline(admin.TabularInline):
    model = Activity
    extra = 0


class ItineraryDayInline(admin.TabularInline):
    model = ItineraryDay
    extra = 0


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ('destination', 'country', 'airline', 'owner', 'start_date', 'end_date', 'status')
    list_filter = ('status', 'start_date')
    search_fields = ('destination', 'owner__username', 'owner__email')
    inlines = (ItineraryDayInline,)


@admin.register(ItineraryDay)
class ItineraryDayAdmin(admin.ModelAdmin):
    list_display = ('trip', 'date', 'title')
    inlines = (ActivityInline,)


admin.site.register((Flight, Activity, TravelInfo, Checklist, GroupTrip, GroupMember, Notification, TripPlace))
