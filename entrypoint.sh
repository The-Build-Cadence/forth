#!/usr/bin/env bash
set -euo pipefail

APP_ROLE="${APP_ROLE:-web}"

if [[ -z "${OPENAI_API_KEY:-}" && -f "/run/secrets/openai_api_key" ]]; then
  export OPENAI_API_KEY="$(cat /run/secrets/openai_api_key)"
fi

python manage.py safe_migrate

if [[ "${DJANGO_SUPERUSER_USERNAME:-}" != "" ]]; then
  python manage.py shell <<'PYTHON'
import os
from django.contrib.auth import get_user_model
User = get_user_model()
username = os.environ['DJANGO_SUPERUSER_USERNAME']
email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '')
if not User.objects.filter(username=username).exists():
    if not password:
        raise RuntimeError('DJANGO_SUPERUSER_PASSWORD is required to create an administrator.')
    User.objects.create_superuser(username=username, email=email, password=password)
PYTHON
fi

if [[ "$APP_ROLE" == "worker" ]]; then
  exec celery -A forth worker -l info -Q "${CELERY_WORKER_QUEUES:-celery}" --concurrency="${CELERY_WORKER_CONCURRENCY:-2}"
elif [[ "$APP_ROLE" == "beat" ]]; then
  exec celery -A forth beat -l info --schedule=/app/data/celerybeat-schedule
else
  exec daphne --access-log /dev/null -b 0.0.0.0 -p 8000 forth.asgi:application
fi
