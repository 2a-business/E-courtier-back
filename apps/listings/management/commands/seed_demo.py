"""Données de démonstration reproductibles et clairement fictives.

Usage : python manage.py seed_demo [--password MOTDEPASSE] [--reset]
Refusé en production. Aucun paiement réel, aucune signature n'est créé.
"""

import secrets
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Profile, Role, User
from apps.listings import services as listing_services
from apps.listings.demo_images import building, fake_pdf
from apps.listings.models import Listing
from apps.moderation.services import create_report
from apps.reviews.models import Review
from apps.verification import services as verification_services
from apps.visits.models import Visit, VisitSlot, VisitStatus
from apps.visits.services import create_slots

DOMAIN = "demo.e-courtier.sn"
USERS = [
    ("admin", "Awa", "Diop (démo)", Role.ADMIN),
    ("proprietaire", "Moussa", "Ndiaye (démo)", Role.OWNER),
    ("agent", "Fatou", "Sow (démo)", Role.AGENT),
    ("client", "Ibrahima", "Fall (démo)", Role.CUSTOMER),
    ("cliente", "Aminata", "Ba (démo)", Role.CUSTOMER),
]

# (titre, type, transaction, prix, surface, pièces, chambres, sdb, meublé, ville, quartier, lat, lng, équipements, propriétaire)
LISTINGS = [
    ("Appartement 3 pièces lumineux à Fann Hock", "APARTMENT", "RENT", 280000, 85, 3, 2, 1, False, "Dakar", "Fann Hock", "14.6858", "-17.4652", ["balcon", "climatisation", "surpresseur"], "proprietaire"),
    ("F3 avec balcon proche de l'UCAD", "APARTMENT", "RENT", 300000, 90, 3, 2, 2, False, "Dakar", "Fann Hock", "14.6870", "-17.4630", ["balcon", "gardiennage"], "agent"),
    ("Studio meublé à Mermoz", "STUDIO", "RENT", 150000, 30, 1, 0, 1, True, "Dakar", "Mermoz", "14.7071", "-17.4751", ["climatisation", "wifi"], "agent"),
    ("Villa avec piscine aux Almadies", "VILLA", "SALE", 450000000, 420, 7, 5, 4, False, "Dakar", "Almadies", "14.7447", "-17.5108", ["piscine", "jardin", "gardiennage", "parking", "groupe-electrogene"], "proprietaire"),
    ("Appartement 4 pièces vue mer à Ouakam", "APARTMENT", "RENT", 650000, 140, 4, 3, 2, False, "Dakar", "Ouakam", "14.7232", "-17.4921", ["vue-mer", "ascenseur", "parking", "climatisation"], "agent"),
    ("Chambre pour étudiant à Point E", "ROOM", "RENT", 75000, 14, 1, 1, 1, True, "Dakar", "Point E", "14.6951", "-17.4633", ["wifi"], "proprietaire"),
    ("Maison familiale à Sacré-Cœur 3", "HOUSE", "SALE", 120000000, 250, 6, 4, 3, False, "Dakar", "Sacré-Cœur", "14.7185", "-17.4659", ["jardin", "parking", "surpresseur"], "proprietaire"),
    ("Bureau 60 m² au Plateau", "OFFICE", "RENT", 500000, 60, 3, 0, 1, False, "Dakar", "Plateau", "14.6705", "-17.4325", ["climatisation", "ascenseur", "wifi"], "agent"),
    ("Appartement 2 pièces à Liberté 6", "APARTMENT", "RENT", 200000, 60, 2, 1, 1, False, "Dakar", "Liberté 6", "14.7248", "-17.4562", ["balcon"], "proprietaire"),
    ("Duplex meublé aux Mamelles", "APARTMENT", "RENT", 900000, 180, 5, 3, 3, True, "Dakar", "Mamelles", "14.7302", "-17.5003", ["toit-terrasse", "climatisation", "cuisine-equipee", "vue-mer"], "agent"),
    ("Terrain 300 m² à Diamniadio", "LAND", "SALE", 25000000, 300, 1, 0, 0, False, "Diamniadio", "Pôle urbain", "14.7210", "-17.1830", [], "proprietaire"),
    ("Villa F5 à Saly Portudal", "VILLA", "SALE", 85000000, 300, 5, 4, 3, False, "Saly", "Saly Portudal", "14.4462", "-17.0055", ["piscine", "jardin"], "agent"),
    ("Appartement 3 pièces à Ngor", "APARTMENT", "RENT", 450000, 100, 3, 2, 2, False, "Dakar", "Ngor", "14.7478", "-17.5139", ["vue-mer", "climatisation", "balcon"], "proprietaire"),
    ("Studio non meublé aux Parcelles Assainies", "STUDIO", "RENT", 90000, 25, 1, 0, 1, False, "Dakar", "Parcelles Assainies", "14.7605", "-17.4402", [], "proprietaire"),
]

