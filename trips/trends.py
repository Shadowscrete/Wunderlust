import json
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.cache import cache

# Only destination guides qualify; the feed also ranks itineraries and travel topics.
CITIES = {
    'Amsterdam', 'Athens', 'Bangkok', 'Barcelona', 'Beijing', 'Berlin', 'Brisbane',
    'Buenos Aires', 'Cairo', 'Chicago', 'Copenhagen', 'Delhi', 'Dubai', 'Dublin',
    'Edinburgh', 'Florence', 'Hanoi', 'Hong Kong', 'Istanbul', 'Jakarta', 'Kyoto',
    'Kuala Lumpur', 'Lisbon', 'London', 'Los Angeles', 'Madrid', 'Manila', 'Melbourne',
    'Mexico City', 'Montreal', 'Mumbai', 'Munich', 'New York City', 'Osaka', 'Paris',
    'Prague', 'Rio de Janeiro', 'Rome', 'San Francisco', 'Seoul', 'Shanghai',
    'Singapore', 'Stockholm', 'Sydney', 'Taipei', 'Tokyo', 'Toronto', 'Venice',
    'Vienna', 'Warsaw',
}


def destination_trends():
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    key = f'city-guide-trends:{yesterday}'
    cached = cache.get(key)
    if cached is not None:
        return cached

    for offset in range(3):
        day = yesterday - timedelta(days=offset)
        url = ('https://wikimedia.org/api/rest_v1/metrics/pageviews/top/'
               f'en.wikivoyage/all-access/{day:%Y/%m/%d}')
        request = Request(url, headers={'User-Agent': 'Wunderlust/1.0 (destination guide readership)'})
        try:
            with urlopen(request, timeout=3) as response:
                articles = json.load(response)['items'][0]['articles']
            cities = []
            for article in articles:
                name = article['article'].replace('_', ' ')
                if name in CITIES:
                    cities.append({'name': name, 'views': int(article['views']), 'slug': article['article']})
            result = {'day': day, 'cities': cities[:10]}
        except HTTPError as error:
            if error.code == 404:
                continue
            break
        except (OSError, URLError, ValueError, TypeError, IndexError, KeyError):
            break
        if cities:
            cache.set(key, result, 3600 if offset else 86400)
            cache.set('city-guide-trends:last', result, 7 * 86400)
            return result
    result = cache.get('city-guide-trends:last') or {}
    cache.set(key, result, 300)
    return result
