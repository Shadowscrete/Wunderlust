import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .airline_marks import LOGO_DIRECTORY, airline_mark, logo_manifest, read_manifest
from .models import Trip


class AirlineMarkTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.enterContext(self.settings(BASE_DIR=root))
        self.directory = root / LOGO_DIRECTORY
        self.directory.mkdir(parents=True)
        self.manifest = self.directory / 'SOURCES.json'
        self.manifest.write_text('{"logos": {}}', encoding='utf-8')
        logo_manifest.cache_clear()
        self.addCleanup(logo_manifest.cache_clear)

    def test_badge_colour_is_stable_and_in_range(self):
        mark = airline_mark('pr')
        logo_manifest.cache_clear()
        self.assertEqual(mark, airline_mark('PR'))
        self.assertIn(mark['colour'], range(1, 9))

    def test_missing_and_invalid_manifest_fall_back_once(self):
        for content in (None, '{"logos": []}', '{"logos": {"PR":{"file":"../../PR.svg"}}}'):
            with self.subTest(content=content):
                self.manifest.unlink(missing_ok=True)
                if content:
                    self.manifest.write_text(content, encoding='utf-8')
                logo_manifest.cache_clear()
                with self.assertLogs('trips.airline_marks', 'WARNING') as logs:
                    self.assertEqual(airline_mark('PR')['logo_url'], '')
                    self.assertEqual(airline_mark('5J')['logo_url'], '')
                self.assertEqual(len(logs.output), 1)

    def test_trip_renders_empty_plane_then_badges_then_local_images(self):
        user = get_user_model().objects.create_user('flyer')
        date = timezone.localdate()
        trip = Trip.objects.create(owner=user, destination='Manila', start_date=date, end_date=date)
        self.client.force_login(user)
        url = reverse('trip_detail', args=[trip.pk])
        self.assertContains(self.client.get(url), 'class="flight-icon"', count=1)
        trip.flights.create(carrier_code='PR', number='102', flight_date=date)
        page = self.client.get(url)
        self.assertNotContains(page, 'class="flight-icon"')
        self.assertContains(page, 'aria-hidden="true">PR</span>', count=2)
        self.register('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h1v1z"/></svg>')
        self.assertContains(self.client.get(url), 'airlines/logos/PR.svg', count=2)

    def register(self, content, code='pr', extension='.svg'):
        image = self.directory.parent / f'input{extension}'
        image.write_text(content, encoding='utf-8')
        call_command('add_airline_logo', code, image, source_url='https://example.com/logo',
                     license='PD-textlogo', stdout=StringIO())

    def test_command_rejects_unsafe_or_unsupported_files(self):
        cases = [
            ('<svg><script/></svg>', 'PR', '.svg'),
            ('<svg><image href="other.svg"/></svg>', 'PR', '.svg'),
            ('<svg><path onclick="run()"/></svg>', 'PR', '.svg'),
            ('<svg><path fill="url(https://example.com/a)"/></svg>', 'PR', '.svg'),
            ('<svg/>', 'PR', '.jpg'),
            ('<svg/>', '12', '.svg'),
        ]
        for data, code, extension in cases:
            with self.subTest(data=data, code=code, extension=extension), self.assertRaises(CommandError):
                self.register(data, code, extension)
        self.assertEqual(read_manifest(self.directory), {})

    def test_command_adds_provenance_and_removes_the_file(self):
        self.register('<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.assertEqual(json.loads(self.manifest.read_text(encoding='utf-8')), {'logos': {'PR': {
            'file': 'PR.svg', 'source_url': 'https://example.com/logo',
            'license': 'PD-textlogo', 'added': timezone.localdate().isoformat(),
        }}})
        self.assertTrue((self.directory / 'PR.svg').is_file())
        call_command('add_airline_logo', remove='pr', stdout=StringIO())
        self.assertEqual(read_manifest(self.directory), {})
        self.assertFalse((self.directory / 'PR.svg').exists())


class AirlineLogoInventoryTests(TestCase):
    def test_every_logo_has_provenance_and_every_entry_has_a_file(self):
        directory = settings.BASE_DIR / LOGO_DIRECTORY
        files = {path.name for path in directory.iterdir() if path.is_file() and path.suffix.lower() in ('.svg', '.png')}
        self.assertEqual(files, {entry['file'] for entry in read_manifest(directory).values()})
