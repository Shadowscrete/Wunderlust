from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse


User = get_user_model()
PASSWORD = 'Fjord!52Maple'


class AuthenticationLandingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.username = 'landing-test-user'
        self.user = User.objects.create_user(username=self.username, email='landing@example.com', password=PASSWORD)

    def test_login_lands_travelers_on_their_dashboard(self):
        response = self.client.post(reverse('login'), {'username': self.username, 'password': PASSWORD}, follow=True)
        self.assertEqual(response.redirect_chain[0][0], reverse('login_success'))
        self.assertEqual(response.redirect_chain[-1][0], reverse('traveler_dashboard'))

    def test_success_landing_requires_authentication(self):
        response = self.client.get(reverse('login_success'))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('login_success')}")

    def test_registration_saves_user_timestamps(self):
        response = self.client.post(reverse('register'), {
            'username': 'new-traveler', 'email': 'new-traveler@example.com',
            'password1': PASSWORD, 'password2': PASSWORD,
        })
        self.assertRedirects(response, reverse('traveler_dashboard'))
        user = User.objects.get(username='new-traveler')
        self.assertIsNotNone(user.created_at)
        self.assertIsNotNone(user.updated_at)

    def test_registration_returns_to_invite_link(self):
        invite = '/dashboard/join/ABCDEFGHJK/'
        response = self.client.post(reverse('register'), {
            'username': 'invitee', 'email': 'invitee@example.com',
            'password1': PASSWORD, 'password2': PASSWORD, 'next': invite,
        })
        self.assertEqual(response['Location'], invite)

    def test_registration_ignores_offsite_next(self):
        response = self.client.post(reverse('register'), {
            'username': 'invitee2', 'email': 'invitee2@example.com',
            'password1': PASSWORD, 'password2': PASSWORD, 'next': 'https://evil.example/',
        })
        self.assertRedirects(response, reverse('traveler_dashboard'))


class LoginProtectionTests(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_user(username='target', email='target@example.com', password=PASSWORD)

    def test_lockout_after_repeated_failures_even_with_right_password(self):
        for _ in range(5):
            self.client.post(reverse('login'), {'username': 'target', 'password': 'wrong'})
        response = self.client.post(reverse('login'), {'username': 'target', 'password': PASSWORD})
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, 'Too many sign-in attempts', status_code=429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_success_resets_the_counter(self):
        for _ in range(4):
            self.client.post(reverse('login'), {'username': 'target', 'password': 'wrong'})
        self.client.post(reverse('login'), {'username': 'target', 'password': PASSWORD})
        self.client.logout()
        for _ in range(4):
            self.client.post(reverse('login'), {'username': 'target', 'password': 'wrong'})
        response = self.client.post(reverse('login'), {'username': 'target', 'password': PASSWORD})
        self.assertEqual(response.status_code, 302)


class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='forgetful', email='forgetful@example.com', password=PASSWORD)

    def test_full_reset_flow(self):
        response = self.client.post(reverse('password_reset'), {'email': 'forgetful@example.com'})
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        link = next(line for line in mail.outbox[0].body.splitlines() if '/accounts/reset/' in line).strip()
        path = link.split('://', 1)[1].split('/', 1)[1]
        response = self.client.get('/' + path, follow=True)
        self.assertContains(response, 'Choose a new password')
        response = self.client.post(response.redirect_chain[-1][0], {'new_password1': 'Lagoon!88Cedar', 'new_password2': 'Lagoon!88Cedar'})
        self.assertRedirects(response, reverse('password_reset_complete'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Lagoon!88Cedar'))

    def test_unknown_email_looks_the_same_and_sends_nothing(self):
        response = self.client.post(reverse('password_reset'), {'email': 'nobody@example.com'})
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_requests_are_rate_limited(self):
        for _ in range(8):
            self.client.post(reverse('password_reset'), {'email': 'forgetful@example.com'})
        self.assertEqual(len(mail.outbox), 5)


class LogoutTests(TestCase):
    def test_logout_clears_offline_copies(self):
        user = User.objects.create_user(username='leaver', password=PASSWORD)
        self.client.force_login(user)
        response = self.client.post(reverse('logout'))
        self.assertIn('storage', response['Clear-Site-Data'])
