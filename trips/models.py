from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.crypto import get_random_string


def create_trip_code():
    return get_random_string(10, allowed_chars='ABCDEFGHJKLMNPQRSTUVWXYZ23456789')


class Trip(models.Model):
    class Status(models.TextChoices):
        PLANNING = 'PLANNING', 'Planning'
        READY = 'READY', 'Ready'
        IN_PROGRESS = 'IN_PROGRESS', 'In progress'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='owned_trips')
    destination = models.CharField(max_length=160)
    country = models.CharField(max_length=100, blank=True)
    airline = models.CharField(max_length=120, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('start_date', 'destination')
        constraints = [models.CheckConstraint(condition=Q(end_date__gte=F('start_date')), name='trip_end_on_or_after_start')]

    def __str__(self):
        return f'{self.destination} ({self.start_date:%b %d, %Y})'

    @property
    def is_group_trip(self):
        return hasattr(self, 'group_trip')


class ItineraryDay(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='itinerary_days')
    date = models.DateField()
    title = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ('date', 'pk')
        unique_together = ('trip', 'date')

    def __str__(self):
        return f'{self.trip.destination} · {self.date:%b %d}'


class TripPlace(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='places')
    name = models.CharField(max_length=180)
    visit_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ('visit_order', 'name')

    def __str__(self):
        return self.name


class Activity(models.Model):
    day = models.ForeignKey(ItineraryDay, on_delete=models.CASCADE, related_name='activities')
    title = models.CharField(max_length=180)
    start_time = models.TimeField(null=True, blank=True)
    location = models.CharField(max_length=180, blank=True)
    notes = models.TextField(blank=True)
    is_recommended = models.BooleanField(default=False)

    class Meta:
        ordering = ('start_time', 'pk')

    def __str__(self):
        return self.title


class TravelInfo(models.Model):
    class Category(models.TextChoices):
        FLIGHT = 'FLIGHT', 'Flight'
        TRANSIT = 'TRANSIT', 'Transit'
        GUIDE = 'GUIDE', 'Guide'
        OTHER = 'OTHER', 'Other'

    trip = models.ForeignKey(Trip, null=True, blank=True, on_delete=models.CASCADE, related_name='travel_info')
    destination = models.CharField(max_length=160, blank=True, help_text='Optional destination-wide reference entry.')
    category = models.CharField(max_length=12, choices=Category.choices, default=Category.OTHER)
    title = models.CharField(max_length=160)
    details = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('destination', 'category', 'title')
        verbose_name_plural = 'travel information'

    def __str__(self):
        return self.title


class Checklist(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='checklist_items')
    title = models.CharField(max_length=180)
    is_document = models.BooleanField(default=False, help_text='Documents include passports, visas and IDs.')
    is_complete = models.BooleanField(default=False)
    is_mandatory = models.BooleanField(default=False)
    is_custom = models.BooleanField(default=False)
    quantity = models.PositiveIntegerField(default=1)
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('is_complete', 'is_document', 'due_date', 'title')

    def __str__(self):
        return self.title


class GroupTrip(models.Model):
    trip = models.OneToOneField(Trip, on_delete=models.CASCADE, related_name='group_trip')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='created_group_trips')
    invite_code = models.CharField(max_length=10, unique=True, default=create_trip_code, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Group · {self.trip.destination}'


class GroupMember(models.Model):
    class Membership(models.TextChoices):
        ORGANIZER = 'ORGANIZER', 'Organizer'
        MEMBER = 'MEMBER', 'Member'

    group_trip = models.ForeignKey(GroupTrip, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='trip_memberships')
    membership = models.CharField(max_length=12, choices=Membership.choices, default=Membership.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('group_trip', 'user')
        ordering = ('joined_at',)

    def __str__(self):
        return f'{self.user} · {self.group_trip.trip.destination}'


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='travel_notifications', help_text='Leave empty for a system-wide notice.')
    trip = models.ForeignKey(Trip, null=True, blank=True, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=180)
    message = models.TextField(blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return self.title
