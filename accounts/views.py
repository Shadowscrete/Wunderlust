import logging

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
from .models import Follow, Report, UserSession
from .forms import AboutMeForm, AppearanceForm, AvatarForm, DeleteAccountForm, NotificationPrefsForm, RegisterForm, ReportForm
from .social import avatar_url_for, connection_sets, discoverable_users, initials_for, notify_follow, relationship
from .models import Profile

logger = logging.getLogger(__name__)


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
            device_id = request.POST.get('device', '')
            row = UserSession.objects.filter(user=user, pk=int(device_id)).first() if device_id.isdigit() else None
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
    except Exception:  # local disk (OSError) or cloud storage (network/API errors)
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
            try:
                profile.avatar.save('avatar.jpg', form.processed_file(), save=False)
            except Exception:
                # Storage unreachable or misconfigured: keep the old picture, tell the user, log details for Vercel.
                logger.exception('Profile picture upload failed for user %s', request.user.pk)
                messages.error(request, 'We couldn’t save your picture right now. Please try again in a moment.')
                return redirect('profile')
            profile.save(update_fields=['avatar'])
            if old:
                _delete_file(profile.avatar.storage, old)
            messages.success(request, 'Your profile picture has been updated.')
        else:
            messages.error(request, form.errors['avatar'][0])
    clear_user_prefs(request.user.pk)
    return redirect('profile')



# ======================= Social: search, profiles, follow, report, friends =======================
from django.db import IntegrityError, transaction  # noqa: E402
from django.db.models import Q  # noqa: E402
from django.http import JsonResponse  # noqa: E402
from django.shortcuts import get_object_or_404  # noqa: E402

from trips.decorators import role_required  # noqa: E402
from .models import User  # noqa: E402

TRAVELER = User.Role.TRAVELER


@role_required(TRAVELER)
def user_search(request):
    """Live search for the header: up to 8 travelers matching every word typed."""
    query = ' '.join(request.GET.get('q', '').split())[:60]
    if len(query) < 2:
        return JsonResponse({'results': []})
    people = discoverable_users().exclude(pk=request.user.pk)
    for term in query.split():
        people = people.filter(Q(username__icontains=term) | Q(first_name__icontains=term) | Q(last_name__icontains=term))
    people = list(people.select_related('profile').order_by('username')[:8])
    following, followers = connection_sets(request.user)
    return JsonResponse({'results': [{
        'username': person.get_username(),
        'name': person.get_full_name(),
        'initials': initials_for(person),
        'avatar_url': avatar_url_for(person),
        'url': reverse('public_profile', kwargs={'username': person.get_username()}),
        'is_friend': person.pk in following and person.pk in followers,
        'follows_you': person.pk in followers and person.pk not in following,
    } for person in people]})


def _discoverable_or_404(username):
    return get_object_or_404(discoverable_users().select_related('profile'), username__iexact=username)


@role_required(TRAVELER)
def public_profile(request, username):
    person = _discoverable_or_404(username)
    if person.pk == request.user.pk:
        return redirect('profile')
    from django.db.models import Count, Q
    from django.utils import timezone
    from trips.models import Trip
    today = timezone.localdate()
    trip_ids = Trip.objects.filter(Q(owner=person) | Q(group_trip__members__user=person)).values('pk')
    person_trips = Trip.objects.filter(pk__in=trip_ids)
    # Same numbers as the owner's own profile, minus anything about who shares trips with them.
    stats = person_trips.aggregate(
        total=Count('pk'),
        upcoming=Count('pk', filter=Q(end_date__gte=today) & ~Q(status=Trip.Status.CANCELLED)),
        completed=Count('pk', filter=Q(status=Trip.Status.COMPLETED) | (Q(end_date__lt=today) & ~Q(status=Trip.Status.CANCELLED))),
        countries=Count('country', distinct=True, filter=~Q(country='') & Q(status=Trip.Status.COMPLETED)),
    )
    visited_countries = list(person_trips.filter(status=Trip.Status.COMPLETED).exclude(country='')
                             .order_by('country').values_list('country', flat=True).distinct())
    return render(request, 'accounts/public_profile.html', {
        'person': person,
        'person_avatar': avatar_url_for(person),
        'person_initials': initials_for(person),
        'person_profile': getattr(person, 'profile', None) if hasattr(person, 'profile') else None,
        'rel': relationship(request.user, person),
        'stats': stats,
        'visited_countries': visited_countries,
        'followers_count': Follow.objects.filter(following=person).count(),
        'following_count': Follow.objects.filter(follower=person).count(),
        'report_form': ReportForm(),
    })


@role_required(TRAVELER)
@require_POST
def follow_toggle(request, username):
    person = _discoverable_or_404(username)
    if person.pk == request.user.pk:
        return JsonResponse({'error': 'You can’t follow yourself.'}, status=400)
    existing = Follow.objects.filter(follower=request.user, following=person)
    if existing.exists():
        existing.delete()
    else:
        try:
            with transaction.atomic():
                Follow.objects.create(follower=request.user, following=person)
        except IntegrityError:
            pass  # a double-click already created it
        else:
            follows_me = Follow.objects.filter(follower=person, following=request.user).exists()
            notify_follow(request.user, person, became_friends=follows_me)
    rel = relationship(request.user, person)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({**rel, 'followers_count': Follow.objects.filter(following=person).count()})
    return redirect('public_profile', username=person.get_username())


@role_required(TRAVELER)
@require_POST
def report_user(request, username):
    person = _discoverable_or_404(username)
    if person.pk == request.user.pk:
        return redirect('profile')
    form = ReportForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Choose a reason for the report.')
    elif Report.objects.filter(reporter=request.user, reported_user=person, status=Report.Status.OPEN).exists():
        messages.info(request, 'You’ve already reported this traveler. Our team will review it.')
    else:
        report = form.save(commit=False)
        report.reporter, report.reported_user = request.user, person
        report.save()
        messages.success(request, 'Thanks for letting us know. Our team will review this report.')
    return redirect('public_profile', username=person.get_username())


@role_required(TRAVELER)
def friends(request):
    following, followers = connection_sets(request.user)
    friend_ids = following & followers
    people = {p.pk: p for p in User.objects.filter(pk__in=following | followers).select_related('profile')}

    def rows(ids):
        out = []
        for pk in ids:
            person = people.get(pk)
            if person is None or not person.is_active or person.role != TRAVELER:
                continue
            out.append({'user': person, 'avatar_url': avatar_url_for(person), 'initials': initials_for(person),
                        'i_follow': pk in following, 'follows_me': pk in followers, 'is_friend': pk in friend_ids})
        return sorted(out, key=lambda r: (r['user'].get_full_name() or r['user'].get_username()).lower())

    friend_rows, follower_rows, following_rows = rows(friend_ids), rows(followers), rows(following)
    return render(request, 'accounts/friends.html', {
        'friend_rows': friend_rows, 'follower_rows': follower_rows, 'following_rows': following_rows,
        'active_tab': request.GET.get('tab', 'friends'),
    })
