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

    def status_for_dates(self, today=None):
        """The status this trip should have from its dates (Cancelled stays Cancelled)."""
        from django.utils import timezone
        today = today or timezone.localdate()
        if self.status == self.Status.CANCELLED:
            return self.status
        if self.end_date < today:
            return self.Status.COMPLETED
        if self.start_date <= today:
            return self.Status.IN_PROGRESS
        # Back in the future (e.g. dates moved later): keep Ready if set, otherwise Planning.
        return self.status if self.status == self.Status.READY else self.Status.PLANNING

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


class Flight(models.Model):
    """A flight on a trip, stored in standard IATA form (carrier code + number + date)
    so it can later be passed straight to a live flight-status service."""
    class Leg(models.TextChoices):
        OUTBOUND = 'OUTBOUND', 'Outbound'
        RETURN = 'RETURN', 'Return'
        CONNECTION = 'CONNECTION', 'Connection'
        OTHER = 'OTHER', 'Other'

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='flights')
    carrier_code = models.CharField(max_length=2, help_text='IATA airline code, e.g. PR')
    number = models.CharField(max_length=5, help_text='Flight number digits plus optional suffix, e.g. 102 or 102A')
    flight_date = models.DateField(help_text='Scheduled departure date (local time at the departure airport)')
    leg = models.CharField(max_length=12, choices=Leg.choices, default=Leg.OUTBOUND)
    airline_name = models.CharField(max_length=120, blank=True)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('flight_date', 'carrier_code', 'number')
        constraints = [
            models.UniqueConstraint(fields=('trip', 'carrier_code', 'number', 'flight_date'), name='unique_flight_per_trip_and_date'),
        ]

    @property
    def flight_number(self):
        return f'{self.carrier_code}{self.number}'

    def __str__(self):
        return f'{self.flight_number} on {self.flight_date:%Y-%m-%d}'


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


class ChecklistCheck(models.Model):
    """One traveler's tick on a checklist item. Everyone on a trip shares the item list,
    but each member ticks their own copy, so each person has their own progress."""
    item = models.ForeignKey(Checklist, on_delete=models.CASCADE, related_name='checks')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='checklist_checks')
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('item', 'user'), name='unique_check_per_item_and_user')]

    def __str__(self):
        return f'{self.user} ✓ {self.item}'


def trip_travelers(trip):
    """Everyone on a trip: the owner first, then group members in the order they joined."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    rows = [(trip.owner, 'Organizer')]
    seen = {trip.owner_id}
    group = getattr(trip, 'group_trip', None) if trip.is_group_trip else None
    if group:
        for member in group.members.select_related('user', 'user__profile').order_by('joined_at'):
            if member.user_id not in seen:
                seen.add(member.user_id)
                rows.append((member.user, member.get_membership_display()))
    return rows


def trip_readiness(trip):
    """Each traveler's checklist progress for a trip, from two queries."""
    from django.db.models import Count
    total = trip.checklist_items.count()
    done = dict(ChecklistCheck.objects.filter(item__trip=trip).values_list('user').annotate(n=Count('pk')))
    out = []
    for user, role in trip_travelers(trip):
        n = done.get(user.pk, 0)
        out.append({'user': user, 'role': role, 'done': n, 'total': total,
                    'percent': round(n * 100 / total) if total else 0,
                    'is_ready': bool(total) and n >= total})
    return out


def refresh_ready_status(trip):
    rows = trip_readiness(trip)
    if trip.status in (Trip.Status.PLANNING, Trip.Status.READY):
        status = Trip.Status.READY if rows and all(row['is_ready'] for row in rows) else Trip.Status.PLANNING
        if status != trip.status and Trip.objects.filter(pk=trip.pk, status=trip.status).update(status=status):
            trip.status = status
    return rows


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


class RemovedMember(models.Model):
    """A traveler the organizer removed from a group trip. They can't rejoin with the invite link."""
    group_trip = models.ForeignKey(GroupTrip, on_delete=models.CASCADE, related_name='removed_members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    removed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('group_trip', 'user'), name='unique_removed_member')]

    def __str__(self):
        return f'{self.user} removed from {self.group_trip}'


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



class NotificationRead(models.Model):
    """Marks a system-wide notice (user=None) as read for one traveler.
    One shared notice row plus a small read marker per reader, instead of copying the notice to every account."""
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name='reads')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('notification', 'user'), name='unique_notification_read')]


def sync_trip_statuses():
    """Moves trips along by date: started trips become In progress, finished trips become Completed.
    Cancelled and already-completed trips are left alone. Two UPDATE queries in total."""
    from django.utils import timezone
    today = timezone.localdate()
    active = Trip.objects.exclude(status__in=(Trip.Status.CANCELLED, Trip.Status.COMPLETED))
    active.filter(end_date__lt=today).update(status=Trip.Status.COMPLETED)
    active.filter(start_date__lte=today, end_date__gte=today).exclude(status=Trip.Status.IN_PROGRESS).update(status=Trip.Status.IN_PROGRESS)
