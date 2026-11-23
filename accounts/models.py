import uuid

from django.db import models
from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager

class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('role', self.model.Role.ADMINISTRATOR)
        return super().create_superuser(username, email, password, **extra_fields)

class User(AbstractUser):
    class Role(models.TextChoices):
        TRAVELER = 'TRAVELER', 'Traveler'
        ADMINISTRATOR = 'ADMINISTRATOR', 'Administrator'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.TRAVELER)
    objects = UserManager()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


def avatar_upload_path(instance, filename):
    # A fresh random name each upload, so browsers never show a stale cached picture.
    return f'avatars/{instance.user_id}/{uuid.uuid4().hex}.jpg'


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    location = models.CharField(max_length=100, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    avatar = models.ImageField(upload_to=avatar_upload_path, blank=True)

    class Theme(models.TextChoices):
        SYSTEM = 'system', 'Match system'
        LIGHT = 'light', 'Light'
        DARK = 'dark', 'Dark'

    theme = models.CharField(max_length=10, choices=Theme.choices, default=Theme.SYSTEM)
    notify_trip_updates = models.BooleanField(default=True, verbose_name='Trip updates')
    notify_member_joins = models.BooleanField(default=True, verbose_name='New group members')
    notify_system = models.BooleanField(default=True, verbose_name='Notices from Wunderlust')

    def __str__(self):
        return f"{self.user.username}'s profile"



class UserSession(models.Model):
    """One row per signed-in browser, so users can see their devices and sign them out."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='login_sessions')
    session_key = models.CharField(max_length=40, unique=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.user} · {self.created_at:%Y-%m-%d}'
