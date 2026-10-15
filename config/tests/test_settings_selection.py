"""Sélection des paramètres et garde-fous de production.

Chaque cas s'exécute dans un sous-processus avec un environnement contrôlé (sans le .env local).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent.parent
STRONG_KEY = "k3y-de-test-Tr3s-L0ngue-et-Aleatoire-0123456789abcdefXYZ"
PROD_OK = {
    "DJANGO_ENV": "production",
    "DJANGO_SECRET_KEY": STRONG_KEY,
    "DATABASE_URL": "postgresql://app:motdepasse@ep-exemple-123-pooler.eu-central-1.aws.neon.tech/ecourtier?sslmode=require",
    "DJANGO_ALLOWED_HOSTS": "api.exemple.sn",
    "CORS_ALLOWED_ORIGINS": "https://exemple.sn",
    "CSRF_TRUSTED_ORIGINS": "https://exemple.sn",
    "FRONTEND_URL": "https://exemple.sn",
    "PAYMENT_SIMULATION_ENABLED": "false",
}

PROBE = (
    "import django; from django.conf import settings; django.setup(); "
    "print(settings.SETTINGS_MODULE, settings.ENVIRONMENT, settings.DEBUG, settings.PAYMENT_SIMULATION_ENABLED)"
)


def run(code: str, extra: dict, via_manage: bool = False):
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), "DJANGO_DOTENV_FILE": "/nonexistent/.env", **extra}
    if via_manage:
        cmd = [sys.executable, "manage.py", "shell", "-c", code.replace("import django; ", "").replace("django.setup(); ", "")]
    else:
        cmd = [sys.executable, "-c", "from config.environment import configure_settings_module as c; c('development'); " + code]
    return subprocess.run(cmd, cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)


def assert_refused(result, fragment):
    assert result.returncode != 0, result.stdout
    assert fragment in result.stderr, result.stderr[-800:]


def test_local_default_is_development():
    result = run(PROBE, {})
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[:4] == ["config.settings.dev", "development", "True", "True"]


def test_manage_py_with_production_env_loads_prod_settings():
    result = run(PROBE, PROD_OK, via_manage=True)
    assert result.returncode == 0, result.stderr[-800:]
    assert result.stdout.split()[-4:] == ["config.settings.prod", "production", "False", "False"]


def test_wsgi_defaults_to_production():
    env = {"PATH": os.environ["PATH"], "DJANGO_DOTENV_FILE": "/nonexistent/.env", **{k: v for k, v in PROD_OK.items() if k != "DJANGO_ENV"}}
    result = subprocess.run(
        [sys.executable, "-c", "import config.wsgi; from django.conf import settings; print(settings.SETTINGS_MODULE)"],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr[-800:]
    assert result.stdout.strip() == "config.settings.prod"


def test_dev_settings_refused_when_env_is_production():
    result = run(PROBE, {**PROD_OK, "DJANGO_SETTINGS_MODULE": "config.settings.dev"})
    assert_refused(result, "seuls les paramètres config.settings.prod")
    # Même en contournant le sélecteur, dev.py refuse de se charger.
    direct = subprocess.run(
        [sys.executable, "-c", "import os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings.dev'; " + PROBE],
        cwd=BACKEND, env={"PATH": os.environ["PATH"], "DJANGO_DOTENV_FILE": "/nonexistent/.env", "DJANGO_ENV": "production"},
        capture_output=True, text=True, timeout=60,
    )
    assert_refused(direct, "paramètres de développement sont interdits")


def test_test_settings_refused_in_production():
    result = run(PROBE, {**PROD_OK, "DJANGO_SETTINGS_MODULE": "config.settings.test"})
    assert_refused(result, "seuls les paramètres config.settings.prod")


@pytest.mark.parametrize("value", ["prod", "Production ", "staging"])
def test_unknown_environment_is_refused(value):
    result = run(PROBE, {"DJANGO_ENV": value})
    if value.strip().lower() == "production":
        assert result.returncode != 0  # accepté comme production mais configuration incomplète
    else:
        assert_refused(result, "est invalide")


@pytest.mark.parametrize(
    "missing, fragment",
    [
        ("DJANGO_SECRET_KEY", "DJANGO_SECRET_KEY est obligatoire"),
        ("DATABASE_URL", "DATABASE_URL est obligatoire"),
        ("DJANGO_ALLOWED_HOSTS", "DJANGO_ALLOWED_HOSTS est obligatoire"),
        ("CORS_ALLOWED_ORIGINS", "CORS_ALLOWED_ORIGINS est obligatoire"),
        ("CSRF_TRUSTED_ORIGINS", "CSRF_TRUSTED_ORIGINS est obligatoire"),
        ("FRONTEND_URL", "FRONTEND_URL est obligatoire"),
    ],
)
def test_production_refuses_missing_variables(missing, fragment):
    env = {k: v for k, v in PROD_OK.items() if k != missing}
    assert_refused(run(PROBE, env), fragment)


@pytest.mark.parametrize(
    "override, fragment",
    [
        ({"PAYMENT_SIMULATION_ENABLED": "true"}, "PAYMENT_SIMULATION_ENABLED doit être false"),
        ({"DJANGO_SECRET_KEY": "dev-only-insecure-key-ne-pas-utiliser-en-production"}, "trop faible"),
        ({"DJANGO_SECRET_KEY": "court"}, "trop faible"),
        ({"DJANGO_ALLOWED_HOSTS": "*"}, "ne doit pas contenir"),
        ({"CORS_ALLOWED_ORIGINS": "http://localhost:5173"}, "uniquement des URL https://"),
        ({"DATABASE_URL": "postgresql://a:b@ep-x.neon.tech/ecourtier"}, "sans ?sslmode=require"),
        ({"DATABASE_URL": "postgresql://a:b@localhost/test_ecourtier"}, "désigne une base de test"),
        ({"DATABASE_URL": "sqlite:///db.sqlite3"}, "exige PostgreSQL"),
        ({"WAVE_PAYMENT_LINK": "http://pay.wave.com/m/x"}, "WAVE_PAYMENT_LINK doit être"),
    ],
)
def test_production_refuses_dangerous_values(override, fragment):
    assert_refused(run(PROBE, {**PROD_OK, **override}), fragment)


def test_seed_demo_refused_with_prod_settings_even_without_django_env():
    env = {k: v for k, v in PROD_OK.items() if k != "DJANGO_ENV"}
    env["DJANGO_SETTINGS_MODULE"] = "config.settings.prod"
    result = subprocess.run(
        [sys.executable, "manage.py", "seed_demo"], cwd=BACKEND,
        env={"PATH": os.environ["PATH"], "DJANGO_DOTENV_FILE": "/nonexistent/.env", **env},
        capture_output=True, text=True, timeout=60,
    )
    assert_refused(result, "seed_demo est interdit en production")


def test_test_settings_refuse_remote_or_application_database():
    remote = {"DJANGO_SETTINGS_MODULE": "config.settings.test", "TEST_DATABASE_URL": "postgresql://a:b@ep-x.neon.tech/t?sslmode=require"}
    assert_refused(run(PROBE, remote), "pointe vers un serveur distant")
    same = {"DJANGO_SETTINGS_MODULE": "config.settings.test", "TEST_DATABASE_URL": "postgresql://a:b@localhost/x", "DATABASE_URL": "postgresql://a:b@localhost/x"}
    assert_refused(run(PROBE, same), "ne doit pas être identique")


def _db_target(*args, **extra_env):
    return subprocess.run(
        [sys.executable, "manage.py", "db_target", *args], cwd=BACKEND,
        env={"PATH": os.environ["PATH"], "DJANGO_DOTENV_FILE": "/nonexistent/.env", **PROD_OK, **extra_env},
        capture_output=True, text=True, timeout=60,
    )


def test_db_target_shows_target_without_password_and_rejects_pooler_for_migrations():
    result = _db_target("--expect-direct", "--expect-production")
    assert "motdepasse" not in result.stdout + result.stderr
    assert "pooled (pooler Neon)" in result.stdout
    assert_refused(result, "utilisez l'URL directe")


def test_db_target_accepts_expected_direct_host_and_rejects_other():
    direct = "postgresql://app:motdepasse@ep-exemple-123.eu-central-1.aws.neon.tech/ecourtier?sslmode=require"
    ok = _db_target("--expect-host", "ep-exemple-123.eu-central-1.aws.neon.tech", "--expect-database", "ecourtier",
                    "--expect-direct", "--expect-production", DATABASE_URL=direct)
    assert ok.returncode == 0, ok.stderr[-500:]
    assert "Cible conforme" in ok.stdout
    wrong = _db_target("--expect-host", "ep-autre-999.eu-central-1.aws.neon.tech", DATABASE_URL=direct)
    assert_refused(wrong, "différent de l'hôte attendu")


def test_render_generate_value_secret_is_accepted():
    """Render « generateValue » : valeur aléatoire de 256 bits encodée en base64 (44 caractères)."""
    import base64
    import secrets as _secrets

    for _ in range(5):
        key = base64.b64encode(_secrets.token_bytes(32)).decode()
        assert len(key) == 44
        result = run(PROBE, {**PROD_OK, "DJANGO_SECRET_KEY": key})
        assert result.returncode == 0, "clé de type Render refusée"  # la clé n'est jamais affichée


def test_remote_test_database_never_targets_application_server():
    pooled = "postgresql://a:b@ep-prod-1-pooler.eu-central-1.aws.neon.tech/ecourtier?sslmode=require"
    direct_test = "postgresql://a:b@ep-prod-1.eu-central-1.aws.neon.tech/tests?sslmode=require"
    env = {"DJANGO_SETTINGS_MODULE": "config.settings.test", "ALLOW_REMOTE_TEST_DATABASE": "true",
           "DATABASE_URL": pooled, "TEST_DATABASE_URL": direct_test}
    assert_refused(run(PROBE, env), "même serveur que DATABASE_URL")
    env_direct = {**env, "DATABASE_URL": "postgresql://a:b@localhost/x", "DATABASE_URL_DIRECT": direct_test.replace("/tests", "/ecourtier")}
    assert_refused(run(PROBE, env_direct), "même serveur que DATABASE_URL")
    other = {**env, "TEST_DATABASE_URL": "postgresql://a:b@ep-branche-jetable-2.eu-central-1.aws.neon.tech/t?sslmode=require"}
    assert run(PROBE, other).returncode == 0
