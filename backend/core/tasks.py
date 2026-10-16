from __future__ import annotations

from celery import shared_task
from .usage import metered_task

from .models import AgentRun, Application, ApplicationEvent, CandidateProfile, JobPosting, JobSource, ProfileDocument, ProfileFact, SourceRun
from .realtime_events import publish_user_event
from .services import ingest_profile_document, recompute_match


@shared_task
@metered_task(ProfileDocument, 'document_id')
def ingest_profile_document_task(document_id: int) -> dict:
    document = ProfileDocument.objects.select_related('owner').get(pk=document_id)
    publish_user_event(document.owner_id, 'profile_ingestion_started', {'document_id': document.id})
    try:
        result = ingest_profile_document(document)
        publish_user_event(document.owner_id, 'profile_ingestion_finished', {'document_id': document.id, 'status': document.status, **result})
        try:
            refresh_profile_search_task.delay(document.owner_id)
        except Exception:
            pass
        return result
    except Exception as exc:
        document.status = 'failed'
        document.status_message = str(exc)[:500]
        document.save(update_fields=['status', 'status_message', 'updated_at'])
        publish_user_event(document.owner_id, 'profile_ingestion_finished', {'document_id': document.id, 'status': 'failed', 'error': str(exc)[:500]})
        raise


@shared_task
@metered_task(JobPosting, 'job_id')
def recompute_job_match_task(job_id: int) -> dict:
    job = JobPosting.objects.select_related('owner').get(pk=job_id)
    publish_user_event(job.owner_id, 'match_recompute_started', {'job_id': job.id})
    try:
        match = recompute_match(job)
        payload = {'job_id': job.id, 'match_id': match.id, 'score': match.score, 'confidence': match.confidence}
        publish_user_event(job.owner_id, 'match_recomputed', payload)
        return payload
    except Exception as exc:
        publish_user_event(job.owner_id, 'match_recompute_failed', {'job_id': job.id, 'error': str(exc)[:500]})
        raise


@shared_task
@metered_task()
def recompute_all_matches_task(owner_id: int) -> dict:
    jobs = JobPosting.objects.filter(owner_id=owner_id)
    count = 0
    for job in jobs.iterator():
        recompute_match(job)
        count += 1
    publish_user_event(owner_id, 'matches_recomputed', {'count': count})
    return {'count': count}


@shared_task
@metered_task(JobPosting, 'job_id')
def regenerate_application_materials_task(job_id: int) -> dict:
    """Create fresh, profile-aware resume and cover-letter versions for a job."""
    from django.utils import timezone

    from .domain.documents import prepare_application_materials

    job = JobPosting.objects.select_related('owner').get(pk=job_id)
    job.materials_status = 'running'
    job.save(update_fields=['materials_status', 'updated_at'])
    publish_user_event(job.owner_id, 'materials_regeneration_started', {'job_id': job.id})
    application, _ = Application.objects.get_or_create(
        owner=job.owner,
        job=job,
        defaults={'status': 'preparing'},
    )
    # Generating a new version must not rewind an application already submitted.

    try:
        materials = prepare_application_materials(job.owner, job, application=application)
        ApplicationEvent.objects.create(
            owner=job.owner,
            application=application,
            event_type='materials_regenerated',
            happened_at=timezone.now(),
            notes='Resume and cover letter regenerated from the latest verified profile evidence.',
            metadata={
                'resume_id': materials['resume'].id,
                'cover_letter_id': materials['cover_letter'].id,
                'cover_letter_version': materials['cover_letter'].version,
            },
        )
        payload = {
            'job_id': job.id,
            'application_id': application.id,
            'resume_id': materials['resume'].id,
            'cover_letter_id': materials['cover_letter'].id,
            'cover_letter_version': materials['cover_letter'].version,
        }
        job.materials_status = 'ready'
        job.save(update_fields=['materials_status', 'updated_at'])
        publish_user_event(job.owner_id, 'materials_regenerated', payload)
        return payload
    except Exception as exc:
        Application.objects.filter(pk=application.pk, status='preparing', resume__isnull=True).update(
            status='saved', updated_at=timezone.now(),
        )
        job.materials_status = 'failed'
        job.save(update_fields=['materials_status', 'updated_at'])
        publish_user_event(job.owner_id, 'materials_regeneration_failed', {
            'job_id': job.id,
            'application_id': application.id,
            'error': str(exc)[:500],
        })
        raise


@shared_task
@metered_task()
def refresh_profile_search_task(owner_id: int, force: bool = False) -> dict:
    """Refresh candidate/fact vectors, then re-rank every stored opportunity."""
    from .domain.embeddings import refresh_fact_embedding, refresh_job_embedding, refresh_profile_embedding

    profile = CandidateProfile.objects.select_related('owner').get(owner_id=owner_id)
    publish_user_event(owner_id, 'profile_embedding_started', {'profile_id': profile.id})
    embedded_facts = 0
    for fact in ProfileFact.objects.filter(owner_id=owner_id).iterator():
        before = fact.embedding_content_hash
        refresh_fact_embedding(fact, force=force)
        embedded_facts += int(force or before != fact.embedding_content_hash)
    refresh_profile_embedding(profile.owner, force=force)
    match_count = 0
    for job in JobPosting.objects.filter(owner_id=owner_id).iterator():
        refresh_job_embedding(job, force=force)
        recompute_match(job)
        match_count += 1
    publish_user_event(owner_id, 'matches_recomputed', {'count': match_count})
    profile.refresh_from_db()
    payload = {
        'profile_id': profile.id,
        'provider': profile.embedding_provider,
        'model': profile.embedding_model,
        'embedded_facts': embedded_facts,
        'matches': match_count,
    }
    publish_user_event(owner_id, 'profile_embedding_finished', payload)
    return payload


@shared_task
@metered_task(SourceRun, 'run_id')
def execute_source_run_task(run_id: int, origin: str = 'background') -> dict:
    from .domain.sourcing import execute_source_run

    run = SourceRun.objects.select_related('owner', 'source').get(pk=run_id)
    publish_user_event(run.owner_id, 'source_run_started', {'source_run_id': run.id, 'source_id': run.source_id})
    execute_source_run(run)
    payload = {
        'source_run_id': run.id,
        'source_id': run.source_id,
        'status': run.status,
        'imported': run.imported_count,
        'updated': run.updated_count,
        'errors': run.error_count,
    }
    publish_user_event(run.owner_id, 'source_run_finished', payload)
    return payload


@shared_task
def refresh_enabled_sources_task() -> dict:
    from datetime import timedelta
    from django.utils import timezone

    queued = 0
    for source in JobSource.objects.filter(enabled=True, kind='brave').iterator():
        minutes = max(15, min(10080, int((source.config or {}).get('schedule_minutes') or 360)))
        if source.last_run_at and source.last_run_at > timezone.now() - timedelta(minutes=minutes):
            continue
        run = SourceRun.objects.create(owner=source.owner, source=source)
        execute_source_run_task.delay(run.id, origin='scheduled')
        queued += 1
    return {'queued': queued}


@shared_task
@metered_task(AgentRun, 'run_id')
def execute_agent_run_task(run_id: int) -> dict:
    from .domain.orchestration import execute_agent_run

    run = AgentRun.objects.select_related('owner', 'thread').get(pk=run_id)
    execute_agent_run(run)
    return {'run_id': run.id, 'status': run.status, 'output': run.output, 'error': run.error}
