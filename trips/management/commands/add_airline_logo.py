import json
import re
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.etree import ElementTree

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from PIL import Image

from trips.airline_marks import LOGO_DIRECTORY, logo_manifest, read_manifest
from trips.forms import parse_flight_number


def validate_svg(data):
    try:
        source = data.decode('utf-8-sig')
        if re.search(r'<\s*!(?:doctype|entity)|<\?(?!xml\s)', source, re.I):
            raise ValueError
        root = ElementTree.fromstring(source)
        if root.tag not in ('svg', '{http://www.w3.org/2000/svg}svg'):
            raise ValueError
        for element in root.iter():
            tag = element.tag.rsplit('}', 1)[-1].lower()
            if tag in ('script', 'foreignobject'):
                raise ValueError
            for name, value in element.attrib.items():
                attribute = name.rsplit('}', 1)[-1].lower()
                if attribute.startswith('on') or (attribute == 'href' and not value.strip().startswith('#')):
                    raise ValueError
            style = ' '.join([*element.attrib.values(), element.text or ''])
            if tag == 'style' or 'style' in element.attrib or 'url' in style.lower():
                # Reject CSS obfuscation before checking that resource URLs are fragment-only.
                if re.search(r'@import|\\|/\*', style, re.I):
                    raise ValueError
                for match in re.finditer(r'url\s*\(\s*([^)]*)', style, re.I):
                    if not match[1].strip().strip(chr(34) + chr(39)).startswith('#'):
                        raise ValueError
    except (ValueError, ElementTree.ParseError) as exc:
        raise CommandError('Use a valid UTF-8 SVG without scripts, event handlers or external references.') from exc


def validate_png(data):
    try:
        with Image.open(BytesIO(data), formats=['PNG']) as image:
            if min(image.size) < 128:
                raise ValueError
            image.verify()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise CommandError('Use a valid PNG at least 128 by 128 pixels.') from exc


def replace_file(path, data):
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        staging = Path(temporary.name)
        temporary.write(data)
    try:
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)


class Command(BaseCommand):
    help = 'Register or remove a locally licensed airline logo.'

    def add_arguments(self, parser):
        parser.add_argument('code', nargs='?')
        parser.add_argument('path', nargs='?', type=Path)
        parser.add_argument('--source-url')
        parser.add_argument('--license')
        parser.add_argument('--remove', metavar='CODE')

    def handle(self, *args, **options):
        removal = options['remove']
        code = (removal or options['code'] or '').strip().upper()
        try:
            if len(code) != 2:
                raise ValidationError('Invalid code length.')
            parse_flight_number(f'{code}1')
        except ValidationError as exc:
            raise CommandError('Enter a two-character airline code containing at least one letter.') from exc
        path = options['path']
        source = (options['source_url'] or '').strip()
        license_text = (options['license'] or '').strip()
        directory = settings.BASE_DIR / LOGO_DIRECTORY
        try:
            logos = read_manifest(directory)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise CommandError('Repair the logo manifest before changing it.') from exc
        previous = logos.get(code)
        if removal:
            if options['code'] or path or source or license_text:
                raise CommandError('Use --remove CODE by itself.')
            if not previous:
                raise CommandError(f'No logo is registered for {code}.')
            del logos[code]
        else:
            if not path or not source or not license_text:
                raise CommandError('Provide a file, --source-url and --license.')
            extension = path.suffix.lower()
            if extension not in ('.svg', '.png'):
                raise CommandError('Only SVG and PNG files are supported.')
            limit = 100 if extension == '.svg' else 200
            try:
                with path.open('rb') as image:
                    data = image.read(limit * 1024 + 1)
            except OSError as exc:
                raise CommandError(f'Could not read logo: {exc}') from exc
            if len(data) > limit * 1024:
                raise CommandError(f'Logo must be at most {limit} KB.')
            (validate_svg if extension == '.svg' else validate_png)(data)
            filename = f'{code}{extension}'
            replace_file(directory / filename, data)
            logos[code] = {'file': filename, 'source_url': source, 'license': license_text,
                          'added': timezone.localdate().isoformat()}
        replace_file(directory / 'SOURCES.json', (json.dumps({'logos': logos}, indent=2, sort_keys=True) + '\n').encode())
        if previous and (removal or previous['file'] != logos[code]['file']):
            (directory / previous['file']).unlink(missing_ok=True)
        logo_manifest.cache_clear()
        self.stdout.write(self.style.SUCCESS(f'{"Removed" if removal else "Registered"} logo for {code}.'))
