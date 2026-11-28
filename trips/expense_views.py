from django.contrib import messages
from django.http import Http404
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import User

from .decorators import role_required
from .balances import trip_balances
from .expense_forms import ExpenseForm, SettlementForm
from .models import Trip, trip_travelers
from .views import _accessible_trips, _notify_group


def _expense_redirect(trip):
    return redirect(f"{reverse('trip_detail', args=[trip.pk])}?tab=expenses#panel-expenses")


def _ledger_trip(request, trip_id):
    trips = _accessible_trips(request.user).values('pk')
    queryset = Trip.objects.filter(pk__in=trips)
    if request.method == 'POST':
        queryset = queryset.select_for_update()
    return get_object_or_404(queryset, pk=trip_id)


@role_required(User.Role.TRAVELER)
@transaction.atomic
def expense_save(request, trip_id, expense_id=None):
    trip = _ledger_trip(request, trip_id)
    expense = None
    if expense_id is not None:
        allowed = trip.expenses.all() if trip.owner_id == request.user.pk else trip.expenses.filter(paid_by=request.user)
        expense = get_object_or_404(allowed, pk=expense_id)
    form = ExpenseForm(trip, request.POST if request.method == 'POST' else None, viewer=request.user, instance=expense)
    if request.method == 'POST' and form.is_valid():
        expense = form.save_for(request.user)
        verb = 'edited' if expense_id else 'added'
        _notify_group(trip, 'Trip expenses updated', f'{request.user.username} {verb} the expense {expense.title}.', request.user.pk)
        return _expense_redirect(trip)
    return render(request, 'dashboard/expense_form.html', {'trip': trip, 'form': form, 'expense': expense})


@role_required(User.Role.TRAVELER)
@require_POST
@transaction.atomic
def expense_delete(request, trip_id, expense_id):
    trip = _ledger_trip(request, trip_id)
    allowed = trip.expenses.all() if trip.owner_id == request.user.pk else trip.expenses.filter(paid_by=request.user)
    expense = get_object_or_404(allowed, pk=expense_id)
    expense.delete()
    _notify_group(trip, 'Trip expenses updated', f'{request.user.username} deleted the expense {expense.title}.', request.user.pk)
    return _expense_redirect(trip)


@role_required(User.Role.TRAVELER)
@require_POST
@transaction.atomic
def settlement_add(request, trip_id):
    trip = _ledger_trip(request, trip_id)
    form = SettlementForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
        return _expense_redirect(trip)
    data = form.cleaned_data
    sender, recipient = data['from_user'], data['to_user']
    if request.user.pk not in (trip.owner_id, sender, recipient):
        raise Http404
    people = set(trip_balances([trip.pk])[trip.pk])
    people.update(user.pk for user, _ in trip_travelers(trip))
    if not {sender, recipient} <= people:
        raise Http404
    trip.settlements.create(from_user_id=sender, to_user_id=recipient, amount=data['amount'], created_by=request.user)
    _notify_group(trip, 'Trip expenses updated', f'{request.user.username} recorded a settlement.', request.user.pk)
    return _expense_redirect(trip)


@role_required(User.Role.TRAVELER)
@require_POST
@transaction.atomic
def settlement_delete(request, trip_id, settlement_id):
    trip = _ledger_trip(request, trip_id)
    settlements = trip.settlements.all()
    if request.user.pk != trip.owner_id:
        from django.db.models import Q
        settlements = settlements.filter(Q(from_user=request.user) | Q(to_user=request.user))
    settlement = get_object_or_404(settlements, pk=settlement_id)
    settlement.delete()
    _notify_group(trip, 'Trip expenses updated', f'{request.user.username} removed a settlement.', request.user.pk)
    return _expense_redirect(trip)
