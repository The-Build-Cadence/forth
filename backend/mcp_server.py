#!/usr/bin/env python3
"""Credential-authenticated local MCP adapter and request-scoped tool dispatcher.

Local clients supply FORTH_MCP_USERNAME and FORTH_MCP_PASSWORD. Remote HTTP
requests bind the user from a verified OAuth access token, never tool arguments.
"""
from __future__ import annotations

import json
import os
import sys
from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable


BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'forth.settings')

import django  # noqa: E402

django.setup()

from django.contrib.auth import authenticate, get_user_model  # noqa: E402
from django.utils import timezone  # noqa: E402

from core.domain.documents import prepare_application_materials  # noqa: E402
from core.domain.matching import recompute_match  # noqa: E402
from core.domain.profiles import candidate_profile  # noqa: E402
from core.domain.material_preferences import readable_match_summary
from core.domain.scoring import normalize_match_score  # noqa: E402
from core.models import (  # noqa: E402
    Application,
    ApplicationEvent,
    CandidatePreference,
    CoverLetter,
    JobMatch,
    JobPosting,
    ProfileFact,
    Resume,
)
from core.services import import_job_posting  # noqa: E402


class ToolError(ValueError):
    """A safe, actionable tool error shown to the MCP caller."""


_request_owner = ContextVar('mcp_owner', default=None)


@contextmanager
def authenticated_owner(owner):
    token = _request_owner.set(owner)
    try:
        yield
    finally:
        _request_owner.reset(token)


def _owner():
    owner = _request_owner.get()
    if owner is not None:
        if owner.is_authenticated and owner.is_active:
            return owner
        raise ToolError('Authentication required.')
    username = os.environ.get('FORTH_MCP_USERNAME', '').strip()
    password = os.environ.get('FORTH_MCP_PASSWORD', '')
    if not username or not password:
        raise ToolError('Set FORTH_MCP_USERNAME (email) and FORTH_MCP_PASSWORD. Owner selectors are no longer accepted.')
    owner = authenticate(username=username, password=password)
    if owner is None:
        raise ToolError('Invalid credentials or inactive account.')
    return owner


def _limit(value: Any, *, default: int = 10, maximum: int = 40) -> int:
    try:
        return max(1, min(int(value or default), maximum))
    except (TypeError, ValueError):
        return default


def _job_result(job: JobPosting, match: JobMatch | None = None) -> dict[str, Any]:
    match = match or getattr(job, 'match', None)
    minimum_score = getattr(getattr(job.owner, 'candidate_profile', None), 'minimum_match_score', 50)
    return {
        'job_id': job.id,
        'title': job.title,
        'company': job.company,
        'location': job.location,
        'work_mode': job.remote_policy,
        'seniority': job.seniority,
        'compensation': job.compensation,
        'source_url': job.source_url,
        'application_url': job.application_url or job.source_url,
        'freshness': job.freshness_status,
        'status': job.status,
        'materials_status': job.materials_status,
        'generation_instructions_override': job.generation_instructions,
        'match': None if not match else {
            'score': match.score,
            'normalized_score': normalize_match_score(match.score, minimum_score),
            'profile_minimum_score': minimum_score,
            'meets_profile_threshold': match.score >= minimum_score,
            'confidence': match.confidence,
            'eligibility': match.hard_filter_status,
            'required_conditions_label': {'pass': 'Meets required conditions', 'fail': 'Required condition mismatch', 'uncertain': 'Needs confirmation'}.get(match.hard_filter_status, 'Not assessed'),
            'summary': readable_match_summary((match.explanation_json or {}).get('summary', '')),
            'covered_skills': (match.explanation_json or {}).get('covered_skills', []),
            'missing_requirements': match.missing_requirements,
            'eligibility_notes': (
                (match.explanation_json or {}).get('eligibility_failures', [])
                + (match.explanation_json or {}).get('eligibility_uncertainties', [])
            ),
            'supporting_facts': match.supporting_facts[:8],
        },
    }


