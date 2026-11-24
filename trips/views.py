from django.utils.http import url_has_allowed_host_and_scheme
from datetime import datetime, time, timedelta
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.context_processors import get_user_prefs
from accounts.models import Profile

from .decorators import role_required
from .forms import ActivityForm, FlightForm, TripEditForm, ChecklistQuantityForm, CustomChecklistForm, ItineraryDayForm, SystemNotificationForm, TravelInfoForm, TripForm, TripTravelInfoForm
from .models import Activity, Checklist, ChecklistCheck, Flight, GroupMember, GroupTrip, ItineraryDay, Notification, TravelInfo, Trip, TripPlace
from .recommendations import ideas_for
from .models import trip_readiness
from accounts.social import avatar_url_for, initials_for

User = get_user_model()


def dashboard_home(request):
    if not request.user.is_authenticated:
        return redirect('login')
    if request.user.role == User.Role.ADMINISTRATOR:
        return redirect('admin_dashboard')
    return redirect('traveler_dashboard')


@role_required(User.Role.TRAVELER)
def traveler_dashboard(request):
    # Owned trips and accepted group memberships form the traveler's ORM scope.
    trips = Trip.objects.filter(
        Q(owner=request.user) | Q(group_trip__members__user=request.user)
    ).distinct().select_related('owner').prefetch_related('itinerary_days__activities', 'checklist_items', 'travel_info')
    upcoming_trips = trips.filter(end_date__gte=timezone.localdate()).order_by('start_date')
    # Readiness is scoped to trips that are still ahead of the traveler.
    checklist_items = Checklist.objects.filter(trip__in=upcoming_trips)
    documents = _with_my_ticks(checklist_items.filter(is_document=True), request.user)
    packing_items = _with_my_ticks(checklist_items.filter(is_document=False), request.user)
    # One aggregate query instead of ten separate COUNT/EXISTS round-trips.
    stats = checklist_items.aggregate(
        document_total=Count('pk', distinct=True, filter=Q(is_document=True)),
        document_done=Count('pk', distinct=True, filter=Q(is_document=True, checks__user=request.user)),
        packing_total=Count('pk', distinct=True, filter=Q(is_document=False)),
        packing_done=Count('pk', distinct=True, filter=Q(is_document=False, checks__user=request.user)),
    )
    recent_activities = Activity.objects.filter(
        day__trip__in=trips,
        day__date__gte=timezone.localdate(),
    ).select_related('day__trip').order_by('day__date', 'start_time')[:6]
    group_memberships = GroupMember.objects.filter(user=request.user).select_related('group_trip__trip', 'group_trip__created_by')
    travel_info = TravelInfo.objects.filter(Q(trip__in=upcoming_trips) | Q(trip__isnull=True)).distinct()[:8]
    return render(request, 'dashboard/traveler.html', {
        'trips': upcoming_trips[:5],
        'has_any_trips': trips.exists(),
        'documents': documents,
        'packing_items': packing_items,
        'document_total': stats['document_total'],
        'document_done': stats['document_done'],
        'document_progress': round(stats['document_done'] * 100 / stats['document_total']) if stats['document_total'] else 0,
        'packing_total': stats['packing_total'],
        'packing_done': stats['packing_done'],
        'packing_progress': round(stats['packing_done'] * 100 / stats['packing_total']) if stats['packing_total'] else 0,
        'activities': recent_activities,
        'group_memberships': group_memberships[:5],
        'travel_info': travel_info,
        'today_notification_count': Notification.objects.filter(
            _notification_scope(request.user), created_at__date=timezone.localdate(), is_read=False
        ).count(),
    })


def _accessible_trips(user):
    return Trip.objects.filter(Q(owner=user) | Q(group_trip__members__user=user)).distinct()


def _notification_scope(user):
    """Notifications a user should see: their own, plus system-wide notices unless they turned those off."""
    if get_user_prefs(user)['notify_system']:
        return Q(user=user) | Q(user__isnull=True)
    return Q(user=user)


