from django import forms
from django.utils import timezone

from accounts.countries import COUNTRY_CHOICES

import re
from datetime import timedelta

from .models import Activity, Checklist, Flight, ItineraryDay, Notification, TravelInfo, Trip


class TripForm(forms.ModelForm):
    country = forms.ChoiceField(choices=COUNTRY_CHOICES, label='Country')
    has_ticket = forms.ChoiceField(
        choices=(('no', 'Not yet, I’ll add it later'), ('yes', 'Yes, I have a flight number')),
        initial='no', widget=forms.RadioSelect, label='Have you bought your plane ticket?',
    )
    flight_number = forms.CharField(
        required=False, max_length=10, label='Flight number',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. PR 102', 'autocomplete': 'off', 'autocapitalize': 'characters', 'spellcheck': 'false'}),
        help_text='Your outbound flight, as printed on your booking.',
    )
    flight_date = forms.DateField(
        required=False, label='Flight departure date',
        widget=forms.DateInput(attrs={'type': 'date'}),
        help_text='Leave blank to use the trip’s departure date.',
    )
    places = forms.CharField(
        required=False,
        label='Places to visit',
        help_text='Add one place per line. You can edit this list later.',
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Old Town\nCity museum'}),
    )
    generate_itinerary = forms.BooleanField(required=False, initial=True, label='Create a suggested day-by-day itinerary')

    class Meta:
        model = Trip
        fields = ('destination', 'country', 'start_date', 'end_date')
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            # data-min-from keeps the return picker from going earlier than the chosen departure.
            'end_date': forms.DateInput(attrs={'type': 'date', 'data-min-from': 'id_start_date'}),
        }
        labels = {'destination': 'City', 'country': 'Country'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate().isoformat()
        self.fields['start_date'].widget.attrs['min'] = today
        self.fields['end_date'].widget.attrs['min'] = today
        self.order_fields(['destination', 'country', 'start_date', 'end_date', 'has_ticket', 'flight_number', 'flight_date'])

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get('start_date')
        end_date = cleaned.get('end_date')
        # Only new trips are created through this form, so departure can't already be in the past.
        # (When editing, a trip may keep the past departure date it already has.)
        if start_date and start_date < timezone.localdate() and start_date != getattr(self, 'original_start', None):
            self.add_error('start_date', 'The departure date can’t be in the past.')
        if start_date and end_date and end_date < start_date:
            self.add_error('end_date', 'The return date must be on or after the departure date.')
        if start_date and end_date and cleaned.get('generate_itinerary') and (end_date - start_date).days > 30:
            self.add_error('end_date', 'Suggested itineraries can cover trips up to 31 days. You can still create a longer trip without suggestions.')
        self.flight = None
        if cleaned.get('has_ticket') == 'yes':
            self._clean_ticket(cleaned, start_date, end_date)
        return cleaned

    def _clean_ticket(self, cleaned, start_date, end_date):
        raw = cleaned.get('flight_number', '')
        if not raw:
            self.add_error('flight_number', 'Enter your flight number, or choose “Not yet”.')
            return
        try:
            carrier_code, number = parse_flight_number(raw)
        except forms.ValidationError as exc:
            self.add_error('flight_number', exc)
            return
        flight_date = cleaned.get('flight_date') or start_date
        if not flight_date:
            return
        # Flights can leave the day before the trip starts or land the day after it ends.
        if start_date and end_date and not (start_date - timedelta(days=1) <= flight_date <= end_date + timedelta(days=1)):
            self.add_error('flight_date', 'The flight date must be within a day of the trip dates.')
            return
        self.flight = (carrier_code, number, flight_date)


# Flights have their own section with live status, so notes no longer offer a Flight category.
NOTE_CATEGORY_CHOICES = [(v, l) for v, l in TravelInfo.Category.choices if v != TravelInfo.Category.FLIGHT]


class TripTravelInfoForm(forms.ModelForm):
    category = forms.ChoiceField(choices=NOTE_CATEGORY_CHOICES, initial=TravelInfo.Category.TRANSIT)

    class Meta:
        model = TravelInfo
        fields = ('category', 'title', 'details')
        widgets = {'details': forms.Textarea(attrs={'rows': 3})}


class CustomChecklistForm(forms.ModelForm):
    class Meta:
        model = Checklist
        fields = ('title', 'quantity')
        labels = {'title': 'Custom item', 'quantity': 'Amount'}
        widgets = {'quantity': forms.NumberInput(attrs={'min': 1, 'step': 1})}


class ChecklistRenameForm(forms.ModelForm):
    class Meta:
        model = Checklist
        fields = ('title',)


class ChecklistQuantityForm(forms.ModelForm):
    MAX_QUANTITY = 999

    class Meta:
        model = Checklist
        fields = ('quantity',)
        widgets = {'quantity': forms.NumberInput(attrs={'min': 1, 'max': 999, 'step': 1})}

    def clean_quantity(self):
        quantity = self.cleaned_data['quantity']
        if not 1 <= quantity <= self.MAX_QUANTITY:
            raise forms.ValidationError(f'Enter an amount from 1 to {self.MAX_QUANTITY}.')
        return quantity


class ActivityForm(forms.ModelForm):
    class Meta:
        model = Activity
        fields = ('title', 'start_time', 'location', 'notes')
        labels = {'title': 'Activity', 'start_time': 'Time (optional)', 'location': 'Place (optional)'}
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'e.g. Visit Senso-ji Temple'}),
            'start_time': forms.TimeInput(format='%H:%M:%S', attrs={'type': 'time', 'title': 'Leave empty for a flexible time'}),
            'location': forms.TextInput(attrs={'placeholder': 'e.g. Asakusa, Tokyo'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class ItineraryDayForm(forms.ModelForm):
    class Meta:
        model = ItineraryDay
        fields = ('date', 'title', 'notes')
        labels = {'title': 'Day title (optional)', 'notes': 'Notes (optional)'}
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'title': forms.TextInput(attrs={'placeholder': 'e.g. Arrival & old town'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Anything to remember for this day'}),
        }

    def __init__(self, trip, *args, **kwargs):
        self.trip = trip
        super().__init__(*args, **kwargs)
        # The picker only offers days inside the trip.
        self.fields['date'].widget.attrs.update({'min': trip.start_date.isoformat(), 'max': trip.end_date.isoformat()})

    def clean_date(self):
        selected_date = self.cleaned_data['date']
        if not self.trip.start_date <= selected_date <= self.trip.end_date:
            raise forms.ValidationError('Choose a date within this trip.')
        if ItineraryDay.objects.filter(trip=self.trip, date=selected_date).exists():
            raise forms.ValidationError('There is already an itinerary day for this date.')
        return selected_date


class ItineraryDayEditForm(forms.ModelForm):
    class Meta(ItineraryDayForm.Meta):
        fields = ('title', 'notes')


class TravelInfoForm(forms.ModelForm):
    category = forms.ChoiceField(choices=NOTE_CATEGORY_CHOICES, initial=TravelInfo.Category.TRANSIT)

    class Meta:
        model = TravelInfo
        fields = ('destination', 'category', 'title', 'details')
        widgets = {'details': forms.Textarea(attrs={'rows': 2})}


class SystemNotificationForm(forms.ModelForm):
    """A notice from the Wunderlust team: to every traveler (one shared row) or to one traveler."""
    AUDIENCE_ALL, AUDIENCE_ONE = 'all', 'one'
    audience = forms.ChoiceField(choices=((AUDIENCE_ALL, 'All travelers'), (AUDIENCE_ONE, 'One traveler')), initial=AUDIENCE_ALL, widget=forms.RadioSelect)
    recipient = forms.CharField(required=False, max_length=150, label='Traveler username', help_text='Only for a notice to one traveler.')

    class Meta:
        model = Notification
        fields = ('title', 'message')
        widgets = {'message': forms.Textarea(attrs={'rows': 3})}

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('audience') == self.AUDIENCE_ONE:
            from accounts.social import discoverable_users
            name = (cleaned.get('recipient') or '').strip().lstrip('@')
            person = discoverable_users().filter(username__iexact=name).only('pk').first() if name else None
            if person is None:
                self.add_error('recipient', 'Enter the username of an active traveler.')
            cleaned['recipient_user'] = person
        return cleaned

    def save(self, commit=True):
        notice = super().save(commit=False)
        notice.user = self.cleaned_data.get('recipient_user') if self.cleaned_data.get('audience') == self.AUDIENCE_ONE else None
        if commit:
            notice.save()
        return notice


FLIGHT_NUMBER_RE = re.compile(r'^([A-Z0-9]{2})\s*-?\s*(\d{1,4})([A-Z]?)$')


def parse_flight_number(raw):
    """'pr 0102' -> ('PR', '102'). Raises ValidationError for anything that isn't an IATA flight number."""
    match = FLIGHT_NUMBER_RE.match(raw.upper().strip())
    if not match:
        raise forms.ValidationError('Enter a flight number like PR 102 or 5J560: the 2-character airline code, then up to 4 digits.')
    code, digits, suffix = match.groups()
    if code.isdigit():
        raise forms.ValidationError('The airline code needs at least one letter, e.g. PR or 5J.')
    # Leading zeros aren't part of the flight number (PR0102 is PR102).
    return code, f'{int(digits)}{suffix}'


class FlightForm(forms.ModelForm):
    flight_number = forms.CharField(
        max_length=10, label='Flight number',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. PR 102', 'autocomplete': 'off', 'autocapitalize': 'characters', 'spellcheck': 'false'}),
        help_text='Airline code plus number, as printed on your booking.',
    )

    class Meta:
        model = Flight
        fields = ('leg', 'flight_date')
        labels = {'leg': 'Flight', 'flight_date': 'Departure date'}
        widgets = {'flight_date': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, trip, *args, **kwargs):
        self.trip = trip
        super().__init__(*args, **kwargs)
        self.order_fields(['flight_number', 'flight_date', 'leg'])
        # Flights can leave the day before the trip starts or land the day after it ends.
        self.earliest = trip.start_date - timedelta(days=1)
        self.latest = trip.end_date + timedelta(days=1)
        self.fields['flight_date'].widget.attrs.update({'min': self.earliest.isoformat(), 'max': self.latest.isoformat()})

    def clean_flight_number(self):
        self.carrier_code, self.number = parse_flight_number(self.cleaned_data['flight_number'])
        return f'{self.carrier_code}{self.number}'

    def clean_flight_date(self):
        flight_date = self.cleaned_data['flight_date']
        if not self.earliest <= flight_date <= self.latest:
            raise forms.ValidationError(f'Choose a date between {self.earliest:%b} {self.earliest.day} and {self.latest:%b} {self.latest.day}, {self.latest.year}.')
        return flight_date

    def clean(self):
        cleaned = super().clean()
        if 'flight_number' in cleaned and cleaned.get('flight_date') and Flight.objects.filter(
            trip=self.trip, carrier_code=self.carrier_code, number=self.number, flight_date=cleaned['flight_date'],
        ).exists():
            self.add_error('flight_number', 'This flight is already on the trip for that date.')
        return cleaned

    def save(self, commit=True):
        from .airlines import AIRLINE_BY_CODE
        flight = super().save(commit=False)
        flight.trip = self.trip
        flight.carrier_code = self.carrier_code
        flight.number = self.number
        flight.airline_name = AIRLINE_BY_CODE.get(self.carrier_code, '')
        if commit:
            flight.save()
        return flight


class TripEditForm(TripForm):
    """Edit an existing trip. Same fields as creating one, minus the one-time setup options,
    plus the status the traveler controls (Planning / Ready / Cancelled)."""
    EDITABLE_STATUSES = (Trip.Status.PLANNING, Trip.Status.READY, Trip.Status.CANCELLED)

    status = forms.ChoiceField(label='Status')

    class Meta(TripForm.Meta):
        fields = ('destination', 'country', 'start_date', 'end_date')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('places', 'generate_itinerary', 'has_ticket', 'flight_number', 'flight_date'):
            del self.fields[name]
        trip = self.instance
        self.original_start = trip.start_date
        # In-progress / completed come from the dates; show the current one but only offer the editable ones.
        choices = [(value, label) for value, label in Trip.Status.choices if value in self.EDITABLE_STATUSES]
        if trip.status not in self.EDITABLE_STATUSES:
            choices.insert(0, (trip.status, f'{trip.get_status_display()} (set by dates)'))
        self.fields['status'].choices = choices
        self.fields['status'].initial = trip.status
        self.fields['status'].help_text = 'In progress and Completed are set automatically from the dates.'
        # A trip that already started may keep its past departure date.
        earliest = min(self.original_start, timezone.localdate()).isoformat()
        self.fields['start_date'].widget.attrs['min'] = earliest
        self.fields['end_date'].widget.attrs['min'] = earliest
        self.fields['end_date'].help_text = 'Shortening the trip removes itinerary days outside the new dates.'
        self.order_fields(['destination', 'country', 'start_date', 'end_date', 'status'])

    def save(self, commit=True):
        trip = super().save(commit=False)
        chosen = self.cleaned_data['status']
        if chosen in self.EDITABLE_STATUSES:
            trip.status = chosen
        trip.status = trip.status_for_dates()
        if commit:
            trip.save()
        return trip
