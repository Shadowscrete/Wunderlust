from django.utils.http import url_has_allowed_host_and_scheme
from datetime import datetime, time, timedelta
from django.contrib import messages
from django.contrib.auth import get_user_model
from accounts.security import rate_limited
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from accounts.context_processors import get_user_prefs
from accounts.models import Profile

from .decorators import role_required
from .forms import ChecklistRenameForm, ItineraryDayEditForm, ActivityForm, FlightForm, TripEditForm, ChecklistQuantityForm, CustomChecklistForm, ItineraryDayForm, TripForm, TripTravelInfoForm
from .airline_marks import airline_mark
from .currencies import COUNTRY_CURRENCY
from .balances import ZERO, suggested_transfers, trip_balances
from .expense_forms import ExpenseForm
from .models import NotificationRead
from .models import Activity, Checklist, ChecklistCheck, Flight, GroupMember, GroupTrip, ItineraryDay, Notification, RemovedMember, TravelInfo, Trip, TripPlace
from .trends import CITIES, destination_trends
from .recommendations import ideas_for
from .flight_status import FlightLookupLimited, FlightStatusError, get_flight_status, is_trackable
from .models import create_trip_code, refresh_ready_status, trip_readiness
from accounts.social import avatar_url_for, initials_for

User = get_user_model()


@role_required(User.Role.TRAVELER)
@require_POST
def dismiss_walkthrough(request):
    User.objects.filter(pk=request.user.pk, walkthrough_pending=True).update(walkthrough_pending=False)
    return HttpResponse(status=204)


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
    travel_info = TravelInfo.objects.filter(Q(trip__in=upcoming_trips) | Q(trip__isnull=True)).exclude(category=TravelInfo.Category.FLIGHT).distinct()[:8]
    dashboard_trips = list(upcoming_trips[:5])
    balances = trip_balances([trip.pk for trip in dashboard_trips], request.user.pk)
    for trip in dashboard_trips:
        trip.expense_balance = balances[trip.pk][request.user.pk]
    return render(request, 'dashboard/traveler.html', {
        'trips': dashboard_trips,
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
        'today_notification_count': _today_unread(request.user).count(),
    })


def _accessible_trips(user):
    return Trip.objects.filter(Q(owner=user) | Q(group_trip__members__user=user)).distinct()


def _notification_scope(user):
    """Notifications a user should see: their own, plus system-wide notices unless they turned those off.
    Administrators only get their own (e.g. new reports); system notices are written for travelers."""
    if user.role == User.Role.TRAVELER and get_user_prefs(user)['notify_system']:
        return Q(user=user) | Q(user__isnull=True)
    return Q(user=user)


def _with_read_state(queryset, user):
    """Annotate `read_by_me`: own rows use is_read, shared notices use a per-user read marker."""
    return queryset.annotate(seen=Exists(NotificationRead.objects.filter(notification=OuterRef('pk'), user=user)))


def _is_read(item):
    return item.is_read if item.user_id else item.seen


def _notify_group(trip, title, message, exclude_user=None, kind='notify_trip_updates', *, retain_after_delete=False):
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
        Notification(user_id=user_id, trip=None if retain_after_delete else trip, title=title, message=message)
        for user_id in recipients
    ])


