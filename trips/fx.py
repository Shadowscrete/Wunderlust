import json
from decimal import Decimal, DecimalException, ROUND_HALF_UP
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings
from django.core.cache import cache

RATE_STEP = Decimal('0.000000000001')
CENT = Decimal('0.01')
UNAVAILABLE = 'Exchange rates are unavailable right now; enter the rate manually'


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
        query = urlencode({'base': source, 'symbols': target})
        try:
            rate = Decimal(str(_fetch(f'latest?{query}')['rates'][target])).quantize(RATE_STEP, rounding=ROUND_HALF_UP)
            if not 0 < rate < 10**12:
                raise ValueError('Rate is outside the supported range')
        except (KeyError, TypeError, ValueError, DecimalException) as exc:
            raise ExchangeRateUnavailable(UNAVAILABLE) from exc
        cache.set(key, rate, 43200)
    return rate
