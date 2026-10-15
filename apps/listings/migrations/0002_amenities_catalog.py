from django.db import migrations

AMENITIES = [
    ("balcon", "Balcon", "balcons,terrasse"),
    ("climatisation", "Climatisation", "clim,climatiseur,climatise,climatisee"),
    ("parking", "Parking", "garage,place de parking,stationnement"),
    ("piscine", "Piscine", ""),
    ("gardiennage", "Gardiennage", "gardien,securite,vigile"),
    ("groupe-electrogene", "Groupe électrogène", "groupe electrogene,generateur"),
    ("surpresseur", "Surpresseur / réserve d'eau", "reserve d eau,citerne,bache a eau"),
    ("ascenseur", "Ascenseur", ""),
    ("cuisine-equipee", "Cuisine équipée", "cuisine americaine"),
    ("wifi", "Internet / fibre", "fibre,internet,wi fi"),
    ("jardin", "Jardin", "cour"),
    ("vue-mer", "Vue sur mer", "vue mer,bord de mer,pieds dans l eau"),
    ("eau-chaude", "Chauffe-eau", "eau chaude,chauffe eau"),
    ("toit-terrasse", "Toit-terrasse", "rooftop"),
]


def forwards(apps, schema_editor):
    Amenity = apps.get_model("listings", "Amenity")
    for slug, label, synonyms in AMENITIES:
        Amenity.objects.update_or_create(slug=slug, defaults={"label": label, "synonyms": synonyms})


class Migration(migrations.Migration):
    dependencies = [("listings", "0001_initial")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
