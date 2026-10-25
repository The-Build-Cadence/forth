"""Deterministic PostgreSQL tests; provider requests use test mocks/fallbacks."""
from .settings import *  # noqa: F403

OPENAI_API_KEY = ''
BRAVE_SEARCH_API_KEY = ''
FORTH_BETA_INVITE_CODE = ''
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
# TestCase creates users inside its default-connection transaction. A second
# connection cannot see them; use that same transaction for the test ledger.
USAGE_DATABASE_ALIAS = 'default'
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
FORTH_PUBLIC_URL = 'http://localhost:8021'
OAUTH2_PROVIDER = {**OAUTH2_PROVIDER, 'OIDC_ISS_ENDPOINT': FORTH_PUBLIC_URL,
                   'OAUTH2_PROTECTED_RESOURCE_IDENTIFIER': f'{FORTH_PUBLIC_URL}/mcp/',
                   'OAUTH2_PROTECTED_RESOURCE_AUTHORIZATION_SERVERS': [FORTH_PUBLIC_URL]}
