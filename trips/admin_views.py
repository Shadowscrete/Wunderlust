"""Administrator pages: overview analytics, users, trips, reports, travel information and notices.

Data handling rules for everything in this module:
- Every view requires the ADMINISTRATOR role; every change is POST + CSRF.
- Lists are filtered and paginated in the database (never load a whole table into Python).
- Analytics are aggregate queries only, cached briefly under a key that holds no personal data.
- Passwords, session keys and reporter identities are never sent to the reported traveler.
"""
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Report, UserSession
from accounts.sessions import end_session
from accounts.social import avatar_url_for, initials_for

from .views import _notify_group
from .decorators import role_required
from .forms import SystemNotificationForm, TravelInfoForm
from .models import ChecklistCheck, Flight, GroupMember, Notification, TravelInfo, Trip

User = get_user_model()
ADMIN = User.Role.ADMINISTRATOR
admin_required = role_required(ADMIN)

PAGE_SIZE = 20
ANALYTICS_CACHE_KEY = 'admin-analytics-v1'
ANALYTICS_TTL = 60 * 5
MONTHS = 6


def _page(request, queryset, size=PAGE_SIZE):
    return Paginator(queryset, size).get_page(request.GET.get('page'))


def _query_string(request):
    """Current filters without `page`, so pagination links keep them."""
    params = request.GET.copy()
    params.pop('page', None)
    return params.urlencode()


def _redirect_back(request, fallback):
    from django.utils.http import url_has_allowed_host_and_scheme
    target = request.POST.get('next', '')
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(target)
    return redirect(fallback)


# ------------------------------------------------------------------ Overview

def _month_starts(today, count):
    year, month = today.year, today.month
    starts = []
    for _ in range(count):
        starts.append(date(year, month, 1))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(starts))


def _monthly_series(queryset, field, starts):
    rows = (queryset.filter(**{f'{field}__date__gte': starts[0]})
            .annotate(month=TruncMonth(field)).values('month').annotate(total=Count('pk')))
    by_month = {}
    for row in rows:
        month = row['month']
        key = month.date() if hasattr(month, 'date') else month
        by_month[key.replace(day=1)] = row['total']
    peak = max(by_month.values(), default=0) or 1
    return [{'label': start.strftime('%b'), 'full': start.strftime('%B %Y'), 'value': by_month.get(start, 0),
             'pct': round(by_month.get(start, 0) * 100 / peak)} for start in starts]


def _bars(rows, label_key):
    peak = max((row['total'] for row in rows), default=0) or 1
    return [{'label': row[label_key], 'value': row['total'], 'pct': round(row['total'] * 100 / peak)} for row in rows]


def _analytics():
    """Every overview number, from a handful of aggregate queries. Cached for five minutes."""
    data = cache.get(ANALYTICS_CACHE_KEY)
    if data is not None:
        return data
    today = timezone.localdate()
    starts = _month_starts(today, MONTHS)
    user_counts = User.objects.aggregate(
        total=Count('pk'),
        travelers=Count('pk', filter=Q(role=User.Role.TRAVELER)),
        inactive=Count('pk', filter=Q(is_active=False)),
        new_30=Count('pk', filter=Q(date_joined__date__gte=today - timedelta(days=30))),
    )
    trip_counts = Trip.objects.aggregate(
        total=Count('pk'),
        active=Count('pk', filter=Q(status__in=(Trip.Status.PLANNING, Trip.Status.READY, Trip.Status.IN_PROGRESS))),
        group=Count('pk', filter=Q(group_trip__isnull=False)),
    )
    member_ticks = GroupMember.objects.filter(group_trip__trip_id=OuterRef('item__trip_id'), user_id=OuterRef('user_id'))
    done = ChecklistCheck.objects.filter(Q(user_id=F('item__trip__owner_id')) | Exists(member_ticks)).count()
    trips = Trip.objects.annotate(
        items=Count('checklist_items', distinct=True),
        others=Count('group_trip__members', distinct=True, filter=~Q(group_trip__members__user_id=F('owner_id'))),
    )
    total = trips.aggregate(total=Sum(F('items') * (F('others') + 1)))['total']
    status_labels = dict(Trip.Status.choices)
    status_rows = [{'label': status_labels.get(r['status'], r['status']), 'total': r['total']}
                   for r in Trip.objects.values('status').annotate(total=Count('pk')).order_by('-total')]
    reason_labels = dict(Report.Reason.choices)
    reason_rows = [{'label': reason_labels.get(r['reason'], r['reason']), 'total': r['total']}
                   for r in Report.objects.filter(status=Report.Status.OPEN).values('reason').annotate(total=Count('pk')).order_by('-total')]
    destination_rows = [{'label': f"{r['destination']}{', ' + r['country'] if r['country'] else ''}", 'total': r['total']}
                        for r in Trip.objects.values('destination', 'country').annotate(total=Count('pk')).order_by('-total', 'destination')[:6]]
    data = {
        'users': user_counts,
        'trips': trip_counts,
        'completion_rate': round(done * 100 / total) if total else 0,
        'open_reports': Report.objects.filter(status=Report.Status.OPEN).count(),
        'signups': _monthly_series(User.objects.all(), 'date_joined', starts),
        'trips_created': _monthly_series(Trip.objects.all(), 'created_at', starts),
        'statuses': _bars(status_rows, 'label'),
        'destinations': _bars(destination_rows, 'label'),
        'report_reasons': _bars(reason_rows, 'label'),
        'generated_at': timezone.now(),
    }
    cache.set(ANALYTICS_CACHE_KEY, data, ANALYTICS_TTL)
    return data


