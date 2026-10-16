from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.tasks import refresh_profile_search_task
from core.usage import usage_context


class Command(BaseCommand):
    help = 'Rebuild pgvector candidate, profile-fact, and job embeddings, then recompute matches.'

    def add_arguments(self, parser):
        parser.add_argument('--username', help='Only rebuild one username or email.')
        parser.add_argument('--force', action='store_true', help='Regenerate vectors even when their content hash is current.')
        parser.add_argument(
            '--jobs-only',
            action='store_true',
            help='Only rebuild job vectors and matches; useful after a partial backfill.',
        )

    def handle(self, *args, **options):
        users = get_user_model().objects.filter(candidate_profile__isnull=False).order_by('id')
        username = (options.get('username') or '').strip()
        if username:
            users = users.filter(username=username) | users.filter(email=username)
        if not users.exists():
            raise CommandError('No candidate profiles matched.')
        total_profiles = 0
        total_jobs = 0
        for user in users.distinct():
            if options['jobs_only']:
                from core.domain.embeddings import refresh_job_embedding
                from core.models import JobPosting
                from core.services import recompute_match

                match_count = 0
                provider = ''
                model = ''
                for job in JobPosting.objects.filter(owner=user).iterator():
                    with usage_context(user, 'background', 'rebuild_search_embeddings'):
                        refresh_job_embedding(job, force=options['force'])
                        recompute_match(job)
                    job.refresh_from_db(fields=['embedding_provider', 'embedding_model'])
                    provider = job.embedding_provider
                    model = job.embedding_model
                    match_count += 1
                result = {
                    'provider': provider,
                    'model': model,
                    'embedded_facts': 0,
                    'matches': match_count,
                }
            else:
                result = refresh_profile_search_task(user.id, force=options['force'])
            total_profiles += 1
            total_jobs += result['matches']
            self.stdout.write(
                f"{user.get_username()}: {result['provider']} / {result['model']}; "
                f"{result['embedded_facts']} facts; {result['matches']} matches"
            )
        self.stdout.write(self.style.SUCCESS(f'Rebuilt {total_profiles} profile(s) and scored {total_jobs} job(s).'))
