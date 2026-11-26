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
    'Amsterdam': ('Netherlands', 'Canals, canal houses and museum afternoons.'),
    'Athens': ('Greece', 'Ancient hilltop ruins and lively neighborhood squares.'),
    'Bangkok': ('Thailand', 'Temple courtyards and evenings at the street-food stalls.'),
    'Barcelona': ('Spain', 'Gaudi architecture and walks along the Mediterranean.'),
    'Beijing': ('China', 'Imperial courtyards and the lanes of the hutongs.'),
    'Berlin': ('Germany', 'Contemporary galleries, parks and layers of history.'),
    'Brisbane': ('Australia', 'Ferry rides on the river and walks along South Bank.'),
    'Buenos Aires': ('Argentina', 'Tango, neighborhood cafes and late dinners.'),
    'Cairo': ('Egypt', 'Old city markets and a day at the pyramids of Giza.'),
    'Chicago': ('United States', 'Architecture along the river and walks by Lake Michigan.'),
    'Copenhagen': ('Denmark', 'Harbor swims, bakeries and bike-friendly streets.'),
    'Delhi': ('India', 'Mughal architecture and the food lanes of Old Delhi.'),
    'Dubai': ('United Arab Emirates', 'Creek crossings, souks and skyline views.'),
    'Dublin': ('Ireland', 'Literary stops and live music in neighborhood pubs.'),
    'Edinburgh': ('United Kingdom', 'Old Town lanes and a climb up Arthur?s Seat.'),
    'Florence': ('Italy', 'Renaissance art and sunset walks over the Arno.'),
    'Hanoi': ('Vietnam', 'Lakeside mornings and coffee in the Old Quarter.'),
    'Hong Kong': ('Hong Kong', 'Harbor ferries, dim sum and hillside trails.'),
    'Istanbul': ('Turkey', 'Ferries across the Bosphorus and bazaars on foot.'),
    'Jakarta': ('Indonesia', 'Old Town museums and Indonesian street food.'),
    'Kyoto': ('Japan', 'Temple gardens and quiet lanes in Higashiyama.'),
    'Kuala Lumpur': ('Malaysia', 'Food stalls, city parks and a visit to Batu Caves.'),
    'Lisbon': ('Portugal', 'Tram rides, hilltop viewpoints and custard tarts.'),
    'London': ('United Kingdom', 'Thames walks, neighborhood markets and museums.'),
    'Los Angeles': ('United States', 'Coastal neighborhoods and views from Griffith Park.'),
    'Madrid': ('Spain', 'Art museums, park strolls and late-night tapas.'),
    'Manila': ('Philippines', 'The walled streets of Intramuros and Chinatown food stops.'),
    'Melbourne': ('Australia', 'Laneway coffee, markets and gallery afternoons.'),
    'Mexico City': ('Mexico', 'Museum days, street tacos and leafy plazas.'),
    'Montreal': ('Canada', 'Old port walks, bagel bakeries and Mount Royal.'),
    'Mumbai': ('India', 'Seafront walks, Art Deco streets and busy food markets.'),
    'Munich': ('Germany', 'Beer gardens and afternoons in the English Garden.'),
    'New York City': ('United States', 'Neighborhood walks, galleries and skyline views.'),
    'Osaka': ('Japan', 'Dotonbori after dark and street snacks around Namba.'),
    'Paris': ('France', 'Sidewalk cafes, small museums and walks along the Seine.'),
    'Prague': ('Czechia', 'Cobblestone lanes and a walk across Charles Bridge.'),
    'Rio de Janeiro': ('Brazil', 'Beachfront walks and mountain views over the city.'),
    'Rome': ('Italy', 'Ancient ruins, neighborhood trattorias and piazzas.'),
    'San Francisco': ('United States', 'Cable car rides and walks overlooking the bay.'),
    'Seoul': ('South Korea', 'Palace grounds, market snacks and hillside neighborhoods.'),
    'Shanghai': ('China', 'Bund riverfront walks and old lanes around Yu Garden.'),
    'Singapore': ('Singapore', 'Hawker meals, waterfront walks and tropical gardens.'),
    'Stockholm': ('Sweden', 'Island ferries, Old Town streets and waterside museums.'),
    'Sydney': ('Australia', 'Harbor ferries and walks between ocean beaches.'),
    'Taipei': ('Taiwan', 'Night markets, tea houses and a hike up Elephant Mountain.'),
    'Tokyo': ('Japan', 'Neighborhood food halls, shrine paths and late-night streets.'),
    'Toronto': ('Canada', 'Island ferries and food stops in Kensington Market.'),
    'Venice': ('Italy', 'Canal crossings and quiet walks through the smaller lanes.'),
    'Vienna': ('Austria', 'Coffeehouses, art museums and palace gardens.'),
    'Warsaw': ('Poland', 'Old Town squares and walks along the Vistula.'),
}

LOCAL_PHOTOS = {
    'Lisbon': ('trends-lisbon.webp', 'Aayush Gupta', 'ljhCEaHYWJ8'),
    'London': ('trends-london.webp', 'Benjamin Davies', 'Oja2ty_9ZLM'),
    'Paris': ('trends-paris.webp', 'Pavel Abramiankou', 'yzh7B-9sOhc'),
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
    photos = _city_photos([city['name'] for city in cities if city['name'] not in LOCAL_PHOTOS])
    for city in cities:
        name = city['name']
        city['country'], city['description'] = CITIES[name]
        if name in LOCAL_PHOTOS:
            filename, artist, identifier = LOCAL_PHOTOS[name]
            city['photo'] = {'url': static(f'home/assets/{filename}'), 'artist': artist,
                             'source': f'https://unsplash.com/photos/{identifier}'}
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
