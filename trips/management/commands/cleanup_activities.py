from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from trips.models import Activity, sync_trip_statuses


class Command(BaseCommand):
    help = 'Delete itinerary activities older than 30 days and update trip statuses by date.'

    def handle(self, *args, **options):
        cutoff = timezone.localdate() - timedelta(days=30)
        deleted, _ = Activity.objects.filter(day__date__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted} expired activity record(s).'))
        sync_trip_statuses()
        self.stdout.write(self.style.SUCCESS('Trip statuses updated.'))
