from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


User = get_user_model()


class AuthenticationLandingTests(TestCase):
    def setUp(self):
        self.username = 'landing-test-user'
        self.password = 'Fjord!52Maple'
        self.user = User.objects.create_user(
            username=self.username,
            email='landing@example.com',
            password=self.password,
        )

    def test_login_redirects_to_success_landing(self):
        response = self.client.post(reverse('login'), {
            'username': self.username,
            'password': self.password,
        })

        self.assertRedirects(response, reverse('login_success'))
        self.assertContains(
            self.client.get(reverse('login_success')),
            f'Welcome back, {self.username}.',
        )

    def test_success_landing_requires_authentication(self):
        response = self.client.get(reverse('login_success'))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('login_success')}",
        )

    def test_registration_saves_user_timestamps(self):
        response = self.client.post(reverse('register'), {
            'username': 'new-traveler',
            'email': 'new-traveler@example.com',
            'password1': 'Fjord!52Maple',
            'password2': 'Fjord!52Maple',
        })

        self.assertRedirects(response, reverse('home'))
        user = User.objects.get(username='new-traveler')
        self.assertIsNotNone(user.created_at)
        self.assertIsNotNone(user.updated_at)
