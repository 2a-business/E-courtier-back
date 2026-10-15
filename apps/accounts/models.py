from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Administrateur"
    AGENT = "AGENT", "Agent immobilier"
    OWNER = "OWNER", "Propriétaire"
    CUSTOMER = "CUSTOMER", "Client"


# Rôles qu'un visiteur peut choisir lors de l'inscription publique.
PUBLIC_SIGNUP_ROLES = (Role.CUSTOMER, Role.OWNER)
# Rôles autorisés à publier et gérer des annonces.
LISTING_MANAGER_ROLES = (Role.OWNER, Role.AGENT)

senegal_phone_validator = RegexValidator(
    regex=r"^(\+221\s?)?(7[05678]|3[03])\s?\d{3}\s?\d{2}\s?\d{2}$",
    message="Numéro sénégalais attendu, par exemple +221 77 123 45 67.",
)


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("L'adresse e-mail est obligatoire.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("role", Role.CUSTOMER)
        extra["is_staff"] = False
        extra["is_superuser"] = False
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.update(role=Role.ADMIN, is_staff=True, is_superuser=True)
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField("adresse e-mail", unique=True)
    first_name = models.CharField("prénom", max_length=80)
    last_name = models.CharField("nom", max_length=80)
    phone = models.CharField("téléphone", max_length=20, blank=True, validators=[senegal_phone_validator])
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER, db_index=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        verbose_name = "utilisateur"
        constraints = [
            models.CheckConstraint(condition=models.Q(role__in=Role.values), name="user_role_valid"),
        ]

    def __str__(self):
        return self.email

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def public_name(self) -> str:
        """Nom affiché publiquement : prénom + initiale, sans coordonnées."""
        initial = f" {self.last_name[:1]}." if self.last_name else ""
        return f"{self.first_name}{initial}"

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def can_manage_listings(self) -> bool:
        return self.role in LISTING_MANAGER_ROLES


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    agency_name = models.CharField("agence", max_length=120, blank=True)
    bio = models.TextField(max_length=600, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "profil"

    def __str__(self):
        return f"Profil de {self.user}"
