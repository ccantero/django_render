from django.db import models
from django.contrib.auth.models import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.contrib.auth.models import BaseUserManager
from django.utils import timezone
# Create your models here.

class UserProfileManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise(ValueError('User must have an email address'))

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields )
        user.set_password(password)
        user.save()

        return user
    
    def create_superuser(self, email, password=None):
        user = self.create_user(email, password)
        user.is_superuser = True
        user.is_staff = True
        user.save()

        return user


class UserProfile(AbstractBaseUser,PermissionsMixin):
    email = models.EmailField(max_length=255, unique=True)
    name = models.CharField(max_length=255)    
    is_active = models.BooleanField(default=True)
    is_staff  = models.BooleanField(default=False)

    objects = UserProfileManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.name

    def __str__(self):
        return self.email


class PasskeyRateLimit(models.Model):
    """Hashed, database-backed rate-limit window shared across web workers."""

    key_hash = models.CharField(max_length=64, unique=True)
    window_started_at = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["window_started_at"], name="profile_passkeyrate_window_idx")]


class PasskeyEnrollmentProof(models.Model):
    """One-use, session-bound password or WebAuthn proof for credential enrollment."""

    PASSWORD = "password"
    PASSKEY = "passkey"
    PROOF_TYPES = [(PASSWORD, "Password"), (PASSKEY, "Passkey")]

    token_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey("profile.UserProfile", on_delete=models.CASCADE)
    proof_type = models.CharField(max_length=16, choices=PROOF_TYPES)
    session_binding_hash = models.CharField(max_length=64)
    credential_pk = models.PositiveBigIntegerField(null=True, blank=True)
    verified_at = models.DateTimeField(default=timezone.now)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "proof_type", "verified_at"], name="prof_passkeyproof_lookup_idx"),
        ]


class PasskeyEnrollmentChallenge(models.Model):
    """Server-side one-use WebAuthn step-up state, bound to a user session."""

    token_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey("profile.UserProfile", on_delete=models.CASCADE)
    session_binding_hash = models.CharField(max_length=64)
    state = models.JSONField()
    started_at = models.DateTimeField(default=timezone.now)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["started_at"], name="passkeychal_start_idx"),
        ]
