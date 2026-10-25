"""Leave host filesystem headroom before accepting persistent file writes."""
import shutil
from django.conf import settings


def require_storage_space(incoming_bytes=0):
    root = settings.DATA_DIR
    root.mkdir(parents=True, exist_ok=True)
    reserve = int(getattr(settings, 'STORAGE_MIN_FREE_BYTES', 1024 * 1024 * 1024))
    if shutil.disk_usage(root).free < reserve + incoming_bytes:
        raise ValueError('File storage is temporarily full. Contact the workspace operator.')