VERIFIED_INDEXES = {0, 2, 3, 4, 6, 9}
PENDING_INDEXES = {1, 12}
FEATURED_INDEXES = {0, 3, 4, 9}


class Command(BaseCommand):
    help = "Crée des données de démonstration fictives (refusé en production)."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Mot de passe commun des comptes de démonstration (sinon aléatoire).")
        parser.add_argument("--reset", action="store_true", help="Supprime d'abord les comptes et annonces de démo.")

    def handle(self, *args, password=None, reset=False, **options):
        if settings.ENVIRONMENT == "production" or "prod" in settings.SETTINGS_MODULE:
            raise CommandError("seed_demo est interdit en production.")
        if reset:
            with transaction.atomic():
                self._reset()
        if User.objects.filter(email__endswith=f"@{DOMAIN}").exists():
            raise CommandError("Des données de démo existent déjà. Relancez avec --reset.")
        password = password or secrets.token_urlsafe(10)
        with transaction.atomic():
            users = self._users(password)
            listings = self._listings(users)
            self._verification(users, listings)
            self._visits(users, listings)
        self.stdout.write(self.style.SUCCESS(f"{len(listings)} annonces fictives créées."))
        self.stdout.write("Comptes de démonstration (à n'utiliser qu'en local) :")
        for key, *_rest, role in USERS:
            self.stdout.write(f"  {role:9} {key}@{DOMAIN}")
        self.stdout.write(f"Mot de passe commun : {password}")

    def _reset(self):
        demo_users = User.objects.filter(email__endswith=f"@{DOMAIN}")
        listings = Listing.objects.filter(owner__in=demo_users)
        from apps.contracts.models import Contract, ContractSignature
        from apps.transactions.models import Transaction

        # Les signatures sont protégées en temps normal ; seule la remise à zéro de la démo les efface.
        ContractSignature.objects.filter(contract__listing__in=listings).delete()
        Contract.objects.filter(listing__in=listings).delete()
        Transaction.objects.filter(listing__in=listings).delete()
        Visit.objects.filter(listing__in=listings).delete()
        Visit.objects.filter(customer__in=demo_users).delete()
        for listing in listings:
            for photo in listing.photos.all():
                photo.image.delete(save=False)
                photo.thumbnail.delete(save=False)
            for doc in listing.verification_documents.all():
                doc.file.delete(save=False)
        listings.delete()
        from apps.verification.models import VerificationRequest

        VerificationRequest.objects.filter(submitted_by__in=demo_users).delete()
        demo_users.delete()

    def _users(self, password):
        users = {}
        for key, first, last, role in USERS:
            extra = {"is_staff": True} if role == Role.ADMIN else {}
            user = User.objects.create_user(
                email=f"{key}@{DOMAIN}", password=password, first_name=first, last_name=last, phone="+221 77 000 00 0" + str(len(users)), **extra
            )
            user.role = role
            user.save(update_fields=["role"])
            Profile.objects.create(user=user, agency_name="Agence Téranga (fictive)" if role == Role.AGENT else "")
            users[key] = user
        return users

    def _listings(self, users):
        listings = []
        for i, (title, ptype, ttype, price, surface, rooms, bedrooms, baths, furnished, city, district, lat, lng, amen, owner) in enumerate(LISTINGS):
            listing = listing_services.create_listing(
                owner=users[owner], title=title,
                description=(
                    f"Annonce FICTIVE de démonstration. {title}, situé à {district} ({city}). "
                    f"{rooms} pièce(s), {bedrooms} chambre(s), {baths} salle(s) de bain. "
                    "Quartier calme, proche des commerces et des transports. Les photos sont des illustrations générées."
                ),
                property_type=ptype, transaction_type=ttype, price=price, surface_m2=surface, rooms=rooms,
                bedrooms=bedrooms, bathrooms=baths, is_furnished=furnished, city=city, district=district,
                address_public=f"Quartier {district}", address_private=f"Adresse fictive n°{i + 1}, {district}",
                latitude=Decimal(lat), longitude=Decimal(lng), amenities=amen,
            )
            Listing.objects.filter(pk=listing.pk).update(is_demo=True)
            for variant in range(3):
                listing_services.add_photo(actor=users[owner], listing=listing, uploaded=building(i, variant),
                                           caption=["Façade", "Séjour", "Vue extérieure"][variant])
            listing = listing_services.change_publication(actor=users[owner], listing=listing, target="PUBLISHED")
            if i in FEATURED_INDEXES:
                listing_services.set_featured(actor=users["admin"], listing=listing, featured=True)
            listings.append(listing)
        return listings

    def _verification(self, users, listings):
        for i in VERIFIED_INDEXES | PENDING_INDEXES:
            listing = listings[i]
            owner = listing.owner
            verification_services.upload_document(actor=owner, listing=listing, doc_type="ID_CARD", uploaded=fake_pdf("CNI"))
            verification_services.upload_document(
                actor=owner, listing=listing, doc_type="MANDATE" if owner.role == Role.AGENT else "LAND_TITLE",
                uploaded=fake_pdf("Justificatif du bien"),
            )
            request = verification_services.submit(actor=owner, listing=listing)
            if i in VERIFIED_INDEXES:
                verification_services.decide(
                    actor=users["admin"], request=request, approve=True,
                    reason="[DÉMO] Décision fictive générée par seed_demo : aucun document réel n'a été examiné.",
                )

    def _visits(self, users, listings):
        tomorrow = timezone.localdate() + timedelta(days=1)
        for listing in listings[:10]:
            for d in range(0, 7):
                day = tomorrow + timedelta(days=d)
                if day.weekday() == 6:
                    continue
                create_slots(actor=listing.owner, listing=listing, date=day, start_time=time(9, 0), end_time=time(12, 0), duration_minutes=45)
                create_slots(actor=listing.owner, listing=listing, date=day, start_time=time(15, 0), end_time=time(18, 0), duration_minutes=45)
        # Historique : une visite passée, effectuée, suivie d'un avis (créé directement, données fictives).
        listing = listings[0]
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime.combine(timezone.localdate() - timedelta(days=3), time(10, 0)), tz)
        slot = VisitSlot.objects.create(listing=listing, host=listing.owner, starts_at=start, ends_at=start + timedelta(minutes=45))
        Visit.objects.create(listing=listing, slot=slot, customer=users["cliente"], host=listing.owner,
                             status=VisitStatus.COMPLETED, confirmed_at=start - timedelta(days=1), completed_at=start + timedelta(hours=1))
        Review.objects.create(listing=listing, author=users["cliente"], rating=4, owner_rating=5,
                              comment="Avis fictif de démonstration : logement conforme aux photos, propriétaire ponctuel.")
        create_report(listing=listings[13], reporter=users["cliente"], reason="WRONG_INFO",
                      details="Signalement fictif de démonstration : la surface semble inexacte.")