def get_candidate_context(arguments: dict[str, Any]) -> dict[str, Any]:
    owner = _owner()
    profile = candidate_profile(owner)
    facts = ProfileFact.objects.filter(owner=owner).order_by('-verified_by_user', 'fact_type', 'title')
    if arguments.get('verified_only', True):
        facts = facts.filter(verified_by_user=True)
    return {
        'profile': {
            'generation_instructions': profile.generation_instructions,
            'resume_contact': profile.resume_contact,
            'headline': profile.headline,
            'summary': profile.professional_summary,
            'target_roles': profile.target_roles,
            'target_industries': profile.target_industries,
            'location': profile.location,
            'authorized_countries': profile.authorized_countries,
            'work_modes': profile.work_modes,
            'employment_types': profile.employment_types,
            'minimum_compensation': profile.minimum_compensation,
            'compensation_currency': profile.compensation_currency,
            'minimum_match_score': profile.minimum_match_score,
            'completeness': profile.completeness,
        },
        'preferences': list(CandidatePreference.objects.filter(owner=owner).values(
            'category', 'label', 'value', 'importance', 'verified_by_user', 'rationale',
        )),
        'facts': list(facts[:_limit(arguments.get('limit'), default=30)] .values(
            'id', 'fact_type', 'title', 'statement', 'verified_by_user', 'lifecycle', 'strength',
        )),
    }


def search_jobs(arguments: dict[str, Any]) -> dict[str, Any]:
    owner = _owner()
    query = str(arguments.get('query', '')).strip()
    min_score = arguments.get('min_score')
    jobs = JobPosting.objects.filter(owner=owner).select_related('match', 'owner__candidate_profile')
    if arguments.get('work_mode'):
        jobs = jobs.filter(remote_policy=str(arguments['work_mode']).lower())
    if min_score is not None:
        try:
            jobs = jobs.filter(match__score__gte=int(min_score))
        except (TypeError, ValueError):
            raise ToolError('min_score must be an integer from 0 to 100.')
    if query:
        from core.domain.embeddings import rank_jobs_by_query
        jobs = rank_jobs_by_query(jobs, query)
    else:
        jobs = jobs.order_by('-match__score', '-posted_at', '-discovered_at')
    return {'query': query, 'jobs': [_job_result(job) for job in jobs[:_limit(arguments.get('limit'))]]}


def record_job(arguments: dict[str, Any]) -> dict[str, Any]:
    """Import a browser-found public posting and immediately score it."""
    text = str(arguments.get('description', '')).strip()
    source_url = str(arguments.get('source_url', '')).strip()
    if len(text) < 80:
        raise ToolError('description must contain the job posting text (at least 80 characters).')
    if source_url and not source_url.startswith(('https://', 'http://')):
        raise ToolError('source_url must be an http(s) URL.')
    owner = _owner()
    job = import_job_posting(owner, text=text, source_url=source_url)
    job.refresh_from_db()
    match = JobMatch.objects.filter(owner=owner, job=job).first() or recompute_match(job)
    return {'recorded': True, 'job': _job_result(job, match)}


def prepare_application(arguments: dict[str, Any]) -> dict[str, Any]:
    """Create drafts only. It never approves materials or submits a form."""
    owner = _owner()
    try:
        job = JobPosting.objects.get(owner=owner, pk=int(arguments.get('job_id')))
    except (TypeError, ValueError, JobPosting.DoesNotExist) as exc:
        raise ToolError('job_id must identify a job in the configured owner workspace.') from exc
    application, _ = Application.objects.get_or_create(
        owner=owner, job=job, defaults={'status': 'preparing'},
    )
    result = prepare_application_materials(owner, job, application=application)
    resume, letter = result['resume'], result['cover_letter']
    return {
        'application_id': application.id,
        'job_id': job.id,
        'status': application.status,
        'resume': {
            'id': resume.id, 'title': resume.title, 'content_markdown': resume.content_markdown,
            'approved': resume.approved, 'validation': resume.validation, 'design': resume.content_json.get('design'),
            'generation_instructions': resume.content_json.get('generation_instructions', ''),
        },
        'cover_letter': {
            'id': letter.id, 'title': letter.title, 'content_markdown': letter.content_markdown,
            'approved': letter.approved, 'validation': letter.validation, 'design': letter.content_json.get('design'),
            'generation_instructions': letter.content_json.get('generation_instructions', ''),
        },
        'next_step': 'Review and explicitly approve the drafts. Application submission remains a separate browser action requiring confirmation.',
    }


