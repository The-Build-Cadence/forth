"""Account-specific AI configuration. Credentials never leave the server."""
import os
from pathlib import Path

from cryptography.fernet import Fernet
from django.conf import settings

from .models import AccountSettings
from .usage import current_owner_id


def cipher():
    key = getattr(settings, 'ACCOUNT_ENCRYPTION_KEY', '')
    if not key:
        # Shared persistent volume, outside publicly served/static files. Keep
        # this file with backups; losing it makes saved credentials unreadable.
        path = Path(settings.DATA_DIR) / '.account-credentials.key'
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return Fernet(path.read_bytes().strip())
        # Atomic publish avoids another worker reading a partially written key.
        import tempfile
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.credential-key-')
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(Fernet.generate_key())
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
        key = path.read_bytes().strip()
    return Fernet(key.encode() if isinstance(key, str) else key)


def account_config():
    owner_id = current_owner_id()
    return AccountSettings.objects.filter(owner_id=owner_id).first() if owner_id else None


def ai_credentials():
    config = account_config()
    if config and config.use_personal_ai:
        if not config.openai_key_encrypted:
            return '', config.text_model or settings.OPENAI_TEXT_MODEL, config.reasoning_effort, 'personal'
        key = cipher().decrypt(config.openai_key_encrypted.encode()).decode()
        return key, config.text_model or settings.OPENAI_TEXT_MODEL, config.reasoning_effort, 'personal'
    return settings.OPENAI_API_KEY, settings.OPENAI_TEXT_MODEL, '', 'shared'


def text_model():
    config = account_config()
    return config.text_model if config and config.use_personal_ai and config.text_model else settings.OPENAI_TEXT_MODEL


def reasoning_options():
    config = account_config()
    return {'reasoning': {'effort': config.reasoning_effort}} if config and config.use_personal_ai and config.reasoning_effort else {}
