from django.core.management.base import BaseCommand

from trips.models import sync_trip_statuses


class Command(BaseCommand):
    help = 'Update trip statuses by date.'

    def handle(self, *args, **options):
        sync_trip_statuses()
        self.stdout.write(self.style.SUCCESS('Trip statuses updated.'))
