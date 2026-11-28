from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.countries import COUNTRIES

from .currencies import COUNTRY_CURRENCY
from .models import Trip


class DestinationCurrencyTests(TestCase):
    def test_every_selectable_country_has_a_currency(self):
        self.assertEqual(set(COUNTRY_CURRENCY), set(COUNTRIES))

    def test_destination_sets_currency_and_foreign_expenses_convert_to_it(self):
        owner = get_user_model().objects.create_user('currency-planner')
        self.client.force_login(owner)
        date = timezone.localdate() + timedelta(days=2)
        data = {'destination': 'Manila', 'country': 'Philippines', 'start_date': date,
                'end_date': date, 'has_ticket': 'no'}
        self.assertEqual(self.client.post(reverse('trip_create'), data).status_code, 302)
        trip = Trip.objects.get(owner=owner)
        self.assertEqual(trip.currency, 'PHP')
        edit = reverse('trip_edit', args=[trip.pk])
        data.update(country='Japan', destination='Tokyo', status=trip.status, currency='PHP')
        self.assertEqual(self.client.post(edit, data).status_code, 302)
        trip.refresh_from_db()
        self.assertEqual(trip.currency, 'JPY')
        with patch('trips.expense_forms.exchange_rate', return_value=Decimal('150')) as rate:
            response = self.client.post(reverse('expense_add', args=[trip.pk]), {
                'title': 'Lunch', 'paid_by': owner.pk, 'amount': '10', 'currency': 'USD',
                'spent_on': date, 'split': 'equal', 'travelers': [owner.pk],
            })
        self.assertEqual(response.status_code, 302)
        rate.assert_called_once_with('USD', 'JPY')
        self.assertEqual(trip.expenses.get().amount_in_trip_currency, Decimal('1500'))


    def test_backfill_only_changes_usd_trips_without_ledger_history(self):
        from importlib import import_module
        from types import SimpleNamespace

        from django.apps import apps
        from django.db import connection

        migrate = import_module('trips.migrations.0008_default_currency_by_destination')
        owner = get_user_model().objects.create_user('currency-backfill')
        date = timezone.localdate()
        data = {'owner': owner, 'destination': 'Manila', 'country': 'Philippines',
                'start_date': date, 'end_date': date}
        empty = Trip.objects.create(**data)
        custom = Trip.objects.create(**data, currency='SGD')
        with_history = Trip.objects.create(**data)
        with_history.expenses.create(
            title='Lunch', paid_by=owner, amount=10, currency='USD', rate_to_trip=1,
            amount_in_trip_currency=10, spent_on=date, created_by=owner,
        )
        migrate.set_destination_currency(apps, SimpleNamespace(connection=connection))
        for trip, expected in ((empty, 'PHP'), (custom, 'SGD'), (with_history, 'USD')):
            trip.refresh_from_db()
            self.assertEqual(trip.currency, expected)


    def test_solo_expense_defaults_to_destination_currency_and_needs_no_split(self):
        owner = get_user_model().objects.create_user('solo-currency')
        self.client.force_login(owner)
        date = timezone.localdate()
        trip = Trip.objects.create(owner=owner, destination='Tokyo', country='Japan',
                                   start_date=date, end_date=date, currency='USD')
        detail = reverse('trip_detail', args=[trip.pk])
        self.assertNotContains(self.client.get(detail), 'Who owes whom')
        url = reverse('expense_add', args=[trip.pk])
        page = self.client.get(url)
        self.assertContains(page, 'name="payment_type"')
        self.assertContains(page, '<select name="currency"')
        self.assertContains(page, '<option value="JPY" selected>')
        self.assertContains(page, '<option value="XCG">')
        self.assertNotContains(page, 'name="manual_rate"')
        self.assertNotContains(page, 'name="split"')
        self.assertNotContains(page, 'name="travelers"')
        data = {'payment_type': 'Other', 'title': 'Luggage locker', 'paid_by': owner.pk,
                'amount': '1000', 'currency': 'JPY', 'spent_on': date}
        with patch('trips.expense_forms.exchange_rate', return_value=Decimal('0.0065')):
            self.assertEqual(self.client.post(url, data).status_code, 302)
        expense = trip.expenses.get()
        self.assertEqual(expense.title, 'Luggage locker')
        self.assertEqual(expense.currency, 'JPY')
        self.assertEqual(expense.shares.get(user=owner).amount_in_trip_currency, Decimal('6.50'))
        data.update(payment_type='Meals', currency='USD', title='')
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertTrue(trip.expenses.filter(title='Meals').exists())
