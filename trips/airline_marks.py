import hashlib
import json
import logging
import re
from functools import lru_cache

from django.conf import settings
from django.templatetags.static import static

from .airlines import AIRLINE_BY_CODE

logger = logging.getLogger(__name__)
LOGO_DIRECTORY = 'static/airlines/logos'
CODE_PATTERN = re.compile(r'(?![0-9]{2})[A-Z0-9]{2}')


def read_manifest(directory):
    logos = json.loads((directory / 'SOURCES.json').read_text(encoding='utf-8'))['logos']
    if not isinstance(logos, dict):
        raise ValueError('logos must be an object')
    for code, entry in logos.items():
        if not CODE_PATTERN.fullmatch(code) or not isinstance(entry, dict):
            raise ValueError('Invalid airline logo entry')
        if entry.get('file') not in (f'{code}.svg', f'{code}.png'):
            raise ValueError('Invalid airline logo filename')
        if any(not isinstance(entry.get(key), str) or not entry[key].strip() for key in ('source_url', 'license', 'added')):
            raise ValueError('Incomplete airline logo provenance')
    return logos


@lru_cache(maxsize=1)
def logo_manifest():
    directory = settings.BASE_DIR / LOGO_DIRECTORY
    try:
        return read_manifest(directory)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning('Airline logo manifest unavailable: %s', exc)
        return {}


def airline_mark(code, name=''):
    code = code.strip().upper()
    directory = settings.BASE_DIR / LOGO_DIRECTORY
    entry = logo_manifest().get(code)
    logo_url = static(f"airlines/logos/{entry['file']}") if entry and (directory / entry['file']).is_file() else ''
    return {
        'code': code,
        'logo_url': logo_url,
        'colour': int(hashlib.sha1(code.encode()).hexdigest(), 16) % 8 + 1,
        'label': name or AIRLINE_BY_CODE.get(code) or f'Airline {code}',
    }
