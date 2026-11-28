from decimal import Decimal, ROUND_HALF_UP

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .fx import CENT, ExchangeRateUnavailable, exchange_rate
from .models import Expense, ExpenseShare, trip_travelers


class ExpenseForm(forms.ModelForm):
    split = forms.ChoiceField(choices=[('equal', 'Equal split'), ('exact', 'Exact amounts')], initial='equal')
    travelers = forms.TypedMultipleChoiceField(coerce=int, required=False, widget=forms.CheckboxSelectMultiple)
    manual_rate = forms.DecimalField(max_digits=24, decimal_places=12, min_value=Decimal('0.000000000001'),
                                     required=False, help_text='Trip currency per unit of the expense currency.')

    class Meta:
        model = Expense
        fields = ('title', 'paid_by', 'amount', 'currency', 'spent_on', 'notes')
        widgets = {'spent_on': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
                   'notes': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, trip, *args, viewer, travelers=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.trip = trip
        people = {user.pk: user for user, _ in (trip_travelers(trip) if travelers is None else travelers)}
        shares = list(self.instance.shares.select_related('user')) if self.instance.pk else []
        for user in [self.instance.paid_by, *(share.user for share in shares)]:
            if user:
                people.setdefault(user.pk, user)
        self.fields['paid_by'] = forms.TypedChoiceField(
            label='Paid by', choices=[(pk, user.username) for pk, user in people.items()], coerce=int,
        )
        self.fields['travelers'].choices = self.fields['paid_by'].choices
        self.fields['currency'].help_text = 'Enter a three-letter currency code, such as USD or EUR.'
        self.initial.update({'paid_by': self.instance.paid_by_id or viewer.pk,
                             'spent_on': self.instance.spent_on or timezone.localdate(),
                             'currency': self.instance.currency or trip.currency,
                             'travelers': [share.user_id for share in shares] if shares else list(people),
                             'split': 'exact' if shares else 'equal'})
        existing = {share.user_id: share.amount_in_trip_currency for share in shares}
        self.exact_names = []
        for pk, user in people.items():
            name = f'exact_{pk}'
            self.exact_names.append((pk, name))
            self.fields[name] = forms.DecimalField(
                label=f'{user.username} ({trip.currency})', required=False, max_digits=12, decimal_places=2,
                min_value=0, initial=existing.get(pk),
            )

    def clean_currency(self):
        return self.cleaned_data['currency'].upper()

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        currency = cleaned['currency']
        if self.instance.pk and currency == self.instance.currency:
            rate = self.instance.rate_to_trip
        else:
            try:
                rate = exchange_rate(currency, self.trip.currency)
            except ExchangeRateUnavailable as exc:
                rate = cleaned['manual_rate']
                if rate is None:
                    self.add_error('manual_rate', str(exc))
                    return cleaned
        total = (cleaned['amount'] * rate).quantize(CENT, rounding=ROUND_HALF_UP)
        if not 0 < total < 10**10:
            raise ValidationError('The converted total must be between 0.01 and 9,999,999,999.99.')
        if cleaned['split'] == 'equal':
            users = sorted(set(cleaned['travelers']))
            if not users:
                self.add_error('travelers', 'Select at least one traveler.')
                return cleaned
            cents, remainder = divmod(int(total / CENT), len(users))
            self.allocations = {pk: (cents + (index < remainder)) * CENT for index, pk in enumerate(users)}
        else:
            self.allocations = {pk: cleaned[name] for pk, name in self.exact_names if cleaned[name] is not None}
            if sum(self.allocations.values()) != total:
                raise ValidationError(f'Exact shares must add up to {total} {self.trip.currency}.')
        self.rate, self.total = rate, total
        return cleaned

    def _post_clean(self):
        # The form uses integer choices so departed travelers can remain attached to historical expenses.
        if 'paid_by' in self.cleaned_data:
            self.instance.paid_by_id = self.cleaned_data.pop('paid_by')
        super()._post_clean()

    def save_for(self, viewer):
        expense = self.save(commit=False)
        expense.trip = self.trip
        expense.rate_to_trip = self.rate
        expense.amount_in_trip_currency = self.total
        if not expense.pk:
            expense.created_by = viewer
        expense.save()
        expense.shares.all().delete()
        ExpenseShare.objects.bulk_create([
            ExpenseShare(expense=expense, user_id=pk, amount_in_trip_currency=amount)
            for pk, amount in self.allocations.items()
        ])
        return expense


class SettlementForm(forms.Form):
    from_user = forms.IntegerField(min_value=1)
    to_user = forms.IntegerField(min_value=1)
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=CENT)

    def clean(self):
        cleaned = super().clean()
        if not self.errors and cleaned['from_user'] == cleaned['to_user']:
            raise ValidationError('Choose two different travelers.')
        return cleaned
