from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Report
from .models import Notification, Trip

User = get_user_model()


class AdminPanelTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user('boss', 'boss@example.com', 'Fjord!52Maple', role=User.Role.ADMINISTRATOR)
        self.alice = User.objects.create_user('alice', 'alice@example.com', 'Fjord!52Maple')
        self.bob = User.objects.create_user('bob', 'bob@example.com', 'Fjord!52Maple')
        today = timezone.localdate()
        self.trip = Trip.objects.create(owner=self.alice, destination='Lisbon', country='Portugal',
                                        start_date=today + timedelta(days=10), end_date=today + timedelta(days=14))

    def login(self, user):
        self.client.force_login(user)

    def test_every_admin_page_renders(self):
        self.login(self.admin)
        Report.objects.create(reporter=self.bob, reported_user=self.alice, reason=Report.Reason.SPAM)
        for name, args in [('admin_dashboard', []), ('admin_users', []), ('admin_user_detail', [self.alice.pk]),
                           ('admin_trips', []), ('admin_trip_detail', [self.trip.pk]), ('admin_reports', []),
                           ('admin_travel_info', []), ('admin_notices', []), ('admin_inbox', []),
                           ('account_settings', []), ('public_profile', ['alice'])]:
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 200, name)

    def test_travelers_are_blocked_from_admin_pages(self):
        self.login(self.alice)
        for name in ('admin_users', 'admin_reports', 'admin_notices'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        self.assertEqual(self.client.post(reverse('admin_user_action', args=[self.bob.pk]), {'action': 'deactivate'}).status_code, 403)
        self.bob.refresh_from_db()
        self.assertTrue(self.bob.is_active)

    def test_admin_has_no_profile_and_trimmed_settings(self):
        self.login(self.admin)
        self.assertRedirects(self.client.get(reverse('profile')), reverse('admin_dashboard'))
        page = self.client.get(reverse('account_settings')).content.decode()
        self.assertIn('Appearance', page)
        self.assertIn('Change password', page)
        self.assertNotIn('Delete account', page)
        self.assertNotIn('id="notifications"', page)
        self.client.post(reverse('account_settings'), {'action': 'delete'})
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_account_deletion_transfers_shared_trip(self):
        from .models import GroupTrip

        group = GroupTrip.objects.create(trip=self.trip, created_by=self.alice)
        member = group.members.create(user=self.bob)
        self.login(self.alice)
        self.assertContains(self.client.get(reverse('account_settings')), 'bob will organize Lisbon')
        self.client.post(reverse('account_settings'), {'action': 'delete', 'password': 'Fjord!52Maple'})
        for obj in (self.trip, group, member):
            obj.refresh_from_db()
        self.assertEqual((self.trip.owner, group.created_by, member.membership), (self.bob, self.bob, 'ORGANIZER'))
        self.assertTrue(Notification.objects.filter(user=self.bob, message__contains='bob is now the organizer').exists())

    def test_edit_profile_and_verify_changed_email(self):
        from accounts.forms import AboutMeForm
        from accounts.models import Profile

        profile, _ = Profile.objects.get_or_create(user=self.alice)
        self.alice.first_name = 'Alice'
        self.alice.save()
        data = {'email': 'new@example.com', 'username': 'changed', 'first_name': ''}
        form = AboutMeForm(data, user=self.alice, profile=profile)
        self.assertIn('current_password', form.errors)
        form = AboutMeForm(dict(data, current_password='Fjord!52Maple'), user=self.alice, profile=profile)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.alice.refresh_from_db()
        self.assertEqual((self.alice.username, self.alice.email, self.alice.first_name), ('alice', data['email'], ''))

    def test_member_can_leave_and_rejoin(self):
        from .models import ChecklistCheck, GroupTrip

        group = GroupTrip.objects.create(trip=self.trip, created_by=self.alice)
        group.members.create(user=self.bob)
        item = self.trip.checklist_items.create(title='Passport')
        ChecklistCheck.objects.create(item=item, user=self.bob)
        self.login(self.bob)
        url = reverse('trip_leave', args=[self.trip.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), reverse('trip_list'))
        self.assertFalse(group.members.filter(user=self.bob).exists())
        self.assertFalse(ChecklistCheck.objects.filter(item=item, user=self.bob).exists())
        self.assertTrue(Notification.objects.filter(user=self.alice, message='bob left the trip to Lisbon.').exists())
        self.client.post(reverse('trip_join', args=[group.invite_code]))
        self.assertTrue(group.members.filter(user=self.bob).exists())

    def test_member_removal_notifies_owner(self):
        from .models import GroupTrip

        GroupTrip.objects.create(trip=self.trip, created_by=self.alice).members.create(user=self.bob)
        item = self.trip.checklist_items.create(title='Camera', is_custom=True)
        self.login(self.bob)
        self.client.post(reverse('checklist_remove', args=[item.pk]))
        self.assertTrue(Notification.objects.filter(user=self.alice, message='bob removed Camera from the checklist.').exists())

    def test_admin_trip_notices_reach_members(self):
        from .models import GroupTrip

        GroupTrip.objects.create(trip=self.trip, created_by=self.alice).members.create(user=self.bob)
        self.login(self.admin)
        url = reverse('admin_trip_action', args=[self.trip.pk])
        for action in ('cancel', 'delete'):
            self.client.post(url, {'action': action})
            notices = Notification.objects.filter(trip=self.trip if action == 'cancel' else None)
            self.assertCountEqual(notices.values_list('user_id', flat=True), [self.alice.pk, self.bob.pk])

    def test_report_notifies_admin_and_counts_show(self):
        self.login(self.bob)
        self.client.post(reverse('report_user', args=['alice']), {'reason': Report.Reason.HARASSMENT, 'details': 'rude'})
        self.assertTrue(Notification.objects.filter(user=self.admin, title__contains='@alice').exists())
        self.login(self.admin)
        data = self.client.get(reverse('live_notification_count')).json()
        self.assertEqual(data['count'], 1)
        page = self.client.get(reverse('admin_users') + '?status=reported').content.decode()
        self.assertIn('1×', page)

    def test_deactivate_and_resolve_report(self):
        report = Report.objects.create(reporter=self.bob, reported_user=self.alice, reason=Report.Reason.SPAM)
        self.login(self.admin)
        self.client.post(reverse('admin_report_action', args=[report.pk]), {'action': 'deactivate_user'})
        self.alice.refresh_from_db()
        report.refresh_from_db()
        self.assertFalse(self.alice.is_active)
        self.assertEqual(report.status, Report.Status.REVIEWED)

    def test_admin_cannot_change_self(self):
        self.login(self.admin)
        self.client.post(reverse('admin_user_action', args=[self.admin.pk]), {'action': 'set_role', 'role': User.Role.TRAVELER})
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, User.Role.ADMINISTRATOR)

    def test_broadcast_notice_can_be_marked_read_per_traveler(self):
        self.login(self.admin)
        self.client.post(reverse('admin_notices'), {'notice-audience': 'all', 'notice-title': 'Maintenance tonight', 'notice-message': ''})
        notice = Notification.objects.get(title='Maintenance tonight')
        self.assertIsNone(notice.user_id)
        # The admin does not receive traveler broadcasts.
        self.assertEqual(self.client.get(reverse('live_notification_count')).json()['count'], 0)
        self.login(self.alice)
        self.assertEqual(self.client.get(reverse('live_notification_count')).json()['count'], 1)
        self.client.post(reverse('notification_mark_read', args=[notice.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(self.client.get(reverse('live_notification_count')).json()['count'], 0)
        self.login(self.bob)
        self.assertEqual(self.client.get(reverse('live_notification_count')).json()['count'], 1)

    def test_opening_inbox_reads_personal_and_shared_notifications(self):
        endpoint = reverse('live_notification_count')
        Notification.objects.bulk_create([Notification(user=self.alice, title='Trip update') for _ in range(31)])
        Notification.objects.create(title='System notice')
        self.login(self.alice)
        self.assertEqual(self.client.get(endpoint).json()['count'], 32)
        for _ in range(2):
            result = self.client.post(endpoint).json()
            self.assertEqual(result['count'], 0)
            self.assertTrue(all(item['is_read'] for item in result['notifications']))
        Notification.objects.create(user=self.alice, title='Later update')
        self.assertEqual(self.client.get(endpoint).json()['count'], 1)
        self.login(self.bob)
        self.assertEqual(self.client.get(endpoint).json()['count'], 1)

    def test_opening_admin_inbox_reads_admin_alerts(self):
        notice = Notification.objects.create(user=self.admin, title='Report received')
        self.login(self.admin)
        self.client.get(reverse('admin_inbox'))
        notice.refresh_from_db()
        self.assertTrue(notice.is_read)

    def test_direct_notice_requires_active_traveler(self):
        self.login(self.admin)
        self.client.post(reverse('admin_notices'), {'notice-audience': 'one', 'notice-recipient': 'boss', 'notice-title': 'Hi'})
        self.assertFalse(Notification.objects.filter(title='Hi').exists())
        self.client.post(reverse('admin_notices'), {'notice-audience': 'one', 'notice-recipient': '@bob', 'notice-title': 'Hi'})
        self.assertEqual(Notification.objects.get(title='Hi').user, self.bob)

    def test_trip_cancel_notifies_owner(self):
        self.login(self.admin)
        self.client.post(reverse('admin_trip_action', args=[self.trip.pk]), {'action': 'cancel'})
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, Trip.Status.CANCELLED)
        self.assertTrue(Notification.objects.filter(user=self.alice, trip=self.trip).exists())


class PreparationAndItineraryTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('planner')
        self.client.force_login(self.owner)
        self.start = timezone.localdate() + timedelta(days=1)

    def test_past_itinerary_survives_activity_feed_and_cleanup(self):
        from django.core.management import call_command

        past = timezone.localdate() - timedelta(days=40)
        trip = Trip.objects.create(owner=self.owner, destination='Kyoto', start_date=past, end_date=past)
        day = trip.itinerary_days.create(date=past)
        activity = day.activities.create(title='Historical walk')
        cache.clear()
        self.assertNotContains(self.client.get(reverse('activity_list')), activity.title)
        call_command('cleanup_activities')
        self.assertTrue(day.activities.filter(pk=activity.pk).exists())

    def create_trip(self, city, country):
        response = self.client.post(reverse('trip_create'), {
            'destination': city, 'country': country, 'start_date': self.start,
            'end_date': self.start + timedelta(days=14), 'has_ticket': 'no',
            'generate_itinerary': 'on', 'places': 'Nishiki Market\nnishiki  market',
        })
        self.assertEqual(response.status_code, 302)
        return Trip.objects.get(owner=self.owner)

    def test_removing_unchecked_item_restores_ready_status(self):
        from .models import ChecklistCheck

        trip = self.create_trip('Kyoto', 'Japan')
        for item in trip.checklist_items.all():
            ChecklistCheck.objects.create(item=item, user=self.owner)
        extra = trip.checklist_items.create(title='Camera', is_custom=True)
        self.client.post(reverse('checklist_remove', args=[extra.pk]))
        trip.refresh_from_db()
        self.assertEqual(trip.status, Trip.Status.READY)

    def test_edit_extends_existing_itinerary(self):
        trip = self.create_trip('Kyoto', 'Japan')
        end = trip.end_date + timedelta(days=2)
        response = self.client.post(reverse('trip_edit', args=[trip.pk]), {
            'destination': trip.destination, 'country': trip.country, 'start_date': trip.start_date,
            'end_date': end, 'status': trip.status,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(trip.itinerary_days.filter(date=end, title='', notes='').exists())

    def test_optional_items_can_be_removed_only_by_trip_travelers(self):
        trip = self.create_trip('Kyoto', 'Japan')
        mandatory = trip.checklist_items.filter(is_mandatory=True).first()
        self.assertEqual(self.client.post(reverse('checklist_remove', args=[mandatory.pk])).status_code, 404)
        custom = trip.checklist_items.create(title='Camera', is_custom=True)
        url = reverse('checklist_remove', args=[custom.pk])
        self.client.force_login(User.objects.create_user('outsider'))
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 405)
        for item in [custom, trip.checklist_items.filter(is_custom=False, is_mandatory=False).first()]:
            self.assertRedirects(self.client.post(reverse('checklist_remove', args=[item.pk])),
                                 reverse('trip_detail', args=[trip.pk]) + '#preparation', fetch_redirect_response=False)
            self.assertFalse(trip.checklist_items.filter(pk=item.pk).exists())
        self.assertTrue(trip.checklist_items.filter(pk=mandatory.pk).exists())

    def test_named_places_do_not_repeat_across_days(self):
        trip = self.create_trip('Kyoto', 'Japan')
        from .models import Activity
        activities = Activity.objects.filter(day__trip=trip)
        locations = list(activities.values_list('location', flat=True))
        self.assertEqual(len(locations), len(set(locations)))
        self.assertEqual(activities.filter(title__icontains='Nishiki').count(), 1)
        self.assertEqual(trip.itinerary_days.count(), 15)
        self.assertTrue(trip.itinerary_days.filter(activities__isnull=True).exists())

    def test_country_suggestions_are_used_once(self):
        trip = self.create_trip('Osaka', 'Japan')
        from .models import Activity
        titles = list(Activity.objects.filter(day__trip=trip).values_list('title', flat=True))
        self.assertEqual(len(titles), 4)
        self.assertEqual(len(titles), len(set(titles)))

    def test_join_from_my_trips_with_code(self):
        from .models import GroupTrip, RemovedMember

        trip = self.create_trip('Kyoto', 'Japan')
        group = GroupTrip.objects.create(trip=trip, created_by=self.owner)
        guest = User.objects.create_user('guest')
        self.client.force_login(guest)
        listing = reverse('trip_list')
        invite = reverse('trip_join', args=[group.invite_code])
        self.assertContains(self.client.post(listing, {'invite_code': 'unknown'}), 'Trip code not found')
        self.assertRedirects(self.client.post(listing, {'invite_code': ' ' + group.invite_code.lower() + ' '}), invite)
        self.assertFalse(group.members.filter(user=guest).exists())
        self.assertRedirects(self.client.post(invite), reverse('trip_detail', args=[trip.pk]))
        self.assertContains(self.client.get(listing), trip.destination)
        group.members.filter(user=guest).delete()
        RemovedMember.objects.create(group_trip=group, user=guest)
        self.assertRedirects(self.client.post(invite), listing)
        self.assertFalse(group.members.filter(user=guest).exists())


class TravelerFlowTests(TestCase):
    """The traveler side: creating trips, access control, groups, checklist and itinerary edits."""

    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user('olivia', 'olivia@example.com', 'Fjord!52Maple')
        self.friend = User.objects.create_user('felix', 'felix@example.com', 'Fjord!52Maple')
        self.stranger = User.objects.create_user('sam', 'sam@example.com', 'Fjord!52Maple')
        self.client.force_login(self.owner)
        today = timezone.localdate()
        self.client.post(reverse('trip_create'), {
            'destination': 'Kyoto', 'country': 'Japan',
            'start_date': (today + timedelta(days=20)).isoformat(), 'end_date': (today + timedelta(days=22)).isoformat(),
            'has_ticket': 'no', 'places': '', 'generate_itinerary': 'on',
        })
        self.trip = Trip.objects.get(destination='Kyoto')

    def test_trip_creation_sets_up_checklist_and_itinerary(self):
        self.assertEqual(self.trip.owner, self.owner)
        self.assertEqual(self.trip.itinerary_days.count(), 3)
        self.assertTrue(self.trip.checklist_items.filter(is_document=True, title='Passport').exists())

    def test_strangers_cannot_see_or_change_a_trip(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(reverse('trip_detail', args=[self.trip.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('trip_delete', args=[self.trip.pk])).status_code, 404)
        item = self.trip.checklist_items.first()
        self.assertEqual(self.client.post(reverse('checklist_toggle', args=[item.pk])).status_code, 404)
        self.assertTrue(Trip.objects.filter(pk=self.trip.pk).exists())

    def test_invite_join_and_member_permissions(self):
        self.client.post(reverse('trip_invite', args=[self.trip.pk]))
        code = self.trip.__class__.objects.get(pk=self.trip.pk).group_trip.invite_code
        self.client.force_login(self.friend)
        self.client.post(reverse('trip_join', args=[code]))
        self.assertEqual(self.client.get(reverse('trip_detail', args=[self.trip.pk])).status_code, 200)
        # Members can view, but only the owner can delete.
        self.assertEqual(self.client.post(reverse('trip_delete', args=[self.trip.pk])).status_code, 404)

    def test_suggested_activity_can_be_kept_or_removed(self):
        from .models import Activity
        suggested = list(Activity.objects.filter(day__trip=self.trip, is_recommended=True)[:2])
        url = reverse('trip_detail', args=[self.trip.pk])
        self.client.post(url, {'action': 'keep_activity', 'activity_id': suggested[0].pk})
        self.client.post(url, {'action': 'remove_activity', 'activity_id': suggested[1].pk})
        suggested[0].refresh_from_db()
        self.assertFalse(suggested[0].is_recommended)
        self.assertFalse(Activity.objects.filter(pk=suggested[1].pk).exists())

    def test_cannot_remove_activity_from_someone_elses_trip(self):
        from .models import Activity
        activity = Activity.objects.filter(day__trip=self.trip).first()
        self.client.force_login(self.stranger)
        self.client.post(reverse('trip_detail', args=[self.trip.pk]), {'action': 'remove_activity', 'activity_id': activity.pk})
        self.assertTrue(Activity.objects.filter(pk=activity.pk).exists())


class PlatformTests(TestCase):
    def test_manifest_and_service_worker(self):
        manifest = self.client.get('/manifest.webmanifest')
        self.assertEqual(manifest['Content-Type'], 'application/manifest+json')
        self.assertEqual(manifest.json()['display'], 'standalone')
        worker = self.client.get('/sw.js')
        self.assertEqual(worker.status_code, 200)
        self.assertIn('javascript', worker['Content-Type'])
        self.assertIn('/offline/', worker.content.decode())
        self.assertEqual(self.client.get('/offline/').status_code, 200)

    def test_content_security_policy_and_nonce(self):
        user = User.objects.create_user('nonce', password='Fjord!52Maple')
        self.client.force_login(user)
        response = self.client.get(reverse('traveler_dashboard'))
        policy = response['Content-Security-Policy']
        self.assertIn("frame-ancestors 'none'", policy)
        nonce = policy.split("'nonce-")[1].split("'")[0]
        self.assertIn(f'nonce="{nonce}"', response.content.decode())

    def test_user_timezone_decides_today(self):
        import zoneinfo
        user = User.objects.create_user('tz', password='Fjord!52Maple')
        self.client.force_login(user)
        self.assertEqual(self.client.post(reverse('update_timezone'), {'timezone': 'Not/AZone'}).status_code, 400)
        self.client.post(reverse('update_timezone'), {'timezone': 'Asia/Manila'})
        from accounts.models import Profile
        self.assertEqual(Profile.objects.get(user=user).timezone, 'Asia/Manila')
        from accounts.middleware import UserTimezoneMiddleware
        seen = {}
        def capture(request):
            seen['tz'] = timezone.get_current_timezone()
            return None
        request = self.client.get('/').wsgi_request
        request.user = user
        UserTimezoneMiddleware(capture)(request)
        self.assertEqual(seen['tz'], zoneinfo.ZoneInfo('Asia/Manila'))

    def test_public_pages_render(self):
        for url in ('/', reverse('login'), reverse('register'), reverse('password_reset'), reverse('password_reset_done')):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
        home = self.client.get('/').content.decode()
        self.assertIn('Get the group', home)
        self.assertIn('rel="manifest"', home)
        self.assertIn('Forgot password?', self.client.get(reverse('login')).content.decode())