def _notify_group(trip, title, message, exclude_user=None, kind='notify_trip_updates'):
    group = getattr(trip, 'group_trip', None)
    recipients = set()
    if trip.owner_id != exclude_user:
        recipients.add(trip.owner_id)
    if group:
        recipients.update(group.members.exclude(user_id=exclude_user).values_list('user_id', flat=True))
    # Skip travelers who switched this kind of notification off in Settings.
    if recipients:
        recipients -= set(Profile.objects.filter(user_id__in=recipients, **{kind: False}).values_list('user_id', flat=True))
    Notification.objects.bulk_create([
        Notification(user_id=user_id, trip=trip, title=title, message=message)
        for user_id in recipients
    ])


def _build_itinerary(trip, place_names):
    day_count = (trip.end_date - trip.start_date).days + 1
    place_index = 0
    for index in range(day_count):
        current_date = trip.start_date + timedelta(days=index)
        day = ItineraryDay.objects.create(
            trip=trip,
            date=current_date,
            title=f'Day {index + 1}',
            notes=f'Suggested starting points for {trip.destination}, {trip.country}. Adjust to your pace.',
        )
        ideas = ideas_for(trip.destination, trip.country)
        if place_names:
            selected_place = place_names[place_index % len(place_names)]
            place_index += 1
            Activity.objects.create(
                day=day,
                title=f'Explore {selected_place}',
                start_time='09:30',
                location=selected_place,
                notes='A place you added to this trip.',
                is_recommended=True,
            )
        idea, location = ideas[index % len(ideas)]
        Activity.objects.create(
            day=day,
            title=idea,
            start_time='14:00',
            location=location,
            notes=f'A flexible suggestion for your time in {trip.destination}. Check local opening times before you go.',
            is_recommended=True,
        )


@role_required(User.Role.TRAVELER)
def trip_list(request):
    # One query for the whole list: group info is joined and checklist counts are annotated,
    # instead of extra queries per trip card.
    trips = _accessible_trips(request.user).select_related('owner', 'group_trip').annotate(
        checklist_total=Count('checklist_items', distinct=True),
    ).order_by('start_date')
    return render(request, 'dashboard/trip_list.html', {'trips': trips})


@role_required(User.Role.TRAVELER)
def preparation_overview(request):
    # Preparation and travel information now live inside each trip (tabs on the trip page).
    return redirect('trip_list')


@role_required(User.Role.TRAVELER)
def travel_information_overview(request):
    # Preparation and travel information now live inside each trip (tabs on the trip page).
    return redirect('trip_list')


@role_required(User.Role.TRAVELER)
def trip_create(request):
    form = TripForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            trip = form.save(commit=False)
            trip.owner = request.user
            trip.save()
            place_names = [line.strip() for line in form.cleaned_data['places'].splitlines() if line.strip()]
            TripPlace.objects.bulk_create([
                TripPlace(trip=trip, name=name, visit_order=order)
                for order, name in enumerate(place_names, start=1)
            ])
            Checklist.objects.bulk_create([
                Checklist(trip=trip, title=name, is_document=True, is_mandatory=True)
                for name in ('Passport', 'Visa', 'Identification', 'Flight Documents')
            ] + [
                Checklist(trip=trip, title=name)
                for name in ('Prescription medication', 'Travel adapter', 'Weather-appropriate clothing', 'Toiletries', 'Reusable water bottle')
            ])
            if trip.airline:
                TravelInfo.objects.create(
                    trip=trip,
                    category=TravelInfo.Category.FLIGHT,
                    title='Airline',
                    details=f'{trip.airline}\nAdd your flight number and booking reference here when available.',
                )
            if form.cleaned_data['generate_itinerary']:
                _build_itinerary(trip, place_names)
            Notification.objects.create(
                user=request.user,
                trip=trip,
                title='Trip created',
                message=f'{trip.destination} is in your travel space. Start with your documents and itinerary.',
            )
        messages.success(request, f'{trip.destination} was added to your trips.')
        return redirect('trip_detail', trip_id=trip.pk)
    return render(request, 'dashboard/trip_form.html', {'form': form})


def _with_my_ticks(items, user):
    """Annotate checklist items with is_checked: whether *this* traveler has ticked them."""
    return items.annotate(is_checked=Exists(ChecklistCheck.objects.filter(item=OuterRef('pk'), user=user)))


def _my_totals(trip_id, user):
    """This traveler's progress on one trip's checklist."""
    return Checklist.objects.filter(trip_id=trip_id).aggregate(
        all_count=Count('pk', distinct=True),
        all_done=Count('pk', distinct=True, filter=Q(checks__user=user)),
        document_count=Count('pk', distinct=True, filter=Q(is_document=True)),
        document_done=Count('pk', distinct=True, filter=Q(is_document=True, checks__user=user)),
    )


