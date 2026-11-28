import json
from decimal import Decimal, DecimalException, ROUND_HALF_UP
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.core.cache import cache

RATE_STEP = Decimal('0.000000000001')
CENT = Decimal('0.01')
UNAVAILABLE = 'An automatic rate is unavailable for this currency pair right now. Please try again later.'


class ExchangeRateUnavailable(Exception):
    pass


def _fetch(path):
    try:
        with urlopen(f'{settings.FX_API_BASE_URL.rstrip("/")}/{path}', timeout=5) as response:
            return json.load(response, parse_float=Decimal)
    except (OSError, ValueError) as exc:
        raise ExchangeRateUnavailable(UNAVAILABLE) from exc


def supported_currencies():
    key = f'fx:{settings.FX_API_BASE_URL}:currencies'
    currencies = cache.get(key)
    if currencies is None:
        currencies = _fetch('currencies')
        if isinstance(currencies, list):
            currencies = {row['iso_code']: row['name'] for row in currencies
                          if isinstance(row, dict) and 'iso_code' in row and 'name' in row}
        if not isinstance(currencies, dict) or not currencies:
            raise ExchangeRateUnavailable(UNAVAILABLE)
        cache.set(key, currencies, 86400)
    return currencies


def exchange_rate(source, target):
    if source == target:
        return Decimal(1)
    key = f'fx:{settings.FX_API_BASE_URL}:{source}:{target}'
    rate = cache.get(key)
    if rate is None:
        try:
            if settings.FX_API_BASE_URL.rstrip('/').endswith('/v1'):
                query = urlencode({'base': source, 'symbols': target})
                value = _fetch(f'latest?{query}')['rates'][target]
            else:
                value = _fetch(f'rate/{source}/{target}')['rate']
            rate = Decimal(str(value)).quantize(RATE_STEP, rounding=ROUND_HALF_UP)
            if not 0 < rate < 10**12:
                raise ValueError('Rate is outside the supported range')
        except (KeyError, TypeError, ValueError, DecimalException) as exc:
            raise ExchangeRateUnavailable(UNAVAILABLE) from exc
        cache.set(key, rate, 3600)
    return rate