def get_application_materials(arguments: dict[str, Any]) -> dict[str, Any]:
    owner = _owner()
    try:
        job = JobPosting.objects.get(owner=owner, pk=int(arguments.get('job_id')))
    except (TypeError, ValueError, JobPosting.DoesNotExist) as exc:
        raise ToolError('job_id must identify a job in the configured owner workspace.') from exc
    application = Application.objects.filter(owner=owner, job=job).select_related('resume').first()
    resume = Resume.objects.filter(owner=owner, target_job=job).order_by('-updated_at').first()
    letter = CoverLetter.objects.filter(owner=owner, target_job=job).order_by('-version').first()
    return {
        'job': _job_result(job),
        'application': None if not application else {
            'id': application.id, 'status': application.status, 'applied_at': application.applied_at,
        },
        'resume': None if not resume else {
            'id': resume.id, 'content_markdown': resume.content_markdown,
            'approved': resume.approved, 'validation': resume.validation, 'design': resume.content_json.get('design'),
            'generation_instructions': resume.content_json.get('generation_instructions', ''),
        },
        'cover_letter': None if not letter else {
            'id': letter.id, 'content_markdown': letter.content_markdown,
            'approved': letter.approved, 'validation': letter.validation, 'design': letter.content_json.get('design'),
            'generation_instructions': letter.content_json.get('generation_instructions', ''),
        },
        'submission_rule': 'Do not enter candidate data or submit an external application without explicit user confirmation at the browser step.',
    }


def record_submitted_application(arguments: dict[str, Any]) -> dict[str, Any]:
    """Record an application only after the browser visibly confirms submission."""
    owner = _owner()
    try:
        application = Application.objects.get(owner=owner, pk=int(arguments.get('application_id')))
    except (TypeError, ValueError, Application.DoesNotExist) as exc:
        raise ToolError('application_id must identify an application in the configured owner workspace.') from exc
    confirmation = str(arguments.get('submission_confirmation', '')).strip()
    if len(confirmation) < 12:
        raise ToolError('Provide the visible submission confirmation before recording an application as applied.')
    application.status = 'applied'
    application.applied_at = timezone.now()
    application.save(update_fields=['status', 'applied_at', 'updated_at'])
    ApplicationEvent.objects.create(
        owner=owner, application=application, event_type='submitted', happened_at=application.applied_at,
        notes=confirmation[:1000], metadata={'recorded_by': 'forth_mcp'},
    )
    return {'application_id': application.id, 'status': application.status, 'applied_at': application.applied_at.isoformat()}


def _owned(model, value, label):
    try:
        return model.objects.get(owner=_owner(), pk=int(value))
    except (TypeError, ValueError, model.DoesNotExist) as exc:
        raise ToolError(f'{label} must identify a record in your workspace.') from exc


def get_opportunity(arguments):
    from core.domain.material_preferences import material_instructions
    job = _owned(JobPosting, arguments.get('job_id'), 'job_id')
    return {**_job_result(job), 'description': job.description_text,
            'requirements': list(job.requirements.values('kind', 'text', 'is_hard')),
            'effective_generation_instructions': material_instructions(job.owner, job),
            'instruction_source': 'account' if job.generation_instructions is None else 'opportunity',
            'applications': list(Application.objects.filter(owner=job.owner, job=job).values('id', 'status', 'applied_at')),
            'signals': list(job.match.signals.values('kind', 'label', 'score', 'explanation', 'evidence')) if getattr(job, 'match', None) else []}


