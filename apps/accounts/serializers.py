from django.contrib.auth import password_validation
from rest_framework import serializers

from .models import PUBLIC_SIGNUP_ROLES, Profile, Role, User


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ["agency_name", "bio"]


class MeSerializer(serializers.ModelSerializer):
    """Profil de l'utilisateur connecté. Le rôle et l'e-mail sont en lecture seule."""

    profile = ProfileSerializer(required=False)
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "full_name", "phone", "role", "date_joined", "profile"]
        read_only_fields = ["id", "email", "role", "date_joined"]

    def update(self, instance, validated_data):
        profile_data = validated_data.pop("profile", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if profile_data is not None:
            profile, _ = Profile.objects.get_or_create(user=instance)
            for field, value in profile_data.items():
                setattr(profile, field, value)
            profile.save()
        return instance


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8, max_length=128)
    first_name = serializers.CharField(max_length=80)
    last_name = serializers.CharField(max_length=80)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=[(r.value, r.label) for r in PUBLIC_SIGNUP_ROLES], default=Role.CUSTOMER)

    def validate_phone(self, value):
        if value:
            User._meta.get_field("phone").run_validators(value)
        return value

    def validate(self, attrs):
        candidate = User(email=attrs["email"], first_name=attrs["first_name"], last_name=attrs["last_name"])
        password_validation.validate_password(attrs["password"], user=candidate)
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(min_length=8, max_length=128, write_only=True)

    def validate_new_password(self, value):
        password_validation.validate_password(value)
        return value


class PublicUserSerializer(serializers.ModelSerializer):
    """Informations minimales affichées sur une annonce : jamais d'e-mail ni de téléphone."""

    name = serializers.CharField(source="public_name")
    agency_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "role", "date_joined", "agency_name"]

    def get_agency_name(self, obj) -> str:
        profile = getattr(obj, "profile", None)
        return profile.agency_name if profile else ""


class AdminUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "phone", "role", "is_active", "date_joined", "last_login"]
        read_only_fields = fields


class AdminRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.choices)


class AdminActiveSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()
    reason = serializers.CharField(max_length=200, required=False, allow_blank=True)


class AuthResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    user = MeSerializer()
