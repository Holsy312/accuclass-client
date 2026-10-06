"""Unofficial Python client for the AccuClass attendance API (Engineerica's legacy Service API).

    from accuclass_client import AccuClass

    with AccuClass() as ac:
        ac.login("yourdomain", "you@example.edu", "password")
        csv_bytes = ac.export("attendance", "CSV")

AccuClass is a product of Engineerica Systems, Inc. This project is not affiliated with,
or endorsed by, Engineerica.
"""

from ._version import __version__
from .client import (
    DEFAULT_BASE_URL,
    DEFAULT_USER_AGENT,
    EXPORT_TYPES,
    JSON_NULL,
    AccuClass,
    AccuClassError,
)

__all__ = [
    "AccuClass",
    "AccuClassError",
    "JSON_NULL",
    "EXPORT_TYPES",
    "DEFAULT_BASE_URL",
    "DEFAULT_USER_AGENT",
    "__version__",
]
