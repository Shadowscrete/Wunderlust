from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import User

from .decorators import role_required
from .expense_forms import ExpenseForm
from .models import Trip
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
