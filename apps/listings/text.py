import re
import unicodedata


def normalize(value: str) -> str:
    """Minuscules, sans accents, espaces et tirets unifiés : « Fann-Hock » → « fann hock »."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c)).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return value.strip()
