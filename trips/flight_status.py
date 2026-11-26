"""Live flight status from AviationStack (https://aviationstack.com/documentation).

The free plan allows ~100 requests a month, serves only plain HTTP and only returns
recent/live flights (no future schedules), so results are cached and lookups are only
made for flights departing within a day of today.
"""
import json
import logging
from datetime import date, timedelta
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

CACHE_SECONDS = 30 * 60
DEFAULT_MONTHLY_LIMIT = 90  # leave headroom under the free plan's 100 requests
TIMEOUT_SECONDS = 8
LIVE_WINDOW = timedelta(days=1)

STATUS_LABELS = {
    'scheduled': 'Scheduled',
    'active': 'Active ? phase unconfirmed',
    'departing': 'Departing',
    'boarding': 'Boarding',
    'taxiing': 'Taxiing',
    'airborne': 'In the air',
    'unknown': 'Status unavailable',
    'landed': 'Landed',
    'cancelled': 'Cancelled',
    'incident': 'Incident',
    'diverted': 'Diverted',
}


class FlightStatusError(Exception):
    """A lookup failed; the message is safe to show to travelers."""


def is_trackable(flight, today=None):
    today = today or date.today()
    return abs(flight.flight_date - today) <= LIVE_WINDOW


def _endpoint_side(side):
    side = side or {}
    return {
        'airport': side.get('airport') or '',
        'iata': side.get('iata') or '',
        'terminal': side.get('terminal') or '',
        'gate': side.get('gate') or '',
        'scheduled': side.get('scheduled') or '',
        'estimated': side.get('estimated') or '',
        'actual': side.get('actual') or '',
        'delay': side.get('delay'),
    }


def _summarise(record):
    status = (record.get('flight_status') or 'unknown').strip().lower()
    departure = record.get('departure') or {}
    arrival = record.get('arrival') or {}
    live = record.get('live') or {}
    if status in ('active', 'scheduled', 'unknown'):
        if arrival.get('actual') or arrival.get('actual_runway'):
            status = 'landed'
        elif live.get('is_ground') is False:
            status = 'airborne'
        elif live.get('is_ground') is True and 0 < (live.get('speed_horizontal') or 0) <= 40:
            status = 'taxiing'
        elif departure.get('actual_runway') and live.get('is_ground') is not True:
            status = 'airborne'
        elif departure.get('actual'):
            status = 'departing'
    return {
        'status': status,
        'checked_at': timezone.now().isoformat(),
        'status_label': STATUS_LABELS.get(status, status.title()),
        'departure': _endpoint_side(record.get('departure')),
        'arrival': _endpoint_side(record.get('arrival')),
        'airline': (record.get('airline') or {}).get('name') or '',
    }


def get_flight_status(flight):
    """Return a status dict for a trips.Flight, or None if no matching flight was found."""
    api_key = getattr(settings, 'FLIGHT_API_KEY', '')
    if not api_key:
        raise FlightStatusError('Live flight status is not configured.')

    cache_key = f'flight-status:v2:{flight.flight_number}:{flight.flight_date.isoformat()}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached or None  # {} caches "not found"

    month_key = f'flight-status-usage:{date.today():%Y-%m}'
    limit = int(getattr(settings, 'FLIGHT_API_MONTHLY_LIMIT', DEFAULT_MONTHLY_LIMIT))
    used = cache.get(month_key, 0)
    if used >= limit:
        raise FlightStatusError('Live status checks for this month have been used up.')
    cache.set(month_key, used + 1, 32 * 24 * 3600)

    base_url = getattr(settings, 'FLIGHT_API_BASE_URL', 'http://api.aviationstack.com/v1')
    query = urlencode({'access_key': api_key, 'flight_iata': flight.flight_number})
    try:
        with urlopen(f'{base_url}/flights?{query}', timeout=TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except (URLError, TimeoutError, ValueError) as exc:
        logger.warning('AviationStack request failed for %s: %s', flight, exc)
        raise FlightStatusError('Could not reach the flight status service. Try again shortly.')

    if 'error' in payload:
        error = payload['error'] or {}
        logger.warning('AviationStack error for %s: %s %s', flight, error.get('code'), error.get('message'))
        if error.get('code') in ('usage_limit_reached', 'rate_limit_reached'):
            raise FlightStatusError('The flight status limit has been reached for now.')
        raise FlightStatusError('The flight status service returned an error.')

    wanted = flight.flight_date.isoformat()
    match = next((r for r in payload.get('data') or [] if r.get('flight_date') == wanted), None)
    result = _summarise(match) if match else {}
    cache.set(cache_key, result, CACHE_SECONDS)
    return result or None
