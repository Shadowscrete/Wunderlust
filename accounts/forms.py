from datetime import timedelta

from django import forms
from django.utils import timezone
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model

from .countries import COUNTRY_CHOICES
from .models import Profile

User = get_user_model()

class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

class AboutMeForm(forms.Form):
    """Fills in missing profile details. Anything already saved is locked (disabled),
    so Django ignores any submitted value for it and keeps the stored one."""
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    username = forms.CharField(required=False, disabled=True)
    email = forms.EmailField(required=False)
    location = forms.ChoiceField(choices=COUNTRY_CHOICES, required=False, label='Country')
    birth_date = forms.DateField(required=False, label='Birthday', widget=forms.DateInput(attrs={'type': 'date'}))
    bio = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3, 'maxlength': 500}), max_length=500)

    USER_FIELDS = ('first_name', 'last_name', 'username', 'email')
    PROFILE_FIELDS = ('location', 'birth_date', 'bio')

    def __init__(self, *args, user, profile, **kwargs):
        self.user, self.profile = user, profile
        initial = {name: getattr(user, name) for name in self.USER_FIELDS}
        initial.update({name: getattr(profile, name) for name in self.PROFILE_FIELDS})
        super().__init__(*args, initial=initial, **kwargs)
        # Keep an older free-text location (saved before the dropdown) visible in the locked field.
        if initial['location'] and initial['location'] not in dict(COUNTRY_CHOICES):
            self.fields['location'].choices = [(initial['location'], initial['location'])] + COUNTRY_CHOICES
        # The date picker only offers past dates; clean_birth_date enforces it on the server too.
        yesterday = timezone.localdate() - timedelta(days=1)
        self.fields['birth_date'].widget.attrs.update({'max': yesterday.isoformat(), 'min': '1900-01-01'})
        for name, field in self.fields.items():
            # Country can always be changed; other saved details are locked (grayed out).
            if initial.get(name) and name != 'location':
                field.disabled = True
                field.widget.attrs['class'] = 'is-locked'

    @property
    def has_missing(self):
        return any(not field.disabled for field in self.fields.values())

    def clean_birth_date(self):
        birth_date = self.cleaned_data.get('birth_date')
        if birth_date and not self.fields['birth_date'].disabled:
            if birth_date >= timezone.localdate():
                raise forms.ValidationError('Your birthday must be a date in the past.')
            if birth_date.year < 1900:
                raise forms.ValidationError('Please enter a valid birthday.')
        return birth_date

    def clean_email(self):
        email = self.cleaned_data.get('email', '')
        if email and not self.fields['email'].disabled:
            if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
                raise forms.ValidationError('That email is already used by another account.')
        return email

    def save(self):
        user_changed, profile_changed = [], []
        for name, value in self.cleaned_data.items():
            if self.fields[name].disabled:
                continue
            if not value and name != 'location':
                continue
            target, changed = (self.user, user_changed) if name in self.USER_FIELDS else (self.profile, profile_changed)
            setattr(target, name, value)
            changed.append(name)
        if user_changed:
            self.user.save(update_fields=user_changed)
        if profile_changed:
            self.profile.save()


class DeleteAccountForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}), label='Confirm your password')

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data['password']
        if not self.user.check_password(password):
            raise forms.ValidationError('That password is incorrect.')
        return password


class AvatarForm(forms.Form):
    MAX_BYTES = 5 * 1024 * 1024
    avatar = forms.ImageField()

    def clean_avatar(self):
        image = self.cleaned_data['avatar']
        if image.size > self.MAX_BYTES:
            raise forms.ValidationError('Please choose an image under 5 MB.')
        return image

    def processed_file(self):
        """Center-crops to a square and shrinks to 400×400 JPEG, so pictures stay small and load fast."""
        from io import BytesIO
        from django.core.files.base import ContentFile
        from PIL import Image, ImageOps

        image = Image.open(self.cleaned_data['avatar'])
        image = ImageOps.exif_transpose(image).convert('RGB')
        image = ImageOps.fit(image, (400, 400), Image.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format='JPEG', quality=86, optimize=True)
        return ContentFile(buffer.getvalue(), name='avatar.jpg')


class AppearanceForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ('theme',)
        widgets = {'theme': forms.RadioSelect}


class NotificationPrefsForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ('notify_trip_updates', 'notify_member_joins', 'notify_system')
        help_texts = {
            'notify_trip_updates': 'When someone changes the itinerary, checklist or travel info on a trip you share.',
            'notify_member_joins': 'When a traveler joins one of your group trips.',
            'notify_system': 'Announcements and travel notices from the Wunderlust team.',
        }
