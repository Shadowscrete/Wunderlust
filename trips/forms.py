from django import forms
from .models import Activity, Checklist, ItineraryDay, Notification, TravelInfo, Trip


class TripForm(forms.ModelForm):
    country = forms.CharField(max_length=100, label='Country')
    places = forms.CharField(
        required=False,
        label='Places to visit',
        help_text='Add one place per line. You can edit this list later.',
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Old Town\nCity museum'}),
    )
    generate_itinerary = forms.BooleanField(required=False, initial=True, label='Create a suggested day-by-day itinerary')

    class Meta:
        model = Trip
        fields = ('destination', 'country', 'airline', 'start_date', 'end_date')
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {'destination': 'City', 'country': 'Country', 'airline': 'Airline (optional)'}

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get('start_date')
        end_date = cleaned.get('end_date')
        if start_date and end_date and end_date < start_date:
            self.add_error('end_date', 'The return date must be on or after the departure date.')
        if start_date and end_date and cleaned.get('generate_itinerary') and (end_date - start_date).days > 30:
            self.add_error('end_date', 'Suggested itineraries can cover trips up to 31 days. You can still create a longer trip without suggestions.')
        return cleaned


class TripTravelInfoForm(forms.ModelForm):
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


class ChecklistQuantityForm(forms.ModelForm):
    class Meta:
        model = Checklist
        fields = ('quantity',)
        widgets = {'quantity': forms.NumberInput(attrs={'min': 1, 'step': 1})}


class ActivityForm(forms.ModelForm):
    class Meta:
        model = Activity
        fields = ('title', 'start_time', 'location', 'notes')
        widgets = {
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class ItineraryDayForm(forms.ModelForm):
    class Meta:
        model = ItineraryDay
        fields = ('date', 'title', 'notes')
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, trip, *args, **kwargs):
        self.trip = trip
        super().__init__(*args, **kwargs)

    def clean_date(self):
        selected_date = self.cleaned_data['date']
        if not self.trip.start_date <= selected_date <= self.trip.end_date:
            raise forms.ValidationError('Choose a date within this trip.')
        if ItineraryDay.objects.filter(trip=self.trip, date=selected_date).exists():
            raise forms.ValidationError('There is already an itinerary day for this date.')
        return selected_date


class TravelInfoForm(forms.ModelForm):
    class Meta:
        model = TravelInfo
        fields = ('destination', 'category', 'title', 'details')
        widgets = {'details': forms.Textarea(attrs={'rows': 2})}


class SystemNotificationForm(forms.ModelForm):
    class Meta:
        model = Notification
        fields = ('title', 'message')
        widgets = {'message': forms.Textarea(attrs={'rows': 2})}