def list_applications(arguments):
    from django.db.models import Q
    applications = Application.objects.filter(owner=_owner()).select_related('job')
    if arguments.get('status'):
        applications = applications.filter(status=arguments['status'])
    if arguments.get('query'):
        applications = applications.filter(Q(job__title__icontains=arguments['query']) | Q(job__company__icontains=arguments['query']))
    try:
        offset = max(0, int(arguments.get('offset', 0)))
    except (ValueError, TypeError) as exc:
        raise ToolError('offset must be a nonnegative integer.') from exc
    limit = _limit(arguments.get('limit'), default=20)
    count = applications.count()
    return {'count': count, 'next_offset': offset + limit if offset + limit < count else None,
            'applications': [{'id': app.id, 'job_id': app.job_id, 'title': app.job.title,
                              'company': app.job.company, 'status': app.status, 'applied_at': app.applied_at,
                              'follow_up_at': app.follow_up_at, 'updated_at': app.updated_at}
                             for app in applications.order_by('-updated_at', '-id')[offset:offset + limit]]}


def get_application(arguments):
    from core.serializers import ApplicationSerializer
    application = _owned(Application, arguments.get('application_id'), 'application_id')
    return dict(ApplicationSerializer(application).data)


def update_application(arguments):
    from core.serializers import ApplicationSerializer
    from django.db import transaction
    from core.realtime_events import publish_user_event
    owner = _owner()
    application = _owned(Application, arguments.get('application_id'), 'application_id')
    allowed = {'status', 'notes', 'follow_up_at', 'outcome', 'contact_name', 'contact_email'}
    changes = arguments.get('changes')
    if not isinstance(changes, dict) or not changes or set(changes) - allowed:
        raise ToolError('changes must contain only status, notes, follow_up_at, outcome, contact_name or contact_email.')
    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application.pk, owner=owner)
        previous = application.status
        serializer = ApplicationSerializer(application, data=changes, partial=True)
        if not serializer.is_valid():
            raise ToolError(str(serializer.errors))
        application = serializer.save()
        ApplicationEvent.objects.create(owner=owner, application=application, event_type='status_changed' if previous != application.status else 'updated',
                                        happened_at=timezone.now(), notes=f'MCP updated {", ".join(sorted(changes))}. Status: {previous} → {application.status}.',
                                        metadata={'recorded_by': 'forth_mcp'})
    publish_user_event(owner.id, 'application_updated', {'application_id': application.id, 'status': application.status})
    return {'application_id': application.id, 'status': application.status, 'applied_at': application.applied_at,
            'follow_up_at': application.follow_up_at, 'updated_fields': sorted(changes)}


def set_material_instructions(arguments):
    from core.serializers import CandidateProfileSerializer, JobPostingSerializer
    if 'instructions' not in arguments:
        raise ToolError('instructions is required; use null for an opportunity to inherit account defaults.')
    instructions = arguments['instructions']
    if arguments.get('job_id') is not None:
        instance = _owned(JobPosting, arguments['job_id'], 'job_id')
        serializer = JobPostingSerializer(instance, data={'generation_instructions': instructions}, partial=True)
        scope = 'opportunity'
    else:
        instance = candidate_profile(_owner())
        serializer = CandidateProfileSerializer(instance, data={'generation_instructions': instructions}, partial=True)
        scope = 'account'
    if not serializer.is_valid():
        raise ToolError(str(serializer.errors))
    serializer.save()
    return {'scope': scope, 'instructions': instance.generation_instructions,
            'effect': 'Used for new resume and cover-letter versions. Existing versions remain unchanged.'}


def get_workspace_status(arguments):
    from core.models import ProfileDocument, AgentRun, SourceRun
    owner = _owner()
    return {'documents': list(ProfileDocument.objects.filter(owner=owner).order_by('-updated_at')[:20].values('id', 'title', 'kind', 'status', 'status_message')),
            'agent_runs': list(AgentRun.objects.filter(owner=owner).order_by('-updated_at')[:20].values('id', 'agent', 'objective', 'status', 'error')),
            'source_runs': list(SourceRun.objects.filter(owner=owner).order_by('-created_at')[:20].values('id', 'status', 'discovered_count', 'imported_count', 'error_count')),
            'material_jobs': list(JobPosting.objects.filter(owner=owner, materials_status__in=['queued', 'running', 'failed']).values('id', 'title', 'materials_status', 'materials_started_at')[:20])}


