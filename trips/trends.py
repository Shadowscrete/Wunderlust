import json
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from django.core.cache import cache
from django.templatetags.static import static
from django.utils.html import strip_tags

# Destination guides qualify for the ranking alongside their trip form country.
CITIES = {
    'Amsterdam': 'Netherlands',
    'Athens': 'Greece',
    'Bangkok': 'Thailand',
    'Barcelona': 'Spain',
    'Beijing': 'China',
    'Berlin': 'Germany',
    'Brisbane': 'Australia',
    'Buenos Aires': 'Argentina',
    'Cairo': 'Egypt',
    'Chicago': 'United States',
    'Copenhagen': 'Denmark',
    'Delhi': 'India',
    'Dubai': 'United Arab Emirates',
    'Dublin': 'Ireland',
    'Edinburgh': 'United Kingdom',
    'Florence': 'Italy',
    'Hanoi': 'Vietnam',
    'Hong Kong': 'Hong Kong',
    'Istanbul': 'Turkey',
    'Jakarta': 'Indonesia',
    'Kyoto': 'Japan',
    'Kuala Lumpur': 'Malaysia',
    'Lisbon': 'Portugal',
    'London': 'United Kingdom',
    'Los Angeles': 'United States',
    'Madrid': 'Spain',
    'Manila': 'Philippines',
    'Melbourne': 'Australia',
    'Mexico City': 'Mexico',
    'Montreal': 'Canada',
    'Mumbai': 'India',
    'Munich': 'Germany',
    'New York City': 'United States',
    'Osaka': 'Japan',
    'Paris': 'France',
    'Prague': 'Czechia',
    'Rio de Janeiro': 'Brazil',
    'Rome': 'Italy',
    'San Francisco': 'United States',
    'Seoul': 'South Korea',
    'Shanghai': 'China',
    'Singapore': 'Singapore',
    'Stockholm': 'Sweden',
    'Sydney': 'Australia',
    'Taipei': 'Taiwan',
    'Tokyo': 'Japan',
    'Toronto': 'Canada',
    'Venice': 'Italy',
    'Vienna': 'Austria',
    'Warsaw': 'Poland',
}

LOCAL_PHOTOS = {
    'Lisbon': ('trends-lisbon.webp', 'Aayush Gupta', 'ljhCEaHYWJ8'),
    'London': ('trends-london.webp', 'Benjamin Davies', 'Oja2ty_9ZLM'),
    'Paris': ('trends-paris.webp', 'Pavel Abramiankou', 'yzh7B-9sOhc'),
}

VERIFIED_PHOTOS = {
    'Beijing': {
        'url': 'https://thumb.wikimedia.org/wikipedia/commons/thumb/6/67/'
               'Hall_of_Supreme_Harmony.JPG/960px-Hall_of_Supreme_Harmony.JPG',
        'alt': 'Hall of Supreme Harmony in Beijing’s Forbidden City',
        'artist': 'Gisling',
        'source': 'https://commons.wikimedia.org/wiki/File:Hall_of_Supreme_Harmony.JPG',
        'license': 'CC BY 3.0',
        'license_url': 'https://creativecommons.org/licenses/by/3.0/',
    },
}


def _json_from(url):
    request = Request(url, headers={'User-Agent': 'Wunderlust/1.0 (destination guide readership)'})
    with urlopen(request, timeout=3) as response:
        return json.load(response)


def _daily_cities(day):
    key = f'city-guide-trends:daily:{day}'
    cached = cache.get(key)
    if cached is not None:
        return cached
    url = ('https://wikimedia.org/api/rest_v1/metrics/pageviews/top/'
           f'en.wikivoyage/all-access/{day:%Y/%m/%d}')
    articles = _json_from(url)['items'][0]['articles']
    cities = [
        {'name': article['article'].replace('_', ' '), 'views': int(article['views']), 'slug': article['article']}
        for article in articles if article['article'].replace('_', ' ') in CITIES
    ]
    cities.sort(key=lambda city: city['views'], reverse=True)
    cache.set(key, cities, 7 * 86400 if cities else 300)
    return cities


