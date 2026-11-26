"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.templatetags.static import static as static_url
from django.urls import path, include
from django.views.generic import RedirectView
from . import pwa, views

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url=static_url('home/assets/favicon-v2.ico'), permanent=False)),
    path('manifest.webmanifest', pwa.manifest, name='pwa_manifest'),
    path('sw.js', pwa.service_worker, name='pwa_service_worker'),
    path('offline/', pwa.offline, name='pwa_offline'),
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('accounts/', include('accounts.urls')),
    path('dashboard/', include('trips.urls')),
]

if settings.DEBUG:
    # Serve uploaded profile pictures during development. In production, serve MEDIA_ROOT from the web server.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler400 = 'config.errors.bad_request'
handler403 = 'config.errors.permission_denied'
handler404 = 'config.errors.page_not_found'
handler500 = 'config.errors.server_error'
