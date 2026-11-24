"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()

# Refuse to serve with an incomplete production configuration, naming exactly what's missing.
# (Checked here rather than in settings.py so Vercel's build, which reads settings, still succeeds.)
from django.conf import settings  # noqa: E402
from django.core.exceptions import ImproperlyConfigured  # noqa: E402

if getattr(settings, 'MISSING_PRODUCTION_SETTINGS', None):
    raise ImproperlyConfigured(
        'Missing environment variables: ' + ', '.join(settings.MISSING_PRODUCTION_SETTINGS)
        + '. Add them in Vercel > Settings > Environment Variables (for this environment) and redeploy.'
    )
