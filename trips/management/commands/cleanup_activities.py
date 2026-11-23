from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from trips.models import Activity


class Command(BaseCommand):
    help = 'Delete itinerary activities that took place more than 30 days ago.'

    def handle(self, *args, **options):
        cutoff = timezone.localdate() - timedelta(days=30)
        deleted, _ = Activity.objects.filter(day__date__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {deleted} expired activity record(s).'))