def _wiki_pages(titles, project, **parameters):
    query = urlencode({'action': 'query', 'format': 'json', 'formatversion': 2,
                       'titles': '|'.join(titles), **parameters})
    return _json_from(f'https://en.{project}.org/w/api.php?{query}')['query']['pages']


def _city_photos(names):
    keys = {name: f"city-guide-photo:{name.replace(' ', '_')}" for name in names}
    photos = {name: cache.get(key) for name, key in keys.items()}
    missing = [name for name, photo in photos.items() if photo is None]
    if missing:
        for project in ('wikivoyage', 'wikipedia'):
            remaining = [name for name in missing if not photos[name]]
            if not remaining:
                break
            try:
                pages = _wiki_pages(remaining, project, prop='pageimages', piprop='thumbnail|name',
                                    pilicense='free', pithumbsize=640)
                thumbnails = {
                    f"File:{page['pageimage']}".replace('_', ' '): (page['title'], page['thumbnail']['source'])
                    for page in pages if page.get('thumbnail') and page.get('pageimage')
                    and page['pageimage'].lower().endswith(('.jpeg', '.jpg', '.webp', '.png'))
                }
                files = _wiki_pages(thumbnails, project, prop='imageinfo', iiprop='url|extmetadata',
                                    iiextmetadatafilter='Artist|LicenseShortName') if thumbnails else []
                for file in files:
                    match = thumbnails.get(file['title'])
                    info = (file.get('imageinfo') or [{}])[0]
                    metadata = info.get('extmetadata', {})
                    artist = unescape(strip_tags(metadata.get('Artist', {}).get('value', ''))).strip()
                    license_name = metadata.get('LicenseShortName', {}).get('value', '')
                    source = info.get('descriptionurl', '')
                    if not (match and license_name and urlsplit(source).hostname == 'commons.wikimedia.org'):
                        continue
                    if not artist and license_name != 'Public domain':
                        continue
                    name, thumbnail = match
                    if urlsplit(thumbnail).hostname in ('upload.wikimedia.org', 'thumb.wikimedia.org'):
                        photos[name] = {'url': thumbnail, 'artist': artist, 'license': license_name, 'source': source}
            except (OSError, ValueError, TypeError, KeyError, IndexError):
                pass
        for name in missing:
            cache.set(keys[name], photos[name] or {}, 7 * 86400 if photos[name] else 3600)
    return photos


def _decorate(result):
    cities = result.get('cities', [])
    photos = _city_photos([
        city['name'] for city in cities
        if city['name'] not in LOCAL_PHOTOS and city['name'] not in VERIFIED_PHOTOS
    ])
    for city in cities:
        name = city['name']
        city['country'] = CITIES[name]
        if name in LOCAL_PHOTOS:
            filename, artist, identifier = LOCAL_PHOTOS[name]
            city['photo'] = {'url': static(f'home/assets/{filename}'), 'artist': artist,
                             'source': f'https://unsplash.com/photos/{identifier}'}
        elif name in VERIFIED_PHOTOS:
            city['photo'] = VERIFIED_PHOTOS[name]
        else:
            city['photo'] = photos.get(name)
    return result


def destination_trends():
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    key = f'city-guide-trends:cards:{yesterday}'
    cached = cache.get(key)
    if cached is not None:
        return _decorate(cached)

    for offset in range(3):
        day = yesterday - timedelta(days=offset)
        try:
            cities = _daily_cities(day)[:10]
        except HTTPError as error:
            if error.code == 404:
                continue
            break
        except (OSError, ValueError, TypeError, KeyError, IndexError):
            break
        if not cities:
            continue
        try:
            previous = {city['name']: index for index, city in enumerate(_daily_cities(day - timedelta(days=1)), 1)}
        except (OSError, ValueError, TypeError, KeyError, IndexError):
            previous = {}
        for index, city in enumerate(cities, 1):
            if city['name'] in previous:
                city['movement'] = previous[city['name']] - index
        result = {'day': day, 'cities': cities}
        cache.set(key, result, 3600 if offset or not previous else 86400)
        cache.set('city-guide-trends:last', result, 7 * 86400)
        return _decorate(result)

    result = cache.get('city-guide-trends:last') or {}
    cache.set(key, result, 300)
    return _decorate(result)
