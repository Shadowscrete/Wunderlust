"""Site-wide error handling.

- Page requests get friendly error pages (templates/<code>.html).
- Background (fetch/XHR) requests get JSON errors, so page scripts can react instead of receiving an HTML page.
- A lost database connection becomes a 503 "try again" page instead of a generic 500.
"""
import logging

from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.db import DatabaseError, InterfaceError, OperationalError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render

logger = logging.getLogger('wunderlust.errors')

MESSAGES = {
    400: 'That request was malformed.',
    403: 'You don’t have permission to do that.',
    404: 'That item no longer exists.',
    500: 'Something went wrong on our side. Please try again.',
    503: 'The service is temporarily unavailable. Please try again in a minute.',
}


def wants_json(request):
    return (request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'application/json' in request.headers.get('Accept', ''))


def error_response(request, status, template=None, message=None):
    if wants_json(request):
        return JsonResponse({'error': message or MESSAGES.get(status, MESSAGES[500])}, status=status)
    try:
        return render(request, template or f'errors/{status}.html', status=status)
    except Exception:  # the error page itself must never fail
        logger.exception('Error page %s failed to render', status)
        return HttpResponse(MESSAGES.get(status, MESSAGES[500]), status=status, content_type='text/plain; charset=utf-8')


class ErrorHandlingMiddleware:
    """JSON errors for background requests and a 503 page for database outages.
    Other page errors fall through to the handler404/403/500 views below."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, (OperationalError, InterfaceError)):
            logger.exception('Database unavailable on %s %s', request.method, request.path)
            return error_response(request, 503)
        if not wants_json(request):
            return None
        if isinstance(exception, Http404):
            return error_response(request, 404)
        if isinstance(exception, PermissionDenied):
            return error_response(request, 403)
        if isinstance(exception, SuspiciousOperation):
            return error_response(request, 400)
        if isinstance(exception, DatabaseError):
            logger.exception('Database error on %s %s', request.method, request.path)
            return error_response(request, 503)
        logger.exception('Unhandled error on %s %s', request.method, request.path)
        return error_response(request, 500)


def bad_request(request, exception=None):
    return error_response(request, 400)


def permission_denied(request, exception=None):
    return error_response(request, 403)


def page_not_found(request, exception=None):
    return error_response(request, 404)


def server_error(request):
    return error_response(request, 500)


def csrf_failure(request, reason=''):
    logger.warning('CSRF failure on %s: %s', request.path, reason)
    return error_response(request, 403, template='errors/403_csrf.html',
                          message='Your session expired. Reload the page and try again.')
