"""Mask credential-like config values before a page renders them.

Key-name matching only: a secret stored under an innocuous key is not caught.
Keeping secrets out of config (as the sync driver does) is the real fix.
"""

import re

MASK = "***"
SECRET_KEY = re.compile(
    r"(?i)(secret|password|passwd|token|api_key|access_key|private_key|credential)"
)


def mask_secrets(obj):
    """A copy of ``obj`` with every value under a credential-like key replaced."""
    if isinstance(obj, dict):
        return {
            k: (
                MASK if isinstance(k, str) and SECRET_KEY.search(k) else mask_secrets(v)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [mask_secrets(v) for v in obj]
    return obj
