from pathlib import Path
import os

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-forth-secret-key-change-me-at-least-32-bytes')
DEBUG = os.environ.get('DJANGO_DEBUG', '1').lower() in {'1', 'true', 'yes', 'on'}
ALLOWED_HOSTS = [host.strip() for host in os.environ.get('DJANGO_ALLOWED_HOSTS', '*').split(',') if host.strip()]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', 'http://localhost:8020,http://127.0.0.1:8020').split(',')
    if origin.strip()
]

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'rest_framework_simplejwt',
    'channels',
    'core',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'forth.urls'
ASGI_APPLICATION = 'forth.asgi.application'
WSGI_APPLICATION = 'forth.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'staticfiles'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

DATABASE_URL = os.environ.get('DATABASE_URL', f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
DATABASES = {
    'default': dj_database_url.parse(DATABASE_URL, conn_max_age=60)
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.environ.get('TZ', 'America/Toronto')
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'static_collected'
STATICFILES_DIRS = [BASE_DIR / 'staticfiles'] if (BASE_DIR / 'staticfiles').exists() else []
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage',
    },
}
MEDIA_URL = '/media/'
MEDIA_ROOT = Path(os.environ.get('JOB_SEEKER_DATA_DIR', str(BASE_DIR / 'media'))).resolve()
DATA_DIR = MEDIA_ROOT

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 40,
}

CORS_ALLOWED_ORIGINS = [
    'http://localhost:4200',
    'http://127.0.0.1:4200',
    'http://localhost:8020',
    'http://127.0.0.1:8020',
]
CORS_ALLOW_CREDENTIALS = True

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': REDIS_URL,
        'KEY_PREFIX': 'forth-cache',
    },
}
BRAVE_SEARCH_API_KEY = os.environ.get('BRAVE_SEARCH_API_KEY', '')
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_TIME_LIMIT = int(os.environ.get('CELERY_TASK_TIME_LIMIT_SECONDS', '900'))
CELERY_TASK_SOFT_TIME_LIMIT = int(os.environ.get('CELERY_TASK_SOFT_TIME_LIMIT_SECONDS', '840'))
CELERY_BEAT_SCHEDULE = {
    'refresh-enabled-job-sources': {
        'task': 'core.tasks.refresh_enabled_sources_task',
        'schedule': float(os.environ.get('SOURCE_REFRESH_INTERVAL_SECONDS', '900')),
    },
}

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [{
                'address': REDIS_URL,
                # redis-py 8 defaults reads to five seconds, the same length
                # as channels_redis's blocking BZPOPMIN. Disable the socket
                # deadline so the command's own timeout can complete cleanly.
                'socket_timeout': None,
                'socket_connect_timeout': 5,
            }],
        },
    }
}

def _runtime_secret(environment_name: str, secret_path: str) -> str:
    value = os.environ.get(environment_name, '')
    if value:
        return value
    try:
        return Path(secret_path).read_text(encoding='utf-8').strip()
    except (OSError, UnicodeError):
        return ''


OPENAI_API_KEY = _runtime_secret('OPENAI_API_KEY', '/run/secrets/openai_api_key')
OPENAI_TEXT_MODEL = os.environ.get('OPENAI_TEXT_MODEL', 'gpt-4.1-mini')
OPENAI_EMBEDDING_MODEL = os.environ.get('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-large')
OPENAI_EMBEDDING_DIMENSIONS = int(os.environ.get('OPENAI_EMBEDDING_DIMENSIONS', '3072'))
OPENAI_TIMEOUT_SECONDS = float(os.environ.get('OPENAI_TIMEOUT_SECONDS', '20'))
OPENAI_MAX_RETRIES = int(os.environ.get('OPENAI_MAX_RETRIES', '0'))
SOURCE_HTTP_TIMEOUT_SECONDS = int(os.environ.get('SOURCE_HTTP_TIMEOUT_SECONDS', '20'))
GOTENBERG_URL = os.environ.get('GOTENBERG_URL', 'http://gotenberg:3000')
GOTENBERG_TIMEOUT_SECONDS = int(os.environ.get('GOTENBERG_TIMEOUT_SECONDS', '45'))
