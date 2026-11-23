from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from .decorators import role_required
from .forms import ActivityForm, ChecklistQuantityForm, CustomChecklistForm, ItineraryDayForm, SystemNotificationForm, TravelInfoForm, TripForm, TripTravelInfoForm
from .models import Activity, Checklist, GroupMember, GroupTrip, ItineraryDay, Notification, TravelInfo, Trip, TripPlace
from .recommendations import ideas_for

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
    documents = checklist_items.filter(is_document=True)
    packing_items = checklist_items.filter(is_document=False)
    recent_activities = Activity.objects.filter(
        day__trip__in=trips,
        day__date__gte=timezone.localdate(),
    ).select_related('day__trip').order_by('day__date', 'start_time')[:6]
    group_memberships = GroupMember.objects.filter(user=request.user).select_related('group_trip__trip', 'group_trip__created_by')
    travel_info = TravelInfo.objects.filter(Q(trip__in=upcoming_trips) | Q(trip__isnull=True)).distinct()[:8]
    notifications = Notification.objects.filter(
        Q(user=request.user) | Q(user__isnull=True),
        created_at__date=timezone.localdate(),
    ).filter(Q(trip__in=trips) | Q(trip__isnull=True))[:8]
    return render(request, 'dashboard/traveler.html', {
        'trips': upcoming_trips[:5],
        'documents': documents,
        'packing_items': packing_items,
        'document_total': documents.count(),
        'document_done': documents.filter(is_complete=True).count(),
        'document_progress': round(documents.filter(is_complete=True).count() * 100 / documents.count()) if documents.exists() else 0,
        'packing_total': packing_items.count(),
        'packing_done': packing_items.filter(is_complete=True).count(),
        'packing_progress': round(packing_items.filter(is_complete=True).count() * 100 / packing_items.count()) if packing_items.exists() else 0,
        'activities': recent_activities,
        'group_memberships': group_memberships[:5],
        'travel_info': travel_info,
        'notifications': notifications,
        'today_notification_count': Notification.objects.filter(
            Q(user=request.user) | Q(user__isnull=True), created_at__date=timezone.localdate(), is_read=False
        ).count(),
    })


def _accessible_trips(user):
    return Trip.objects.filter(Q(owner=user) | Q(group_trip__members__user=user)).distinct()


def _notify_group(trip, title, message, exclude_user=None):
    group = getattr(trip, 'group_trip', None)
    recipients = set()
    if trip.owner_id != exclude_user:
        recipients.add(trip.owner_id)
    if group:
        recipients.update(group.members.exclude(user_id=exclude_user).values_list('user_id', flat=True))
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
    trips = _accessible_trips(request.user).select_related('owner').order_by('start_date')
    return render(request, 'dashboard/trip_list.html', {'trips': trips})


@role_required(User.Role.TRAVELER)
def preparation_overview(request):
    trips = _accessible_trips(request.user).annotate(
        checklist_total=Count('checklist_items'),
        checklist_done=Count('checklist_items', filter=Q(checklist_items__is_complete=True)),
        documents_total=Count('checklist_items', filter=Q(checklist_items__is_document=True)),
        documents_done=Count('checklist_items', filter=Q(checklist_items__is_document=True, checklist_items__is_complete=True)),
    ).order_by('start_date')
    return render(request, 'dashboard/preparation.html', {'trips': trips})


@role_required(User.Role.TRAVELER)
def travel_information_overview(request):
    trips = _accessible_trips(request.user)
    entries = TravelInfo.objects.filter(Q(trip__in=trips) | Q(trip__isnull=True)).select_related('trip').distinct()
    return render(request, 'dashboard/travel_information.html', {'entries': entries})


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


