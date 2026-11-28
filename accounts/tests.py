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
        self.assertRedirects(response, reverse('profile_setup'))
        user = User.objects.get(username='new-traveler')
        self.assertIsNotNone(user.created_at)
        self.assertIsNotNone(user.updated_at)

    def test_registration_returns_to_invite_link(self):
        invite = '/dashboard/join/ABCDEFGHJK/'
        response = self.client.post(reverse('register'), {
            'username': 'invitee', 'email': 'invitee@example.com',
            'password1': PASSWORD, 'password2': PASSWORD, 'next': invite,
        })
        self.assertRedirects(response, reverse('profile_setup'))
        response = self.finish_setup_by_skipping_optional_questions()
        self.assertEqual(response['Location'], invite)
        self.assertEqual(User.objects.get(username='invitee').first_name, '')

    def test_registration_ignores_offsite_next(self):
        response = self.client.post(reverse('register'), {
            'username': 'invitee2', 'email': 'invitee2@example.com',
            'password1': PASSWORD, 'password2': PASSWORD, 'next': 'https://evil.example/',
        })
        self.assertRedirects(response, reverse('profile_setup'))
        self.assertRedirects(self.finish_setup_by_skipping_optional_questions(), reverse('traveler_dashboard'))

    def finish_setup_by_skipping_optional_questions(self):
        setup = reverse('profile_setup')
        for name in ('first_name', 'last_name', 'location'):
            self.assertRedirects(self.client.post(setup, {'action': 'skip', 'question': name, name: 'Discarded'}), setup)
        birthday = self.client.get(setup)
        self.assertNotContains(birthday, 'value="skip"')
        self.assertContains(birthday, 'name="birth_date"')
        bypass = self.client.post(setup, {'action': 'skip', 'question': 'birth_date'})
        self.assertContains(bypass, 'This field is required.')
        self.assertRedirects(self.client.post(setup, {'question': 'birth_date', 'birth_date': '2000-01-01'}), setup)
        return self.client.post(setup, {'action': 'skip', 'question': 'referral_source'})

    def test_setup_saves_optional_details_and_does_not_run_again(self):
        from .models import Profile

        self.client.post(reverse('register'), {
            'username': 'profile-setup', 'email': 'setup@example.com',
            'password1': PASSWORD, 'password2': PASSWORD,
        })
        setup = reverse('profile_setup')
        page = self.client.get(setup)
        self.assertContains(page, '1 of 5')
        self.assertNotContains(page, 'name="last_name"')
        self.assertNotContains(page, 'name="email"')
        answers = (
            ('first_name', 'Ava'), ('last_name', 'Reyes'), ('location', 'Philippines'),
            ('birth_date', '2000-02-29'), ('referral_source', 'social'),
        )
        for name, value in answers:
            self.assertContains(self.client.get(setup), f'name="{name}"')
            if name == 'birth_date':
                bad = self.client.post(setup, {'question': name, name: '2999-01-01'})
                self.assertContains(bad, 'Your birthday must be a date in the past.')
                self.assertContains(bad, 'class="setup-error-popup" role="alert" data-setup-error>')
                from datetime import timedelta

                from django.utils import timezone

                today = timezone.localdate()
                birthday_page = self.client.get(setup)
                cutoff = birthday_page.context['field'].form.latest_birth_date
                self.assertContains(birthday_page, f'max="{cutoff.isoformat()}"')
                for rejected in (today, today + timedelta(days=1), cutoff + timedelta(days=1)):
                    bad = self.client.post(setup, {'question': name, name: rejected.isoformat()})
                    self.assertContains(bad, 'Step 4 of 5')
                boundary = self.client.post(setup, {'question': name, name: cutoff.isoformat()})
                self.assertRedirects(boundary, setup)
                self.assertContains(self.client.get(setup), 'Step 5 of 5')
                self.assertRedirects(self.client.post(setup, {'action': 'back'}), setup)
                for impossible_date in ('2001-02-29', '2000-02-30', '2000-04-31', '2000-13-01'):
                    bad = self.client.post(setup, {'question': name, name: impossible_date})
                    self.assertContains(bad, 'Enter a valid date.')
                    self.assertContains(bad, 'Step 4 of 5')
                bad = self.client.post(setup, {'question': name, name: '01/02/2000'})
                self.assertContains(bad, 'Enter a valid date in YYYY-MM-DD format.')
            if name == 'last_name':
                self.assertRedirects(self.client.post(setup, {'action': 'back'}), setup)
                self.assertContains(self.client.get(setup), 'value="Ava"')
                self.client.post(setup, {'question': 'first_name', 'first_name': 'Ava'})
            response = self.client.post(setup, {'question': name, name: value, 'email': 'changed@example.com'})
            self.assertRedirects(response, reverse('traveler_dashboard') if name == 'referral_source' else setup)
        user = User.objects.get(username='profile-setup')
        details = Profile.objects.get(user=user)
        self.assertEqual((user.first_name, user.last_name, user.email), ('Ava', 'Reyes', 'setup@example.com'))
        self.assertEqual((details.location, details.birth_date.isoformat(), details.referral_source),
                         ('Philippines', '2000-02-29', 'social'))
        self.assertRedirects(self.client.get(setup), reverse('traveler_dashboard'))

    def test_existing_users_do_not_enter_setup(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(reverse('profile_setup')), reverse('traveler_dashboard'))


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


class ReferralAnalyticsTests(TestCase):
    def test_admin_sources_are_ranked_and_unanswered_profiles_are_excluded(self):
        from .models import Profile

        cache.clear()
        admin = User.objects.create_superuser('source-admin', password=PASSWORD)
        for index, source in enumerate(('social', 'social', 'search', '')):
            user = User.objects.create_user(f'referral-{index}')
            Profile.objects.create(user=user, referral_source=source)
        self.client.force_login(admin)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertContains(response, 'How travelers heard about us')
        self.assertEqual(response.context['stats']['referral_responses'], 3)
        self.assertEqual(response.context['stats']['referral_sources'], [
            {'label': 'Social media', 'value': 2, 'pct': 67},
            {'label': 'Search engine', 'value': 1, 'pct': 33},
        ])
