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
    walkthrough_pending = models.BooleanField(default=True)
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
    notify_new_followers = models.BooleanField(default=True, verbose_name='New followers')

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


class Follow(models.Model):
    """One traveler following another. Two follows in opposite directions make them friends."""
    follower = models.ForeignKey(User, on_delete=models.CASCADE, related_name='following_links')
    following = models.ForeignKey(User, on_delete=models.CASCADE, related_name='follower_links')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [
            models.UniqueConstraint(fields=('follower', 'following'), name='unique_follow'),
            models.CheckConstraint(condition=~models.Q(follower=models.F('following')), name='no_self_follow'),
        ]

    def __str__(self):
        return f'{self.follower} -> {self.following}'


class Report(models.Model):
    """A traveler reporting another traveler, for administrators to review."""
    class Reason(models.TextChoices):
        SPAM = 'SPAM', 'Spam or scam'
        HARASSMENT = 'HARASSMENT', 'Harassment or bullying'
        INAPPROPRIATE = 'INAPPROPRIATE', 'Inappropriate profile or content'
        IMPERSONATION = 'IMPERSONATION', 'Pretending to be someone else'
        OTHER = 'OTHER', 'Something else'

    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        REVIEWED = 'REVIEWED', 'Reviewed'
        DISMISSED = 'DISMISSED', 'Dismissed'

    reporter = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='reports_made')
    reported_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reports_received')
    reason = models.CharField(max_length=20, choices=Reason.choices)
    details = models.TextField(blank=True, max_length=1000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.get_reason_display()}: {self.reported_user}'