@role_required(User.Role.TRAVELER)
def trip_detail(request, trip_id):
    trip = get_object_or_404(_accessible_trips(request.user).select_related('owner'), pk=trip_id)
    checklist = trip.checklist_items.all()
    documents = checklist.filter(is_document=True)
    essentials = checklist.filter(is_document=False)
    travel_info_form = TripTravelInfoForm(prefix='info')
    checklist_form = CustomChecklistForm(prefix='item')
    activity_form = ActivityForm()
    itinerary_day_form = ItineraryDayForm(trip)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'add_travel_info':
            travel_info_form = TripTravelInfoForm(request.POST, prefix='info')
            if travel_info_form.is_valid():
                info = travel_info_form.save(commit=False)
                info.trip = trip
                info.destination = trip.destination
                info.save()
                _notify_group(trip, 'Travel information updated', f'{info.title} was added to {trip.destination}.', request.user.pk)
                messages.success(request, 'Travel information saved.')
                return redirect('trip_detail', trip_id=trip.pk)
        elif action == 'add_checklist_item':
            checklist_form = CustomChecklistForm(request.POST, prefix='item')
            if checklist_form.is_valid():
                item = checklist_form.save(commit=False)
                item.trip = trip
                item.is_custom = True
                item.save()
                _notify_group(trip, 'Preparation list updated', f'{item.title} was added to the checklist.', request.user.pk)
                messages.success(request, 'Custom item added.')
                return redirect('trip_detail', trip_id=trip.pk)
        elif action == 'add_activity':
            day = get_object_or_404(trip.itinerary_days, pk=request.POST.get('day_id'))
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
    group_trip = getattr(trip, 'group_trip', None)
    return render(request, 'dashboard/trip_detail.html', {
        'trip': trip,
        'days': days,
        'documents': documents,
        'essentials': essentials,
        'document_count': documents.count(),
        'document_done': documents.filter(is_complete=True).count(),
        'all_count': checklist.count(),
        'all_done': checklist.filter(is_complete=True).count(),
        'travel_info': trip.travel_info.all(),
        'travel_info_form': travel_info_form,
        'checklist_form': checklist_form,
        'activity_form': activity_form,
        'itinerary_day_form': itinerary_day_form,
        'group_trip': group_trip,
    })


@role_required(User.Role.TRAVELER)
@require_POST
def checklist_toggle(request, item_id):
    item = get_object_or_404(Checklist.objects.select_related('trip'), pk=item_id, trip__in=_accessible_trips(request.user))
    item.is_complete = not item.is_complete
    item.save(update_fields=('is_complete',))
    _notify_group(item.trip, 'Preparation list updated', f'{item.title} was marked {"ready" if item.is_complete else "not ready"}.', request.user.pk)
    return redirect('trip_detail', trip_id=item.trip_id)


@role_required(User.Role.TRAVELER)
@require_POST
def checklist_quantity_update(request, item_id):
    item = get_object_or_404(Checklist.objects.select_related('trip'), pk=item_id, trip__in=_accessible_trips(request.user), is_document=False)
    form = ChecklistQuantityForm(request.POST, instance=item)
    if form.is_valid():
        form.save()
        messages.success(request, f'Amount updated for {item.title}.')
    else:
        messages.error(request, 'Enter an amount of one or more.')
    return redirect('trip_detail', trip_id=item.trip_id)


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
            _notify_group(group_trip.trip, 'A traveler joined your group', f'{request.user.get_username()} joined {group_trip.trip.destination}.', request.user.pk)
            messages.success(request, f'You joined the trip to {group_trip.trip.destination}.')
        else:
            messages.info(request, 'You are already part of this trip.')
        return redirect('trip_detail', trip_id=group_trip.trip_id)
    return render(request, 'dashboard/join_trip.html', {'group_trip': group_trip})


@role_required(User.Role.TRAVELER)
def activity_list(request):
    cutoff = timezone.localdate() - timedelta(days=30)
    # Lazy cleanup keeps stale activities out even if the daily management command is not scheduled.
    Activity.objects.filter(day__date__lt=cutoff).delete()
    activities = Activity.objects.filter(day__trip__in=_accessible_trips(request.user), day__date__gte=cutoff).select_related('day__trip').order_by('day__date', 'start_time', 'pk')
    page = Paginator(activities, 10).get_page(request.GET.get('page'))
    return render(request, 'dashboard/activities.html', {'page_obj': page})


@role_required(User.Role.TRAVELER)
def notification_list(request):
    notifications = Notification.objects.filter(
        Q(user=request.user) | Q(user__isnull=True),
        created_at__date=timezone.localdate(),
    ).order_by('-created_at')
    return render(request, 'dashboard/notifications.html', {'notifications': notifications})


@role_required(User.Role.TRAVELER)
def live_notification_count(request):
    day_notifications = Notification.objects.filter(
        Q(user=request.user) | Q(user__isnull=True),
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
    return redirect('notification_list')


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

    checklist_stats = Checklist.objects.aggregate(total=Count('id'), complete=Count('id', filter=Q(is_complete=True)))
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