def invalidate_analytics():
    cache.delete_many([ANALYTICS_CACHE_KEY, 'admin-open-reports'])


@admin_required
def admin_dashboard(request):
    if request.method == 'POST' and request.POST.get('action') == 'refresh':
        invalidate_analytics()
        return redirect('admin_dashboard')
    return render(request, 'dashboard/admin/overview.html', {
        'stats': _analytics(),
        'recent_reports': Report.objects.filter(status=Report.Status.OPEN).select_related('reported_user')[:5],
    })


# ------------------------------------------------------------------ Users

def _users_with_counts():
    return User.objects.annotate(
        open_reports=Count('reports_received', filter=Q(reports_received__status=Report.Status.OPEN), distinct=True),
        total_reports=Count('reports_received', distinct=True),
        trip_count=Count('owned_trips', distinct=True),
    )


@admin_required
def admin_users(request):
    query = ' '.join(request.GET.get('q', '').split())[:80]
    role = request.GET.get('role', '')
    status = request.GET.get('status', '')
    sort = request.GET.get('sort', 'newest')
    users = _users_with_counts()
    for term in query.split():
        users = users.filter(Q(username__icontains=term) | Q(email__icontains=term) | Q(first_name__icontains=term) | Q(last_name__icontains=term))
    if role in User.Role.values:
        users = users.filter(role=role)
    if status == 'active':
        users = users.filter(is_active=True)
    elif status == 'inactive':
        users = users.filter(is_active=False)
    elif status == 'reported':
        users = users.filter(open_reports__gt=0)
    users = users.order_by({'reports': '-total_reports', 'name': 'username'}.get(sort, '-date_joined'), 'pk')
    return render(request, 'dashboard/admin/users.html', {
        'page_obj': _page(request, users.only('pk', 'username', 'first_name', 'last_name', 'email', 'role', 'is_active', 'date_joined', 'last_login')),
        'query': query, 'role': role, 'status': status, 'sort': sort,
        'role_choices': User.Role.choices, 'qs': _query_string(request),
    })


@admin_required
def admin_user_detail(request, user_id):
    person = get_object_or_404(_users_with_counts().select_related('profile'), pk=user_id)
    trips = (Trip.objects.filter(Q(owner=person) | Q(group_trip__members__user=person)).distinct()
             .select_related('owner').order_by('-start_date'))
    reports = Report.objects.filter(reported_user=person).select_related('reporter')
    return render(request, 'dashboard/admin/user_detail.html', {
        'person': person,
        'person_avatar': avatar_url_for(person),
        'person_initials': initials_for(person),
        'trips_page': _page(request, trips, 10),
        'reports': reports[:20],
        'reports_made': Report.objects.filter(reporter=person).count(),
        'device_count': UserSession.objects.filter(user=person).count(),
        'is_self': person.pk == request.user.pk,
        'role_choices': User.Role.choices,
    })


def _end_all_sessions(user):
    for key in UserSession.objects.filter(user=user).values_list('session_key', flat=True).iterator():
        end_session(key)
    UserSession.objects.filter(user=user).delete()


