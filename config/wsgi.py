from django.core.wsgi import get_wsgi_application

from config.environment import configure_settings_module

# Serveur d'application : production par défaut si DJANGO_ENV n'est pas défini.
configure_settings_module(default_env="production")
application = get_wsgi_application()
