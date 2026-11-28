from collections import defaultdict
from decimal import Decimal
from heapq import heapify, heappop, heappush

from django.db.models import Sum

from .models import Expense, ExpenseShare, Settlement

ZERO = Decimal('0.00')


def trip_balances(trip_ids, user_id=None):
    balances = defaultdict(lambda: defaultdict(lambda: ZERO))
    for queryset, trip_field, person_field, amount, sign in (
        (Expense.objects.all(), 'trip_id', 'paid_by_id', 'amount_in_trip_currency', 1),
        (ExpenseShare.objects.all(), 'expense__trip_id', 'user_id', 'amount_in_trip_currency', -1),
        (Settlement.objects.all(), 'trip_id', 'from_user_id', 'amount', 1),
        (Settlement.objects.all(), 'trip_id', 'to_user_id', 'amount', -1),
    ):
        queryset = queryset.filter(**{f'{trip_field}__in': trip_ids})
        if user_id is not None:
            queryset = queryset.filter(**{person_field: user_id})
        for trip_id, person_id, total in queryset.order_by().values_list(trip_field, person_field).annotate(total=Sum(amount)):
            balances[trip_id][person_id] += sign * total
    return balances


def suggested_transfers(balances):
    debtors = [(amount, pk or 0) for pk, amount in balances.items() if amount < 0]
    creditors = [(-amount, pk or 0) for pk, amount in balances.items() if amount > 0]
    heapify(debtors)
    heapify(creditors)
    while debtors and creditors:
        debt, debtor = heappop(debtors)
        credit, creditor = heappop(creditors)
        amount = min(-debt, -credit)
        yield debtor or None, creditor or None, amount
        if debt + amount < 0:
            heappush(debtors, (debt + amount, debtor))
        if credit + amount < 0:
            heappush(creditors, (credit + amount, creditor))