def _build_itinerary(trip, place_names):
    day_count = (trip.end_date - trip.start_date).days + 1
    def place_key(name):
        return ' '.join(name.casefold().split())

    places = {}
    for name in place_names:
        places.setdefault(place_key(name), name)
    requested = iter(places.values())
    seen = set(places)
    suggestions = []
    for title, location in ideas_for(trip.destination, trip.country):
        key = place_key(location or title)
        if key in seen or any(f' {place} ' in f' {place_key(title)} ' for place in places):
            continue
        seen.add(key)
        suggestions.append((title, location))
    remaining_ideas = iter(suggestions)
    for index in range(day_count):
        current_date = trip.start_date + timedelta(days=index)
        day = ItineraryDay.objects.create(
            trip=trip,
            date=current_date,
            title=f'Day {index + 1}',
            notes='',
        )
        selected_place = next(requested, None)
        if selected_place:
            Activity.objects.create(
                day=day,
                title=f'Explore {selected_place}',
                start_time='09:30',
                location=selected_place,
                notes='',
                is_recommended=True,
            )
        suggestion = next(remaining_ideas, None)
        if suggestion is None:
            continue
        idea, location = suggestion
        Activity.objects.create(
            day=day,
            title=idea,
            start_time='14:00',
            location=location,
            notes='Check opening times before you go.',
            is_recommended=True,
        )


@role_required(User.Role.TRAVELER)
def trip_list(request):
    code = ''
    error = ''
    if request.method == 'POST':
        code = request.POST.get('invite_code', '').strip().upper()
        if GroupTrip.objects.filter(invite_code=code).exists():
            return redirect('trip_join', invite_code=code)
        error = 'Trip code not found. Check the code with your organizer and try again.'
    # One query for the whole list: group info is joined and checklist counts are annotated,
    # instead of extra queries per trip card.
    trips = _accessible_trips(request.user).select_related('owner', 'group_trip').annotate(
        checklist_total=Count('checklist_items', distinct=True),
    ).order_by('start_date')
    return render(request, 'dashboard/trip_list.html', {'trips': trips, 'invite_code': code, 'code_error': error})


