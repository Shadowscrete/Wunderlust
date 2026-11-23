from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.views.decorators.http import require_POST

from .context_processors import clear_user_prefs
from .sessions import active_devices, end_session, sign_out_other_sessions
from .models import UserSession
from .forms import AboutMeForm, AppearanceForm, AvatarForm, DeleteAccountForm, NotificationPrefsForm, RegisterForm
from .models import Profile


class WunderlustLoginView(LoginView):
    template_name = 'registration/login.html'
    next_page = 'login_success'
    # Already signed in (session still valid) -> skip the form, go to dashboard.
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.request.POST.get('remember_me') == 'on':
            self.request.session.set_expiry(60 * 60 * 24 * 14)
        else:
            self.request.session.set_expiry(0)
        return response

def register(request):
    if request.user.is_authenticated:
        return redirect('login_success')
    if request.method == 'POST':
        form = RegisterForm(request.POST)

        if form.is_valid():
            user = form.save()
            user.role = user.Role.TRAVELER
            user.save(update_fields=['role'])
            login(request, user)
            return redirect('traveler_dashboard')
    else:
        form = RegisterForm()

    return render(request, 'registration/register.html', {'form': form})


@login_required
def login_success(request):
    if request.user.role == request.user.Role.ADMINISTRATOR:
        return redirect('admin_dashboard')
    return redirect('traveler_dashboard')


@login_required
def profile(request):
    from django.db.models import Count, Q
    from django.utils import timezone
    from trips.models import Trip

    user = request.user
    profile_details = Profile.objects.filter(user=user).first() or Profile(user=user)
    if request.method == 'POST':
        about_form = AboutMeForm(request.POST, user=user, profile=profile_details)
        if about_form.is_valid():
            about_form.save()
            messages.success(request, 'Your profile has been updated.')
            return redirect('profile')
    else:
        about_form = AboutMeForm(user=user, profile=profile_details)
    context = {'profile_details': profile_details, 'about_form': about_form}

    if user.role == user.Role.TRAVELER:
        today = timezone.localdate()
        trips = Trip.objects.filter(Q(owner=user) | Q(group_trip__members__user=user)).distinct()
        # Every stat comes from a single aggregate query (the database is remote, so round-trips are what cost).
        context['stats'] = Trip.objects.filter(pk__in=trips.values('pk')).aggregate(
            total=Count('pk'),
            upcoming=Count('pk', filter=Q(end_date__gte=today) & ~Q(status=Trip.Status.CANCELLED)),
            completed=Count('pk', filter=Q(status=Trip.Status.COMPLETED) | (Q(end_date__lt=today) & ~Q(status=Trip.Status.CANCELLED))),
            countries=Count('country', distinct=True, filter=~Q(country='')),
            shared=Count('pk', filter=~Q(owner=user)),
        )
        context['upcoming_trips'] = trips.filter(end_date__gte=today).exclude(status=Trip.Status.CANCELLED).order_by('start_date')[:3]
    return render(request, 'accounts/profile.html', context)


@login_required
def account_settings(request):
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)
    appearance_form = AppearanceForm(instance=profile)
    notification_form = NotificationPrefsForm(instance=profile)
    password_form = PasswordChangeForm(user)
    delete_form = DeleteAccountForm(user=user)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'appearance':
            appearance_form = AppearanceForm(request.POST, instance=profile)
            if appearance_form.is_valid():
                appearance_form.save()
                clear_user_prefs(user.pk)
                messages.success(request, 'Appearance updated.')
                return redirect('account_settings')
        elif action == 'notifications':
            notification_form = NotificationPrefsForm(request.POST, instance=profile)
            if notification_form.is_valid():
                notification_form.save()
                clear_user_prefs(user.pk)
                messages.success(request, 'Notification preferences saved.')
                return redirect('account_settings')
        elif action == 'signout_device':
            row = UserSession.objects.filter(user=user, pk=request.POST.get('device')).first()
            if row and row.session_key != request.session.session_key:
                end_session(row.session_key)
                messages.success(request, 'That device has been signed out.')
            return redirect(f"{reverse('account_settings')}#devices")
        elif action == 'signout_others':
            count = sign_out_other_sessions(request)
            messages.success(request, f'Signed out of {count} other device{"s" if count != 1 else ""}.' if count else 'No other devices were signed in.')
            return redirect(f"{reverse('account_settings')}#devices")
        elif action == 'password':
            password_form = PasswordChangeForm(user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)  # stay signed in after the change
                messages.success(request, 'Your password has been changed.')
                return redirect('account_settings')
        elif action == 'delete':
            delete_form = DeleteAccountForm(request.POST, user=user)
            if delete_form.is_valid():
                logout(request)
                user.delete()
                return redirect('home')

    for field in password_form.fields.values():
        field.help_text = ''
    devices = active_devices(request)
    return render(request, 'accounts/settings.html', {
        'appearance_form': appearance_form,
        'notification_form': notification_form,
        'password_form': password_form,
        'delete_form': delete_form,
        'devices': devices,
        'other_device_count': sum(1 for d in devices if not d['is_current']),
    })

@login_required
def support(request):
    return render(request, 'accounts/support.html')



def _delete_file(storage, name):
    # A missing or briefly locked file (common on Windows) shouldn't break the request.
    try:
        storage.delete(name)
    except OSError:
        pass


@login_required
@require_POST
def update_avatar(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.POST.get('action') == 'remove':
        if profile.avatar:
            _delete_file(profile.avatar.storage, profile.avatar.name)
            profile.avatar = ''
            profile.save(update_fields=['avatar'])
            messages.success(request, 'Your profile picture has been removed.')
    else:
        form = AvatarForm(request.POST, request.FILES)
        if form.is_valid():
            old = profile.avatar.name if profile.avatar else None
            profile.avatar.save('avatar.jpg', form.processed_file(), save=False)
            profile.save(update_fields=['avatar'])
            if old:
                _delete_file(profile.avatar.storage, old)
            messages.success(request, 'Your profile picture has been updated.')
        else:
            messages.error(request, form.errors['avatar'][0])
    clear_user_prefs(request.user.pk)
    return redirect('profile')
