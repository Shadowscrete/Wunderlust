import os

from django.conf import settings

_ASSETS = ('dashboard/dashboard.css', 'dashboard/dashboard.js')


def asset_version(request):
    """A version tag from the dashboard CSS/JS modification times. Appended as ?v=… so browsers
    fetch the new file as soon as it changes, instead of reusing an old cached copy."""
    stamps = []
    for name in _ASSETS:
        for root in settings.STATICFILES_DIRS or []:
            path = os.path.join(root, name)
            if os.path.exists(path):
                stamps.append(int(os.path.getmtime(path)))
                break
    return {'asset_version': max(stamps) if stamps else 1}