@admin_required
@require_POST
def admin_user_action(request, user_id):
    person = get_object_or_404(User, pk=user_id)
    action = request.POST.get('action')
    fallback = reverse('admin_user_detail', args=[person.pk])
    if person.pk == request.user.pk:
        messages.error(request, 'You can’t change your own account from here.')
        return _redirect_back(request, fallback)
    if action == 'deactivate':
        if person.role == ADMIN:
            messages.error(request, 'Administrators can’t be deactivated here. Change their role first.')
        else:
            person.is_active = False
            person.save(update_fields=['is_active'])
            _end_all_sessions(person)
            messages.success(request, f'@{person.username} has been deactivated and signed out everywhere.')
    elif action == 'activate':
        person.is_active = True
        person.save(update_fields=['is_active'])
        messages.success(request, f'@{person.username} has been reactivated.')
    elif action == 'set_role':
        role = request.POST.get('role')
        if role in User.Role.values and role != person.role:
            person.role = role
            person.save(update_fields=['role'])
            _end_all_sessions(person)  # the new role takes effect on their next sign-in
            messages.success(request, f'@{person.username} is now {person.get_role_display().lower()}.')
    invalidate_analytics()
    return _redirect_back(request, fallback)


# ------------------------------------------------------------------ Trips

@admin_required
def admin_trips(request):
    query = ' '.join(request.GET.get('q', '').split())[:80]
    status = request.GET.get('status', '')
    kind = request.GET.get('kind', '')
    trips = Trip.objects.select_related('owner').annotate(group_size=Count('group_trip__members', distinct=True))
    for term in query.split():
        trips = trips.filter(Q(destination__icontains=term) | Q(country__icontains=term) | Q(owner__username__icontains=term))
    if status in Trip.Status.values:
        trips = trips.filter(status=status)
    if kind == 'group':
        trips = trips.filter(group_trip__isnull=False)
    elif kind == 'solo':
        trips = trips.filter(group_trip__isnull=True)
    return render(request, 'dashboard/admin/trips.html', {
        'page_obj': _page(request, trips.order_by('-start_date', 'pk')),
        'query': query, 'status': status, 'kind': kind,
        'status_choices': Trip.Status.choices, 'qs': _query_string(request),
    })


@admin_required
def admin_trip_detail(request, trip_id):
    trip = get_object_or_404(Trip.objects.select_related('owner'), pk=trip_id)
    members = GroupMember.objects.filter(group_trip__trip=trip).select_related('user') if trip.is_group_trip else []
    return render(request, 'dashboard/admin/trip_detail.html', {
        'trip': trip,
        'members': members,
        'days': trip.itinerary_days.prefetch_related('activities').order_by('date'),
        'flights': Flight.objects.filter(trip=trip).order_by('flight_date'),
        'checklist': trip.checklist_items.aggregate(total=Count('pk'), done=Count('pk', filter=Q(checks__user=trip.owner), distinct=True)),
    })


@admin_required
@require_POST
def admin_trip_action(request, trip_id):
    trip = get_object_or_404(Trip, pk=trip_id)
    action = request.POST.get('action')
    if action == 'cancel' and trip.status != Trip.Status.CANCELLED:
        with transaction.atomic():
            trip.status = Trip.Status.CANCELLED
            trip.save(update_fields=['status', 'updated_at'])
            _notify_group(trip, f'Your trip to {trip.destination} was cancelled',
                          'The Wunderlust team cancelled this trip. Contact support if you think this is a mistake.')
        messages.success(request, f'Trip to {trip.destination} cancelled.')
    elif action == 'delete':
        destination = trip.destination
        with transaction.atomic():
            _notify_group(trip, f'Your trip to {destination} was removed',
                          'The Wunderlust team removed this trip. Contact support if you think this is a mistake.',
                          retain_after_delete=True)
            trip.delete()
        messages.success(request, f'Trip to {destination} deleted.')
        invalidate_analytics()
        return redirect('admin_trips')
    invalidate_analytics()
    return _redirect_back(request, reverse('admin_trip_detail', args=[trip.pk]))


# ------------------------------------------------------------------ Reports

@admin_required
def admin_reports(request):
    status = request.GET.get('status', Report.Status.OPEN)
    reason = request.GET.get('reason', '')
    reports = Report.objects.select_related('reporter', 'reported_user').annotate(
        times_reported=Count('reported_user__reports_received', distinct=True))
    if status in Report.Status.values:
        reports = reports.filter(status=status)
    else:
        status = ''
    if reason in Report.Reason.values:
        reports = reports.filter(reason=reason)
    most_reported = (User.objects.annotate(open_reports=Count('reports_received', filter=Q(reports_received__status=Report.Status.OPEN)))
                     .filter(open_reports__gt=0).order_by('-open_reports', 'username').only('pk', 'username', 'is_active')[:5])
    return render(request, 'dashboard/admin/reports.html', {
        'page_obj': _page(request, reports),
        'status': status, 'reason': reason,
        'status_choices': Report.Status.choices, 'reason_choices': Report.Reason.choices,
        'most_reported': most_reported, 'qs': _query_string(request),
    })