TOOLS: dict[str, tuple[str, dict[str, Any], Callable[[dict[str, Any]], dict[str, Any]]]] = {
    'get_candidate_context': (
        'Read the owner-scoped career profile, verified evidence, and job-search preferences before sourcing or matching. profile.minimum_match_score is the saved minimum raw fit score, not the normalized display score.',
        {'type': 'object', 'properties': {'verified_only': {'type': 'boolean', 'default': True}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 40}}},
        get_candidate_context,
    ),
    'search_jobs': (
        'Search and rank jobs already recorded in Forth. Results include raw and normalized fit scores, profile_minimum_score, meets_profile_threshold, and evidence gaps. No score filter is applied unless min_score is supplied.',
        {'type': 'object', 'properties': {'query': {'type': 'string'}, 'min_score': {'type': 'integer', 'minimum': 0, 'maximum': 100, 'description': 'Minimum raw fit score (not normalized score). Use profile.minimum_match_score from get_candidate_context to filter by the saved preference.'}, 'work_mode': {'type': 'string', 'enum': ['remote', 'hybrid', 'onsite', 'unknown']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 40}}},
        search_jobs,
    ),
    'record_job': (
        'Record a public job found through browser research, normalize it, deduplicate it, and compute its explainable match. Requires full posting text; it does not submit anything.',
        {'type': 'object', 'properties': {'description': {'type': 'string', 'description': 'Visible job posting text.'}, 'source_url': {'type': 'string', 'description': 'Canonical public posting URL.'}}, 'required': ['description']},
        record_job,
    ),
    'prepare_application': (
        'Create a tracked application plus unapproved, claim-validated tailored resume and cover-letter drafts. Never approves materials or submits an external application.',
        {'type': 'object', 'properties': {'job_id': {'type': 'integer'}}, 'required': ['job_id']},
        prepare_application,
    ),
    'get_application_materials': (
        'Read current tailored materials and validation state for a recorded job. Use it to prepare a browser-assisted application after the user has reviewed the drafts.',
        {'type': 'object', 'properties': {'job_id': {'type': 'integer'}}, 'required': ['job_id']},
        get_application_materials,
    ),
    'record_submitted_application': (
        'Update Forth only after a browser visibly confirms that an external application was submitted. This does not submit a form.',
        {'type': 'object', 'properties': {'application_id': {'type': 'integer'}, 'submission_confirmation': {'type': 'string', 'description': 'Visible confirmation text from the completed site.'}}, 'required': ['application_id', 'submission_confirmation']},
        record_submitted_application,
    ),
}


def get_usage_summary(arguments):
    from core.usage import usage_summary
    return usage_summary(_owner())


