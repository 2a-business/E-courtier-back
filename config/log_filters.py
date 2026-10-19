"""Filtres de journalisation partagés par Django (settings.LOGGING) et gunicorn (gunicorn.conf.py)."""

import logging


class MaxLevelFilter(logging.Filter):
    """Ne laisse passer que les messages strictement inférieurs à ``level`` (ex. INFO sur stdout)."""

    def __init__(self, level: str | int = "WARNING"):
        super().__init__()
        self.max_level = logging.getLevelName(level) if isinstance(level, str) else level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self.max_level
