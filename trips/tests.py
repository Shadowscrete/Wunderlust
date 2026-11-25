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