@role_required(User.Role.TRAVELER)
def trends(request):
    return render(request, 'dashboard/trends.html', destination_trends())


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
    destination = request.GET.get('destination')
    initial = {'destination': destination, 'country': CITIES[destination]} if destination in CITIES else None
    form = TripForm(request.POST if request.method == 'POST' else None, initial=initial)
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
            if form.flight:
                from .airlines import AIRLINE_BY_CODE
                carrier_code, number, flight_date = form.flight
                Flight.objects.create(
                    trip=trip, carrier_code=carrier_code, number=number, flight_date=flight_date,
                    leg=Flight.Leg.OUTBOUND, airline_name=AIRLINE_BY_CODE.get(carrier_code, ''), added_by=request.user,
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
@transaction.atomic
def trip_edit(request, trip_id):
    trip = get_object_or_404(Trip.objects.select_for_update() if request.method == 'POST' else Trip,
                            pk=trip_id, owner=request.user)
    form = TripEditForm(request.POST or None, instance=trip)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            trip = form.save()
            # Itinerary days outside the new dates no longer belong to the trip.
            existing = set(trip.itinerary_days.values_list('date', flat=True))
            _, deleted = trip.itinerary_days.exclude(date__range=(trip.start_date, trip.end_date)).delete()
            removed = deleted.get(ItineraryDay._meta.label, 0)
            missing = []
            if existing:
                for offset in range((trip.end_date - trip.start_date).days + 1):
                    date = trip.start_date + timedelta(days=offset)
                    if date not in existing:
                        missing.append(ItineraryDay(trip=trip, date=date))
                ItineraryDay.objects.bulk_create(missing)
        _notify_group(trip, 'Trip details updated', f'{request.user.get_username()} updated the trip to {trip.destination}.', request.user.pk)
        messages.success(request, f'Trip updated. Itinerary days added: {len(missing)}. Removed: {removed}.')
        return redirect('trip_detail', trip_id=trip.pk)
    return render(request, 'dashboard/trip_form.html', {'form': form, 'trip': trip, 'editing': True, 'destination_currencies': COUNTRY_CURRENCY})


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
def flight_status(request, trip_id, flight_id):
    trip = get_object_or_404(_accessible_trips(request.user), pk=trip_id)
    flight = get_object_or_404(trip.flights, pk=flight_id)
    if not is_trackable(flight):
        return JsonResponse({'ok': True, 'tracked': False, 'message': 'Live status is available around the day of the flight.'})
    try:
        status = get_flight_status(flight, rate_limit=lambda: rate_limited(request, 'flight-status', limit=20, window=86400))
    except FlightLookupLimited as exc:
        return JsonResponse({'ok': False, 'message': str(exc)}, status=429)
    except FlightStatusError as exc:
        return JsonResponse({'ok': False, 'message': str(exc)}, status=502)
    if status is None:
        return JsonResponse({'ok': True, 'tracked': True, 'found': False, 'message': 'No live data for this flight yet.'})
    return JsonResponse({'ok': True, 'tracked': True, 'found': True, 'status': status})


@role_required(User.Role.TRAVELER)
def trip_detail(request, trip_id):
    trip = get_object_or_404(_accessible_trips(request.user).select_related('owner'), pk=trip_id)
    checklist = _with_my_ticks(trip.checklist_items.all(), request.user)
    documents = checklist.filter(is_document=True)
    essentials = checklist.filter(is_document=False)
    travel_info_form = TripTravelInfoForm(prefix='info')
    checklist_form = CustomChecklistForm(prefix='item')
    submitted_day_id = None
    bound_edit = None
    itinerary_day_form = ItineraryDayForm(trip)
    flight_form = FlightForm(trip, prefix='flight')
    active_tab = 'expenses' if request.GET.get('tab') == 'expenses' else 'overview'
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
            _notify_group(trip, 'Flight removed', f'{request.user.username} removed {flight.flight_number} from {trip.destination}.', request.user.pk)
            return redirect(f"{reverse('trip_detail', kwargs={'trip_id': trip.pk})}#travel-info")
        elif action in ('edit_travel_info', 'delete_travel_info'):
            info = get_object_or_404(trip.travel_info.exclude(category=TravelInfo.Category.FLIGHT), pk=_post_id(request, 'info_id'))
            if action == 'delete_travel_info':
                with transaction.atomic():
                    info.delete()
                    _notify_group(trip, 'Travel information updated', f'{request.user.username} removed {info.title} from the trip notes.', request.user.pk)
                return redirect(f"{reverse('trip_detail', args=[trip.pk])}#travel-info")
            form = TripTravelInfoForm(request.POST, instance=info, prefix=f'note-{info.pk}')
            if form.is_valid():
                form.save(commit=False).save(update_fields=['title', 'category', 'details', 'updated_at'])
                _notify_group(trip, 'Travel information updated', f'{request.user.username} edited {info.title} in the trip notes.', request.user.pk)
                return redirect(f"{reverse('trip_detail', args=[trip.pk])}#travel-info")
            bound_edit = form
            active_tab = 'travel-info'
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
        elif action == 'rename_checklist_item':
            item = get_object_or_404(trip.checklist_items, pk=_post_id(request, 'item_id'), is_custom=True, is_mandatory=False)
            form = ChecklistRenameForm(request.POST, instance=item, prefix=f'checklist-{item.pk}')
            if form.is_valid():
                form.save(commit=False).save(update_fields=['title'])
                _notify_group(trip, 'Preparation list updated', f'{request.user.username} renamed a checklist item to {item.title}.', request.user.pk)
                return redirect(f"{reverse('trip_detail', args=[trip.pk])}#preparation")
            bound_edit = form
            active_tab = 'preparation'
        elif action == 'add_checklist_item':
            checklist_form = CustomChecklistForm(request.POST, prefix='item')
            active_tab = 'preparation'
            if checklist_form.is_valid():
                item = checklist_form.save(commit=False)
                item.trip = trip
                item.is_custom = True
                item.save()
                refresh_ready_status(trip)
                _notify_group(trip, 'Preparation list updated', f'{item.title} was added to the checklist.', request.user.pk)
                messages.success(request, 'Custom item added.')
                return redirect(f"{reverse('trip_detail', kwargs={'trip_id': trip.pk})}#preparation")
        elif action == 'edit_activity':
            activity = get_object_or_404(Activity, pk=_post_id(request, 'activity_id'), day__trip=trip)
            form = ActivityForm(request.POST, instance=activity, prefix=f'activity-{activity.pk}')
            if form.is_valid():
                activity = form.save(commit=False)
                activity.is_recommended = False
                activity.save(update_fields=['title', 'start_time', 'location', 'notes', 'is_recommended'])
                _notify_group(trip, 'Itinerary updated', f'{request.user.username} edited {activity.title} in the itinerary.', request.user.pk)
                return redirect('trip_detail', trip_id=trip.pk)
            bound_edit = form
        elif action == 'add_activity':
            day = get_object_or_404(trip.itinerary_days, pk=_post_id(request, 'day_id'))
            submitted_day_id = day.pk
            activity_form = ActivityForm(request.POST, auto_id=f'id_day{day.pk}_%s')
            if activity_form.is_valid():
                activity = activity_form.save(commit=False)
                activity.day = day
                activity.save()
                _notify_group(trip, 'Itinerary updated', f'{activity.title} was added to {trip.destination}.', request.user.pk)
                messages.success(request, 'Activity added to the itinerary.')
                return redirect('trip_detail', trip_id=trip.pk)
        elif action in ('remove_activity', 'keep_activity'):
            activity = get_object_or_404(Activity.objects.filter(day__trip=trip), pk=_post_id(request, 'activity_id'))
            if action == 'keep_activity':
                activity.is_recommended = False  # now part of the traveler's own plan
                activity.save(update_fields=['is_recommended'])
                messages.success(request, f'{activity.title} is now part of your plan.')
            else:
                messages.success(request, f'{activity.title} was removed from the itinerary.')
                activity.delete()
                _notify_group(trip, 'Itinerary updated', f'{request.user.username} removed {activity.title} from the itinerary.', request.user.pk)
            return redirect('trip_detail', trip_id=trip.pk)
        elif action == 'edit_itinerary_day':
            day = get_object_or_404(trip.itinerary_days, pk=_post_id(request, 'day_id'))
            form = ItineraryDayEditForm(request.POST, instance=day, prefix=f'day-{day.pk}')
            if form.is_valid():
                form.save(commit=False).save(update_fields=['title', 'notes'])
                _notify_group(trip, 'Itinerary updated', f'{request.user.username} edited the itinerary day for {day.date:%b %d}.', request.user.pk)
                return redirect('trip_detail', trip_id=trip.pk)
            bound_edit = form
        elif action == 'delete_itinerary_day':
            day = get_object_or_404(trip.itinerary_days, pk=_post_id(request, 'day_id'))
            with transaction.atomic():
                day.delete()
                _notify_group(trip, 'Itinerary updated', f'{request.user.username} removed the itinerary day for {day.date:%b %d}.', request.user.pk)
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
    for day in days:
        prefix = f'day-{day.pk}'
        day.edit_form = bound_edit if bound_edit and bound_edit.prefix == prefix else ItineraryDayEditForm(instance=day, prefix=prefix)
        for activity in day.activities.all():
            prefix = f'activity-{activity.pk}'
            activity.edit_form = bound_edit if bound_edit and bound_edit.prefix == prefix else ActivityForm(instance=activity, prefix=prefix)
        day.activity_form = activity_form if day.pk == submitted_day_id else ActivityForm(auto_id=f'id_day{day.pk}_%s')
    for item in [*documents, *essentials]:
        if item.is_custom and not item.is_mandatory:
            prefix = f'checklist-{item.pk}'
            item.edit_form = bound_edit if bound_edit and bound_edit.prefix == prefix else ChecklistRenameForm(instance=item, prefix=prefix)
    travelers = _readiness_rows(trip, request.user)
    balances = trip_balances([trip.pk])[trip.pk]
    for row in travelers:
        row['expense_balance'] = balances.get(row['user'].pk, ZERO)
    group_trip = getattr(trip, 'group_trip', None)
    flights = list(trip.flights.all())
    for flight in flights:
        flight.mark = airline_mark(flight.carrier_code, flight.airline_name)
    travel_info = list(trip.travel_info.exclude(category=TravelInfo.Category.FLIGHT))
    for info in travel_info:
        prefix = f'note-{info.pk}'
        info.edit_form = bound_edit if bound_edit and bound_edit.prefix == prefix else TripTravelInfoForm(instance=info, prefix=prefix)
    current = {row['user'].pk: row['user'].username for row in travelers}
    former = User.objects.in_bulk(pk for pk in balances if pk is not None and pk not in current)

    def traveler_label(pk):
        if pk in current:
            return current[pk]
        if pk in former:
            return f'{former[pk].username} (left)'
        return 'Deleted traveler'

    expense_page = Paginator(trip.expenses.prefetch_related('shares'), 25).get_page(request.GET.get('expense_page'))
    for expense in expense_page:
        expense.payer_label = traveler_label(expense.paid_by_id)
        expense.split_rows = [
            (traveler_label(share.user_id), share.amount_in_trip_currency)
            for share in expense.shares.all()
        ]
    transfers = [
        {'sender': sender, 'recipient': recipient, 'sender_name': traveler_label(sender),
         'recipient_name': traveler_label(recipient), 'amount': amount,
         'can_record': sender is not None and recipient is not None and request.user.pk in (trip.owner_id, sender, recipient)}
        for sender, recipient, amount in suggested_transfers(balances)
    ]
    settlements = list(trip.settlements.order_by('-created_at', '-pk'))
    for settlement in settlements:
        settlement.sender_label = traveler_label(settlement.from_user_id)
        settlement.recipient_label = traveler_label(settlement.to_user_id)
    return render(request, 'dashboard/trip_detail.html', {
        'show_shared_expenses': len(current) > 1 or bool(former) or bool(settlements) or bool(transfers),
        'expense_rows': [(traveler_label(pk), balances.get(pk, ZERO)) for pk in [*current, *(pk for pk in balances if pk not in current)]],
        'expense_page': expense_page,
        'expense_total': trip.expenses.aggregate(total=Sum('amount_in_trip_currency', default=ZERO))['total'],
        'expense_form': ExpenseForm(trip, viewer=request.user, travelers=[(row['user'], row['role']) for row in travelers]),
        'transfers': transfers,
        'settlements': settlements,
        'trip': trip,
        'days': days,
        'documents': documents,
        'essentials': essentials,
        **_my_totals(trip.pk, request.user),
        'travelers': travelers,
        'expense_balance': balances.get(request.user.pk, ZERO),
        'expense_balance_magnitude': abs(balances.get(request.user.pk, ZERO)),
        'ready_count': sum(1 for row in travelers if row['is_ready']),
        'travel_info': travel_info,
        'travel_info_form': travel_info_form,
        'flights': flights,
        'travel_tab_count': len(flights) + len(travel_info),
        'flight_form': flight_form,
        'checklist_form': checklist_form,
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
    readiness = refresh_ready_status(trip)
    if trip.is_group_trip:
        me = next((row for row in readiness if row['user'].pk == request.user.pk), None)
        if me and me['is_ready'] and is_checked:
            _notify_group(trip, 'A traveler is ready', f'{request.user.get_username()} has finished their checklist for {trip.destination}.', request.user.pk)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Background save from the trip page: send back fresh totals instead of reloading the page.
        me = next((row for row in readiness if row['user'].pk == request.user.pk), {'percent': 0, 'done': 0, 'total': 0, 'is_ready': False})
        return JsonResponse({
            'is_complete': is_checked, **totals,
            'trip_status': trip.status, 'trip_status_label': trip.get_status_display(),
            'my_percent': me['percent'], 'my_done': me['done'], 'my_total': me['total'], 'my_ready': me['is_ready'],
            'group_ready_count': sum(1 for row in readiness if row['is_ready']), 'group_size': len(readiness),
        })
    return redirect(f"{reverse('trip_detail', kwargs={'trip_id': trip.pk})}#preparation")


@role_required(User.Role.TRAVELER)
@require_POST
def checklist_remove(request, item_id):
    item = get_object_or_404(
        Checklist, pk=item_id, trip__in=_accessible_trips(request.user), is_mandatory=False,
    )
    trip_id = item.trip_id
    item.delete()
    refresh_ready_status(item.trip)
    _notify_group(item.trip, 'Preparation list updated', f'{request.user.username} removed {item.title} from the checklist.', request.user.pk)
    messages.success(request, f'{item.title} removed from the preparation list.')
    return redirect(f"{reverse('trip_detail', args=[trip_id])}#preparation")


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
@require_POST
def trip_invite_reset(request, trip_id):
    trip = _owned_trip(request, trip_id)
    with transaction.atomic():
        group = get_object_or_404(GroupTrip.objects.select_for_update(), trip=trip)
        if request.POST.get('action') == 'off':
            if group.members.exclude(user=request.user).exists():
                messages.error(request, 'Remove the other members before turning group sharing off.')
            else:
                group.delete()
                messages.success(request, 'Group sharing is off.')
        else:
            previous_code = group.invite_code
            for _ in range(10):
                code = create_trip_code()
                if code == previous_code:
                    continue
                try:
                    with transaction.atomic():
                        group.invite_code = code
                        group.save(update_fields=['invite_code'])
                except IntegrityError:
                    if not GroupTrip.objects.filter(invite_code=code).exists():
                        raise
                else:
                    messages.success(request, 'Invite code reset.')
                    break
            else:
                messages.error(request, 'Could not reset the invite code. Please try again.')
    return redirect('trip_detail', trip_id=trip.pk)


@role_required(User.Role.TRAVELER)
@require_POST
def trip_leave(request, trip_id):
    trip = get_object_or_404(_accessible_trips(request.user), pk=trip_id)
    if trip.owner_id == request.user.pk:
        messages.error(request, 'The organizer cannot leave their trip.')
        return redirect('trip_detail', trip_id=trip.pk)
    with transaction.atomic():
        member = get_object_or_404(GroupMember, group_trip__trip=trip, user=request.user)
        ChecklistCheck.objects.filter(item__trip=trip, user=request.user).delete()
        member.delete()
        _notify_group(trip, 'A traveler left the group',
                      f'{request.user.username} left the trip to {trip.destination}.', request.user.pk)
        refresh_ready_status(trip)
    return redirect('trip_list')


@role_required(User.Role.TRAVELER)
@require_POST
def trip_remove_member(request, trip_id, user_id):
    """Only the trip's organizer (owner) can remove a traveler; the organizer can't remove themselves."""
    trip = _owned_trip(request, trip_id)
    group = getattr(trip, 'group_trip', None)
    member = get_object_or_404(GroupMember.objects.select_related('user'), group_trip=group, user_id=user_id) if group else None
    if member is None or member.user_id == trip.owner_id:
        messages.error(request, 'That traveler can’t be removed.')
        return redirect('trip_detail', trip_id=trip.pk)
    name = member.user.get_full_name() or member.user.get_username()
    with transaction.atomic():
        ChecklistCheck.objects.filter(item__trip=trip, user=member.user).delete()
        member.delete()
        refresh_ready_status(trip)
        RemovedMember.objects.get_or_create(group_trip=group, user=member.user)
        # trip=None: they no longer have access to the trip this notice is about.
        Notification.objects.create(user=member.user, title='Removed from a trip', message=f'The organizer removed you from the trip to {trip.destination}.')
    messages.success(request, f'{name} was removed from the trip.')
    return redirect('trip_detail', trip_id=trip.pk)


@role_required(User.Role.TRAVELER)
@transaction.atomic
def trip_join(request, invite_code):
    groups = GroupTrip.objects.select_related('trip', 'created_by')
    if request.method == 'POST':
        groups = groups.select_for_update(of=('self',))
    group_trip = get_object_or_404(groups, invite_code=invite_code)
    if group_trip.trip.owner_id != request.user.pk and RemovedMember.objects.filter(group_trip=group_trip, user=request.user).exists():
        messages.error(request, 'The organizer removed you from this trip, so you can’t rejoin with this link.')
        return redirect('trip_list')
    if request.method == 'POST':
        membership, created = GroupMember.objects.get_or_create(group_trip=group_trip, user=request.user)
        if created:
            refresh_ready_status(group_trip.trip)
            _notify_group(group_trip.trip, 'A traveler joined your group', f'{request.user.get_username()} joined {group_trip.trip.destination}.', request.user.pk, kind='notify_member_joins')
            messages.success(request, f'You joined the trip to {group_trip.trip.destination}.')
        else:
            messages.info(request, 'You are already part of this trip.')
        return redirect('trip_detail', trip_id=group_trip.trip_id)
    return render(request, 'dashboard/join_trip.html', {'group_trip': group_trip})


@role_required(User.Role.TRAVELER)
def activity_list(request):
    cutoff = timezone.localdate() - timedelta(days=30)
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
        for notification in _with_read_state(notifications, request.user):
            notification.is_read = _is_read(notification)
            when = timezone.localtime(notification.created_at).replace(tzinfo=None)
            entries.append({'kind': 'notification', 'when': when, 'has_time': True, 'item': notification})

    entries.sort(key=lambda entry: entry['when'], reverse=True)
    page = Paginator(entries, 15).get_page(request.GET.get('page'))
    return render(request, 'dashboard/activities.html', {'page_obj': page, 'kind': kind})


def _today_unread(user):
    return _with_read_state(Notification.objects.filter(
        _notification_scope(user), created_at__date=timezone.localdate(),
    ), user).filter(Q(user=user, is_read=False) | Q(user__isnull=True, seen=False))


@role_required(User.Role.TRAVELER, User.Role.ADMINISTRATOR)
def live_notification_count(request):
    unread = _today_unread(request.user)
    if request.method == 'POST':
        with transaction.atomic():
            unread.filter(user=request.user).update(is_read=True)
            shared_ids = unread.filter(user__isnull=True).values_list('pk', flat=True)
            NotificationRead.objects.bulk_create([
                NotificationRead(notification_id=pk, user=request.user) for pk in shared_ids
            ], ignore_conflicts=True)
    day_notifications = _with_read_state(Notification.objects.filter(
        _notification_scope(request.user),
        created_at__date=timezone.localdate(),
    ), request.user).select_related('trip').order_by('-created_at')
    notifications = []
    for item in day_notifications[:30]:
        is_read = _is_read(item)
        notifications.append({
            'id': item.pk,
            'title': item.title,
            'message': item.message,
            'is_read': is_read,
            'time': timezone.localtime(item.created_at).strftime('%I:%M %p').lstrip('0') if item.created_at else '',
            'trip': item.trip.destination if item.trip_id else '',
            'can_mark_read': not is_read,
            'mark_url': reverse('notification_mark_read', kwargs={'notification_id': item.pk}),
        })
    return JsonResponse({'count': unread.count(), 'notifications': notifications})


@role_required(User.Role.TRAVELER, User.Role.ADMINISTRATOR)
@require_POST
def notification_mark_read(request, notification_id):
    notification = get_object_or_404(
        Notification.objects.filter(_notification_scope(request.user)),
        pk=notification_id,
    )
    if notification.user_id:
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=('is_read',))
    else:
        NotificationRead.objects.get_or_create(notification=notification, user=request.user)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'is_read': True})
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER', '')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect('activity_list')