def _readiness_rows(trip, viewer):
    rows = trip_readiness(trip)
    for row in rows:
        row['is_me'] = row['user'].pk == viewer.pk
        row['avatar_url'] = avatar_url_for(row['user'])
        row['initials'] = initials_for(row['user'])
    return rows


def _post_id(request, name):
    """A whole-number id from POST data, or None. Garbage like "abc" must mean "not found", not a server error."""
    value = request.POST.get(name, '')
    return int(value) if value.isdigit() else None


def _owned_trip(request, trip_id):
    """Only the trip's owner may edit or delete it."""
    return get_object_or_404(Trip.objects.select_related('owner'), pk=trip_id, owner=request.user)


@role_required(User.Role.TRAVELER)
def trip_edit(request, trip_id):
    trip = _owned_trip(request, trip_id)
    form = TripEditForm(request.POST or None, instance=trip)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            trip = form.save()
            # Itinerary days outside the new dates no longer belong to the trip.
            removed, _ = trip.itinerary_days.exclude(date__range=(trip.start_date, trip.end_date)).delete()
        _notify_group(trip, 'Trip details updated', f'{request.user.get_username()} updated the trip to {trip.destination}.', request.user.pk)
        messages.success(request, 'Trip updated.' + (' Itinerary days outside the new dates were removed.' if removed else ''))
        return redirect('trip_detail', trip_id=trip.pk)
    return render(request, 'dashboard/trip_form.html', {'form': form, 'trip': trip, 'editing': True})


@role_required(User.Role.TRAVELER)
@require_POST
def trip_delete(request, trip_id):
    trip = _owned_trip(request, trip_id)
    destination = trip.destination
    group = getattr(trip, 'group_trip', None)
    member_ids = list(group.members.exclude(user=request.user).values_list('user_id', flat=True)) if group else []
    with transaction.atomic():
        trip.delete()
        # trip=None: these notices must outlive the trip they describe.
        if member_ids:
            muted = set(Profile.objects.filter(user_id__in=member_ids, notify_trip_updates=False).values_list('user_id', flat=True))
            Notification.objects.bulk_create([
                Notification(user_id=uid, title='Trip deleted', message=f'{request.user.get_username()} deleted the trip to {destination}.')
                for uid in member_ids if uid not in muted
            ])
    messages.success(request, f'The trip to {destination} was deleted.')
    return redirect('trip_list')


