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


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    location = models.CharField(max_length=100, blank=True)
    birth_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username}'s profile"

