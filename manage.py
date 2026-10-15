#!/usr/bin/env python
import sys


def main():
    from config.environment import configure_settings_module

    # DJANGO_ENV=production → config.settings.prod ; sinon développement (comportement local inchangé).
    configure_settings_module(default_env="development")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