@role_required(User.Role.TRAVELER)
def trip_detail(request, trip_id):
    trip = get_object_or_404(_accessible_trips(request.user).select_related('owner'), pk=trip_id)
    checklist = _with_my_ticks(trip.checklist_items.all(), request.user)
    documents = checklist.filter(is_document=True)
    essentials = checklist.filter(is_document=False)
    travel_info_form = TripTravelInfoForm(prefix='info')
    checklist_form = CustomChecklistForm(prefix='item')
    activity_form = ActivityForm()
    itinerary_day_form = ItineraryDayForm(trip)
    flight_form = FlightForm(trip, prefix='flight')
    active_tab = 'overview'
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_flight':
            flight_form = FlightForm(trip, request.POST, prefix='flight')
            active_tab = 'travel-info'
            if flight_form.is_valid():
                flight = flight_form.save(commit=False)
                flight.added_by = request.user
                flight.save()
                _notify_group(trip, 'Flight added', f'{flight.flight_number} on {flight.flight_date:%b %d} was added to {trip.destination}.', request.user.pk)
                messages.success(request, f'Flight {flight.flight_number} added.')
                return redirect(f"{reverse('trip_detail', kwargs={'trip_id': trip.pk})}#travel-info")
        elif action == 'delete_flight':
            flight = get_object_or_404(trip.flights, pk=_post_id(request, 'flight_id'))
            messages.success(request, f'Flight {flight.flight_number} removed.')
            flight.delete()
            return redirect(f"{reverse('trip_detail', kwargs={'trip_id': trip.pk})}#travel-info")
        elif action == 'add_travel_info':
            travel_info_form = TripTravelInfoForm(request.POST, prefix='info')
            active_tab = 'travel-info'
            if travel_info_form.is_valid():
                info = travel_info_form.save(commit=False)
                info.trip = trip
                info.destination = trip.destination
                info.save()
                _notify_group(trip, 'Travel information updated', f'{info.title} was added to {trip.destination}.', request.user.pk)
                messages.success(request, 'Travel information saved.')
                return redirect(f"{reverse('trip_detail', kwargs={'trip_id': trip.pk})}#travel-info")
        elif action == 'add_checklist_item':
            checklist_form = CustomChecklistForm(request.POST, prefix='item')
            active_tab = 'preparation'
            if checklist_form.is_valid():
                item = checklist_form.save(commit=False)
                item.trip = trip
                item.is_custom = True
                item.save()
                _notify_group(trip, 'Preparation list updated', f'{item.title} was added to the checklist.', request.user.pk)
                messages.success(request, 'Custom item added.')
                return redirect(f"{reverse('trip_detail', kwargs={'trip_id': trip.pk})}#preparation")
        elif action == 'add_activity':
            day = get_object_or_404(trip.itinerary_days, pk=_post_id(request, 'day_id'))
            activity_form = ActivityForm(request.POST)
            if activity_form.is_valid():
                activity = activity_form.save(commit=False)
                activity.day = day
                activity.save()
                _notify_group(trip, 'Itinerary updated', f'{activity.title} was added to {trip.destination}.', request.user.pk)
                messages.success(request, 'Activity added to the itinerary.')
                return redirect('trip_detail', trip_id=trip.pk)
        elif action == 'add_itinerary_day':
            itinerary_day_form = ItineraryDayForm(trip, request.POST)
            if itinerary_day_form.is_valid():
                day = itinerary_day_form.save(commit=False)
                day.trip = trip
                day.save()
                messages.success(request, 'Itinerary day added.')
                return redirect('trip_detail', trip_id=trip.pk)
    days = trip.itinerary_days.prefetch_related('activities').all()
    travelers = _readiness_rows(trip, request.user)
    group_trip = getattr(trip, 'group_trip', None)
    flights = list(trip.flights.all())
    travel_info = list(trip.travel_info.all())
    return render(request, 'dashboard/trip_detail.html', {
        'trip': trip,
        'days': days,
        'documents': documents,
        'essentials': essentials,
        **_my_totals(trip.pk, request.user),
        'travelers': travelers,
        'ready_count': sum(1 for row in travelers if row['is_ready']),
        'travel_info': travel_info,
        'travel_info_form': travel_info_form,
        'flights': flights,
        'travel_tab_count': len(flights) + len(travel_info),
        'flight_form': flight_form,
        'checklist_form': checklist_form,
        'activity_form': activity_form,
        'itinerary_day_form': itinerary_day_form,
        'group_trip': group_trip,
        'active_tab': active_tab,
    })


@role_required(User.Role.TRAVELER)
@require_POST
def checklist_toggle(request, item_id):
    item = get_object_or_404(Checklist.objects.select_related('trip'), pk=item_id, trip__in=_accessible_trips(request.user))
    # Each traveler ticks their own copy of the item.
    removed, _ = ChecklistCheck.objects.filter(item=item, user=request.user).delete()
    if not removed:
        ChecklistCheck.objects.get_or_create(item=item, user=request.user)
    is_checked = not removed
    trip = item.trip
    totals = _my_totals(trip.pk, request.user)
    # The trip is Ready once every traveler has ticked every item; anything less puts it back to Planning.
    readiness = _readiness_rows(trip, request.user)
    everyone_ready = bool(readiness) and all(row['is_ready'] for row in readiness)
    if everyone_ready and trip.status == Trip.Status.PLANNING:
        trip.status = Trip.Status.READY
        trip.save(update_fields=('status',))
    elif not everyone_ready and trip.status == Trip.Status.READY:
        trip.status = Trip.Status.PLANNING
        trip.save(update_fields=('status',))
    if trip.is_group_trip:
        me = next((row for row in readiness if row['is_me']), None)
        if me and me['is_ready'] and is_checked:
            _notify_group(trip, 'A traveler is ready', f'{request.user.get_username()} has finished their checklist for {trip.destination}.', request.user.pk)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Background save from the trip page: send back fresh totals instead of reloading the page.
        me = next((row for row in readiness if row['is_me']), {'percent': 0, 'done': 0, 'total': 0, 'is_ready': False})
        return JsonResponse({
            'is_complete': is_checked, **totals,
            'trip_status': trip.status, 'trip_status_label': trip.get_status_display(),
            'my_percent': me['percent'], 'my_done': me['done'], 'my_total': me['total'], 'my_ready': me['is_ready'],
            'group_ready_count': sum(1 for row in readiness if row['is_ready']), 'group_size': len(readiness),
        })
    return redirect(f"{reverse('trip_detail', kwargs={'trip_id': trip.pk})}#preparation")