TOOLS.update({
    'get_usage_summary': ('Read your recorded OpenAI and Brave request counts and estimated USD costs, including background work. Unknown costs are excluded; historical usage before tracking is unavailable.',
        {'type': 'object', 'properties': {}}, get_usage_summary),
    'get_opportunity': ('Read the complete posting, requirement-check reasons, match signals, linked applications and effective material instructions.',
        {'type': 'object', 'properties': {'job_id': {'type': 'integer'}}, 'required': ['job_id']}, get_opportunity),
    'list_applications': ('Read your pipeline with status/search filters and offset pagination, including applied dates and follow-up dates.',
        {'type': 'object', 'properties': {'status': {'type': 'string', 'enum': [key for key, _ in Application.STATUS_CHOICES]}, 'query': {'type': 'string'}, 'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 40}}}, list_applications),
    'get_application': ('Read a complete application, including notes, contacts, follow-ups, activity, document versions, validation and artifact download paths.',
        {'type': 'object', 'properties': {'application_id': {'type': 'integer'}}, 'required': ['application_id']}, get_application),
    'update_application': ('Update local tracking status, notes or follow-ups at the user’s request. Applied records a submission the user reports, including outside Forth; never submits anything. notes replaces existing notes, so read them first.',
        {'type': 'object', 'properties': {'application_id': {'type': 'integer'}, 'changes': {'type': 'object', 'additionalProperties': False, 'properties': {
            'status': {'type': 'string', 'enum': [key for key, _ in Application.STATUS_CHOICES]}, 'notes': {'type': 'string'},
            'follow_up_at': {'type': ['string', 'null'], 'description': 'ISO 8601 timestamp, or null to clear'},
            'outcome': {'type': 'string'}, 'contact_name': {'type': 'string'}, 'contact_email': {'type': 'string'}}}}, 'required': ['application_id', 'changes']}, update_application),
    'set_material_instructions': ('Save account defaults, or an opportunity override when job_id is supplied. null restores inheritance for an opportunity; empty text explicitly disables custom instructions. Affects future resumes and cover letters.',
        {'type': 'object', 'properties': {'job_id': {'type': 'integer'}, 'instructions': {'type': ['string', 'null'], 'maxLength': 6000}}, 'required': ['instructions']}, set_material_instructions),
    'get_workspace_status': ('Inspect recent profile ingestion, sourcing, agent runs and material-generation progress or failures before retrying work.',
        {'type': 'object', 'properties': {}}, get_workspace_status),
})


def _tool_definitions() -> list[dict[str, Any]]:
    return [{'name': name, 'description': spec[0], 'inputSchema': spec[1],
             'securitySchemes': [{'type': 'oauth2', 'scopes': ['forth:access']}],
             'annotations': {'readOnlyHint': name.startswith(('get_', 'list_', 'search_')), 'destructiveHint': False, 'openWorldHint': False}}
            for name, spec in TOOLS.items()]


def _result(value: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {'content': [{'type': 'text', 'text': json.dumps(value, default=str, ensure_ascii=False)}], 'isError': is_error}


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get('method')
    request_id = request.get('id')
    if method == 'ping':
        return {'jsonrpc': '2.0', 'id': request_id, 'result': {}} if request_id is not None else None
    if method == 'notifications/initialized':
        return None
    if method == 'initialize':
        payload = {
            'protocolVersion': request.get('params', {}).get('protocolVersion', '2025-03-26'),
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': 'forth-job-seeker', 'version': '0.1.0'},
        }
    elif method == 'tools/list':
        payload = {'tools': _tool_definitions()}
    elif method == 'tools/call':
        params = request.get('params') or {}
        name = params.get('name')
        arguments = params.get('arguments') or {}
        if name not in TOOLS:
            payload = _result({'error': f'Unknown tool: {name}'}, is_error=True)
        elif not isinstance(arguments, dict):
            payload = _result({'error': 'Tool arguments must be an object.'}, is_error=True)
        else:
            try:
                from core.usage import usage_context
                with usage_context(_owner(), 'mcp', str(name)):
                    payload = _result(TOOLS[name][2](arguments))
            except ToolError as exc:
                payload = _result({'error': str(exc)}, is_error=True)
            except Exception:
                payload = _result({'error': 'Forth could not complete that operation. Check the local server logs.'}, is_error=True)
    else:
        payload = {'error': {'code': -32601, 'message': f'Method not found: {method}'}}
    if request_id is None:
        return None
    return {'jsonrpc': '2.0', 'id': request_id, 'result': payload} if 'error' not in payload else {'jsonrpc': '2.0', 'id': request_id, **payload}


def main() -> None:
    try:
        _owner()
    except ToolError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    for raw in sys.stdin:
        try:
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise ValueError('JSON-RPC request must be an object.')
            response = handle_request(request)
        except (json.JSONDecodeError, ValueError) as exc:
            response = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': str(exc)}}
        if response is not None:
            print(json.dumps(response, default=str, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
