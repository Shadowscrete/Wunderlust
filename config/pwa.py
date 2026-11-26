"""Progressive Web App endpoints: the manifest, the service worker and the offline page.

The service worker must be served from the site root (not /static/) so it can control every page.
"""
import json

from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_control

from .context_processors import asset_version


@cache_control(public=True, max_age=60 * 60)
def manifest(request):
    data = {
        'name': 'Wunderlust',
        'short_name': 'Wunderlust',
        'description': 'Plan group trips together: shared itinerary, document checklists, live flight status, and who is ready to go.',
        'id': '/dashboard/',
        'start_url': '/dashboard/?source=pwa',
        'scope': '/',
        'display': 'standalone',
        'orientation': 'portrait-primary',
        'background_color': '#f7f8f5',
        'theme_color': '#214936',
        'categories': ['travel', 'productivity'],
        'icons': [
            {'src': static('pwa/icon-192.png'), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('pwa/icon-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('pwa/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
        'shortcuts': [
            {'name': 'My trips', 'url': '/dashboard/trips/', 'icons': [{'src': static('pwa/icon-192.png'), 'sizes': '192x192'}]},
            {'name': 'Plan a trip', 'url': '/dashboard/trips/new/', 'icons': [{'src': static('pwa/icon-192.png'), 'sizes': '192x192'}]},
        ],
    }
    return HttpResponse(json.dumps(data), content_type='application/manifest+json')


@cache_control(no_cache=True, max_age=0)
def service_worker(request):
    version = asset_version(request)['asset_version']
    response = render(request, 'pwa/sw.js', {
        'version': version,
        'precache': json.dumps([
            '/offline/',
            f"{static('dashboard/dashboard.css')}?v={version}",
            f"{static('dashboard/dashboard.js')}?v={version}",
            static('pwa/icon-192.png'),
        ]),
    }, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    return response


def offline(request):
    return render(request, 'pwa/offline.html')
