from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Check concrete configuration required before inviting external users. Does not print secrets.'

    def handle(self, *args, **options):
        problems = []
        public = urlsplit(settings.FORTH_PUBLIC_URL)
        if public.scheme != 'https' or public.hostname in {'localhost', '127.0.0.1'}:
            problems.append('Set FORTH_PUBLIC_URL to the external HTTPS origin and configure a trusted TLS proxy.')
        if settings.DEBUG:
            problems.append('Set DJANGO_DEBUG=0.')
        if settings.SECRET_KEY.startswith('dev-') or len(settings.SECRET_KEY) < 50:
            problems.append('Set a unique DJANGO_SECRET_KEY of at least 50 characters.')
        if '*' in settings.ALLOWED_HOSTS or public.hostname not in settings.ALLOWED_HOSTS:
            problems.append('Set DJANGO_ALLOWED_HOSTS to explicit hostnames including the public hostname.')
        if not settings.EMAIL_HOST or 'localhost' in settings.DEFAULT_FROM_EMAIL:
            problems.append('Configure EMAIL_HOST and DEFAULT_FROM_EMAIL; verify a real recovery email before launch.')
        if not settings.OPENAI_API_KEY:
            problems.append('Configure the shared OpenAI key for the default AI experience.')
        if not settings.BRAVE_SEARCH_API_KEY:
            problems.append('Configure BRAVE_SEARCH_API_KEY for automatic job discovery.')
        if not settings.FORTH_BETA_INVITE_CODE:
            problems.append('Set FORTH_BETA_INVITE_CODE to limit this beta to invited users while shared provider costs are operator-funded.')
        if get_user_model().objects.filter(username='admin').exists():
            if get_user_model().objects.get(username='admin').check_password('adminpass'):
                problems.append('Replace the known local demo administrator password before exposure.')
        if problems:
            raise CommandError('\n'.join(problems))
        self.stdout.write(self.style.SUCCESS('Configuration checks passed. Verify HTTPS, email delivery and backup recovery on the deployment host before sharing the URL.'))