@role_required(User.Role.TRAVELER)
@require_POST
def checklist_quantity_update(request, item_id):
    item = get_object_or_404(Checklist.objects.select_related('trip'), pk=item_id, trip__in=_accessible_trips(request.user), is_document=False)
    previous = item.quantity
    form = ChecklistQuantityForm(request.POST, instance=item)
    is_background = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if form.is_valid():
        form.save()
        if is_background:
            return JsonResponse({'quantity': item.quantity})
        messages.success(request, f'Amount updated for {item.title}.')
    else:
        error = 'Enter an amount from 1 to 999.'  # one clear message for every invalid amount
        if is_background:
            return JsonResponse({'error': error, 'quantity': previous}, status=400)
        messages.error(request, error)
    return redirect(f"{reverse('trip_detail', kwargs={'trip_id': item.trip_id})}#preparation")


@role_required(User.Role.TRAVELER)
@require_POST
def trip_invite(request, trip_id):
    trip = get_object_or_404(Trip, pk=trip_id, owner=request.user)
    group_trip, created = GroupTrip.objects.get_or_create(trip=trip, defaults={'created_by': request.user})
    GroupMember.objects.get_or_create(
        group_trip=group_trip,
        user=request.user,
        defaults={'membership': GroupMember.Membership.ORGANIZER},
    )
    if created:
        messages.success(request, 'Group sharing is on. Your private trip remains invite-only.')
    return redirect('trip_detail', trip_id=trip.pk)


@role_required(User.Role.TRAVELER)
def trip_join(request, invite_code):
    group_trip = get_object_or_404(GroupTrip.objects.select_related('trip', 'created_by'), invite_code=invite_code)
    if request.method == 'POST':
        membership, created = GroupMember.objects.get_or_create(group_trip=group_trip, user=request.user)
        if created:
            _notify_group(group_trip.trip, 'A traveler joined your group', f'{request.user.get_username()} joined {group_trip.trip.destination}.', request.user.pk, kind='notify_member_joins')
            messages.success(request, f'You joined the trip to {group_trip.trip.destination}.')
        else:
            messages.info(request, 'You are already part of this trip.')
        return redirect('trip_detail', trip_id=group_trip.trip_id)
    return render(request, 'dashboard/join_trip.html', {'group_trip': group_trip})


@role_required(User.Role.TRAVELER)
def activity_list(request):
    cutoff = timezone.localdate() - timedelta(days=30)
    # Lazy cleanup keeps stale activities out even if the daily management command is not scheduled.
    # cache.add only succeeds once per day, so the DELETE doesn't run on every page view.
    if cache.add(f'activity-cleanup-{timezone.localdate()}', True, 60 * 60 * 24):
        Activity.objects.filter(day__date__lt=cutoff).delete()
    kind = request.GET.get('type', 'all')
    if kind not in ('all', 'log', 'notification'):
        kind = 'all'

    entries = []
    if kind in ('all', 'log'):
        activities = Activity.objects.filter(
            day__trip__in=_accessible_trips(request.user), day__date__gte=cutoff,
        ).select_related('day__trip')
        for activity in activities:
            when = datetime.combine(activity.day.date, activity.start_time or time.min)
            entries.append({'kind': 'log', 'when': when, 'has_time': bool(activity.start_time), 'item': activity})
    if kind in ('all', 'notification'):
        # Today's notifications live in the inbox; older ones are kept here.
        notifications = Notification.objects.filter(
            _notification_scope(request.user),
            created_at__date__lt=timezone.localdate(),
            created_at__date__gte=cutoff,
        ).select_related('trip')
        for notification in notifications:
            when = timezone.localtime(notification.created_at).replace(tzinfo=None)
            entries.append({'kind': 'notification', 'when': when, 'has_time': True, 'item': notification})

    entries.sort(key=lambda entry: entry['when'], reverse=True)
    page = Paginator(entries, 15).get_page(request.GET.get('page'))
    return render(request, 'dashboard/activities.html', {'page_obj': page, 'kind': kind})


