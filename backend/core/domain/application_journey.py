from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.models import Application, ApplicationEvent, JobPosting


@transaction.atomic
def save_job(owner, job):
    JobPosting.objects.select_for_update().get(pk=job.pk, owner=owner)
    application = Application.objects.filter(owner=owner, job=job).order_by('-updated_at', '-id').first()
    if application:
        return application, False
    application = Application.objects.create(owner=owner, job=job, status='saved')
    ApplicationEvent.objects.create(
        owner=owner, application=application, event_type='created',
        happened_at=timezone.now(), notes='Job saved. No documents generated or application submitted.',
    )
    return application, True


def document_status(job):
    if job.materials_status in {'queued', 'running'}:
        if not job.materials_started_at or timezone.now() - job.materials_started_at > timedelta(minutes=15):
            return 'failed'
        return 'generating'
    if job.materials_status == 'failed':
        return 'failed'
    resume = job.resumes.filter(kind='tailored', owner=job.owner).order_by('-created_at', '-id').first()
    letter = job.cover_letters.filter(owner=job.owner).order_by('-version', '-id').first()
    if not resume and not letter:
        return 'not_created'
    return 'reviewed' if resume and letter and resume.approved and letter.approved else 'needs_review'