@admin_required
@require_POST
def admin_report_action(request, report_id):
    report = get_object_or_404(Report.objects.select_related('reported_user'), pk=report_id)
    action = request.POST.get('action')
    status = {'review': Report.Status.REVIEWED, 'dismiss': Report.Status.DISMISSED, 'reopen': Report.Status.OPEN}.get(action)
    if status:
        report.status = status
        report.reviewed_at = None if status == Report.Status.OPEN else timezone.now()
        report.save(update_fields=['status', 'reviewed_at'])
        messages.success(request, f'Report marked {report.get_status_display().lower()}.')
    elif action == 'deactivate_user':
        person = report.reported_user
        if person.role == ADMIN or person.pk == request.user.pk:
            messages.error(request, 'That account can’t be deactivated from a report.')
        else:
            person.is_active = False
            person.save(update_fields=['is_active'])
            _end_all_sessions(person)
            Report.objects.filter(reported_user=person, status=Report.Status.OPEN).update(status=Report.Status.REVIEWED, reviewed_at=timezone.now())
            messages.success(request, f'@{person.username} deactivated; their open reports are marked reviewed.')
    invalidate_analytics()
    return _redirect_back(request, reverse('admin_reports'))


# ------------------------------------------------------------------ Travel information

@admin_required
def admin_travel_info(request, entry_id=None):
    entry = get_object_or_404(TravelInfo, pk=entry_id, trip__isnull=True) if entry_id else None
    form = TravelInfoForm(instance=entry)
    if request.method == 'POST':
        if request.POST.get('action') == 'delete' and entry:
            entry.delete()
            messages.success(request, 'Travel entry deleted.')
            return redirect('admin_travel_info')
        form = TravelInfoForm(request.POST, instance=entry)
        if form.is_valid():
            form.save()
            messages.success(request, 'Travel entry updated.' if entry else 'Travel entry saved.')
            return redirect('admin_travel_info')
    query = ' '.join(request.GET.get('q', '').split())[:80]
    # Only the shared library (entries not tied to a traveler's private trip notes).
    entries = TravelInfo.objects.filter(trip__isnull=True)
    if query:
        entries = entries.filter(Q(title__icontains=query) | Q(destination__icontains=query) | Q(details__icontains=query))
    return render(request, 'dashboard/admin/travel_info.html', {
        'form': form, 'entry': entry, 'query': query,
        'page_obj': _page(request, entries.order_by('-updated_at')), 'qs': _query_string(request),
    })


# ------------------------------------------------------------------ Notices

@admin_required
def admin_notices(request):
    form = SystemNotificationForm(prefix='notice')
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete':
            notice = Notification.objects.filter(pk=request.POST.get('notice', '0') if request.POST.get('notice', '').isdigit() else 0,
                                                 trip__isnull=True).first()
            if notice:
                notice.delete()
                messages.success(request, 'Notice deleted.')
            return redirect('admin_notices')
        form = SystemNotificationForm(request.POST, prefix='notice')
        if form.is_valid():
            notice = form.save()
            messages.success(request, f'Notice sent to {"@" + notice.user.username if notice.user_id else "all travelers"}.')
            return redirect('admin_notices')
    # Team notices only: broadcasts, plus direct notices to travelers. Admin inbox items are excluded.
    notices = (Notification.objects.filter(trip__isnull=True)
               .filter(Q(user__isnull=True) | Q(user__role=User.Role.TRAVELER))
               .select_related('user').annotate(read_count=Count('reads')))
    return render(request, 'dashboard/admin/notices.html', {
        'form': form,
        'page_obj': _page(request, notices.order_by('-created_at')),
        'traveler_count': User.objects.filter(role=User.Role.TRAVELER, is_active=True).count(),
    })


@admin_required
def admin_inbox(request):
    items = Notification.objects.filter(user=request.user).order_by('-created_at')
    items.filter(is_read=False).update(is_read=True)
    if request.method == 'POST' and request.POST.get('action') == 'read_all':
        return redirect('admin_inbox')
    return render(request, 'dashboard/admin/inbox.html', {'page_obj': _page(request, items)})


def notify_admins_of_report(report):
    """Drop a notification in every active administrator's inbox. One INSERT."""
    admin_ids = User.objects.filter(role=ADMIN, is_active=True).values_list('pk', flat=True)
    Notification.objects.bulk_create([
        Notification(user_id=pk, title=f'New report: @{report.reported_user.username}',
                     message=f'{report.get_reason_display()}. Review it in Reports.')
        for pk in admin_ids
    ])
    invalidate_analytics()