@role_required(User.Role.TRAVELER)
def live_notification_count(request):
    day_notifications = Notification.objects.filter(
        _notification_scope(request.user),
        created_at__date=timezone.localdate(),
    ).select_related('trip').order_by('-created_at')
    notifications = [{
        'id': item.pk,
        'title': item.title,
        'message': item.message,
        'is_read': item.is_read,
        'time': timezone.localtime(item.created_at).strftime('%I:%M %p').lstrip('0') if item.created_at else '',
        'trip': item.trip.destination if item.trip_id else '',
        'can_mark_read': item.user_id == request.user.pk and not item.is_read,
        'mark_url': reverse('notification_mark_read', kwargs={'notification_id': item.pk}),
    } for item in day_notifications[:30]]
    unread_count = day_notifications.filter(is_read=False).count()
    return JsonResponse({'count': unread_count, 'notifications': notifications})


@role_required(User.Role.TRAVELER)
@require_POST
def notification_mark_read(request, notification_id):
    notification = get_object_or_404(
        Notification.objects.filter(user=request.user),
        pk=notification_id,
        created_at__date=timezone.localdate(),
    )
    notification.is_read = True
    notification.save(update_fields=('is_read',))
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'is_read': True})
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER', '')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect('activity_list')


@role_required(User.Role.ADMINISTRATOR)
def admin_dashboard(request):
    # Admin filtering is applied in the ORM before rendering; no full user table is loaded.
    query = request.GET.get('q', '').strip()
    role_filter = request.GET.get('role', '').strip()
    user_status = request.GET.get('user_status', '').strip()
    trip_status = request.GET.get('status', '').strip()
    users = User.objects.all().order_by('-date_joined')
    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query))
    if role_filter in User.Role.values:
        users = users.filter(role=role_filter)
    if user_status == 'active':
        users = users.filter(is_active=True)
    elif user_status == 'inactive':
        users = users.filter(is_active=False)

    trips = Trip.objects.select_related('owner').annotate(group_size=Count('group_trip__members', distinct=True)).order_by('start_date')
    if query:
        trips = trips.filter(Q(destination__icontains=query) | Q(owner__username__icontains=query) | Q(owner__email__icontains=query))
    if trip_status in Trip.Status.values:
        trips = trips.filter(status=trip_status)

    checklist_stats = Checklist.objects.aggregate(total=Count('id', distinct=True), complete=Count('id', distinct=True, filter=Q(checks__user=F('trip__owner'))))
    total_checklist = checklist_stats['total'] or 0
    complete_checklist = checklist_stats['complete'] or 0
    completion_rate = round(complete_checklist * 100 / total_checklist) if total_checklist else 0

    travel_form = TravelInfoForm(prefix='travel')
    notification_form = SystemNotificationForm(prefix='notice')
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save_travel_info':
            travel_form = TravelInfoForm(request.POST, prefix='travel')
            if travel_form.is_valid():
                travel_form.save()
                messages.success(request, 'Travel information saved.')
                return redirect('admin_dashboard')
        elif action == 'save_notification':
            notification_form = SystemNotificationForm(request.POST, prefix='notice')
            if notification_form.is_valid():
                notification_form.save()
                messages.success(request, 'System notification created.')
                return redirect('admin_dashboard')

    return render(request, 'dashboard/admin.html', {
        'total_users': User.objects.count(),
        'active_trips': Trip.objects.filter(status__in=(Trip.Status.PLANNING, Trip.Status.READY, Trip.Status.IN_PROGRESS)).count(),
        'completion_rate': completion_rate,
        'pending_notifications': Notification.objects.filter(is_read=False, user__isnull=False).count(),
        'users': users[:8],
        'trips': trips[:8],
        'travel_info_entries': TravelInfo.objects.select_related('trip')[:6],
        'notifications': Notification.objects.select_related('user', 'trip')[:6],
        'travel_form': travel_form,
        'notification_form': notification_form,
        'query': query,
        'role_filter': role_filter,
        'user_status': user_status,
        'trip_status': trip_status,
        'role_choices': User.Role.choices,
        'trip_status_choices': Trip.Status.choices,
    })
