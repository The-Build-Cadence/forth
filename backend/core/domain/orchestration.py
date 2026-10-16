from __future__ import annotations

from core.account_ai import text_model

import json
from typing import Any, Callable

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from core.domain.briefing import today_briefing
from core.domain.documents import prepare_application_materials, render_application_bundle
from core.domain.profiles import profile_health
from core.domain.sourcing import execute_source_run
from core.models import (
    AgentRun,
    AgentStep,
    Application,
    ApplicationEvent,
    ApprovalRequest,
    ConversationMessage,
    ConversationThread,
    JobPosting,
    JobSource,
    ProfileFact,
    SourceRun,
)
from core.realtime_events import publish_user_event


def default_thread(owner) -> ConversationThread:
    thread = ConversationThread.objects.filter(owner=owner, status='active').first()
    if thread:
        return thread
    return ConversationThread.objects.create(owner=owner, title='Forth concierge')


def _classify(message: str, *, previous_agent: str = '') -> dict[str, str]:
    """Route common chat intents immediately and keep short follow-ups in context."""
    lowered = message.lower()
    if any(term in lowered for term in ['resume', 'cover letter', 'materials', 'pdf', 'tailor', 'prepare']):
        return {'agent': 'documents', 'intent': 'prepare_materials'}
    if any(term in lowered for term in ['find jobs', 'source', 'discover', 'new roles', 'refresh jobs']):
        return {'agent': 'sourcing', 'intent': 'run_sources'}
    if any(term in lowered for term in ['profile', 'skill', 'experience', 'fact', 'know about me']):
        return {'agent': 'profile', 'intent': 'profile_review'}
    if any(term in lowered for term in [
        'score', 'match', 'fit', 'why this job', 'top one', 'best one', 'top job',
        'best job', 'strongest role', 'strongest opportunity', 'recommendation',
    ]):
        return {'agent': 'matching', 'intent': 'explain_matches'}
    if any(term in lowered for term in ['apply', 'follow up', 'pipeline', 'interview']):
        return {'agent': 'application', 'intent': 'application_next_action'}
    if any(term in lowered for term in ['focus on today', 'what should i do', 'status', 'overview', 'briefing', 'priorities']):
        return {'agent': 'concierge', 'intent': 'daily_briefing'}
    follow_up_terms = ['it', 'that', 'this', 'one', 'more', 'why', 'how', 'there']
    words = {word.strip('.,!?;:') for word in lowered.split()}
    if previous_agent and (len(words) <= 8 or words.intersection(follow_up_terms)):
        return {'agent': previous_agent, 'intent': 'continue_conversation'}
    return {'agent': 'concierge', 'intent': 'daily_briefing'}


def create_concierge_run(
    owner,
    *,
    message: str,
    thread: ConversationThread | None = None,
    context: dict[str, Any] | None = None,
) -> AgentRun:
    thread = thread or default_thread(owner)
    ConversationMessage.objects.create(owner=owner, thread=thread, role='user', content=message)
    previous = thread.messages.filter(role='assistant').order_by('-created_at', '-id').first()
    previous_agent = str((previous.metadata or {}).get('agent', '')) if previous else ''
    route = _classify(message, previous_agent=previous_agent)
    run_input: dict[str, Any] = {'message': message, 'intent': route['intent']}

    requested_job_id = (context or {}).get('job_id')
    previous_job_id = (previous.metadata or {}).get('job_id') if previous else None
    lowered = message.lower()
    message_words = {word.strip('.,!?;:') for word in lowered.split()}
    refers_to_previous = bool(message_words.intersection({'it', 'this', 'that', 'why', 'more'}))
    asks_for_ranking = any(term in lowered for term in ['top', 'best', 'strongest'])
    candidate_job_id = requested_job_id or (previous_job_id if refers_to_previous and not asks_for_ranking else None)
    if candidate_job_id and route['agent'] in {'matching', 'documents', 'application'}:
        job = JobPosting.objects.filter(owner=owner, pk=candidate_job_id).only('id').first()
        if job:
            run_input['job_id'] = job.id

    thread.save(update_fields=['updated_at'])
    return AgentRun.objects.create(
        owner=owner,
        thread=thread,
        agent=route['agent'],
        objective=message,
        input=run_input,
        model=text_model(),
    )


def _record_step(run: AgentRun, name: str, handler: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    sequence = run.steps.count() + 1
    step = AgentStep.objects.create(
        owner=run.owner, run=run, sequence=sequence, name=name, status='running', started_at=timezone.now(),
    )
    try:
        output = json.loads(json.dumps(handler(), cls=DjangoJSONEncoder))
        step.status = 'succeeded'
        step.output = output
        return output
    except Exception as exc:
        step.status = 'failed'
        step.error = str(exc)[:2000]
        raise
    finally:
        step.completed_at = timezone.now()
        step.save(update_fields=['status', 'output', 'error', 'completed_at', 'updated_at'])


def _job_from_run(run: AgentRun) -> JobPosting | None:
    job_id = run.input.get('job_id')
    if job_id:
        return JobPosting.objects.filter(owner=run.owner, pk=job_id).first()
    return JobPosting.objects.filter(owner=run.owner).select_related('match').order_by('-match__score').first()


def _approval(run: AgentRun, *, kind: str, title: str, prompt: str, payload: dict[str, Any]) -> ApprovalRequest:
    approval = ApprovalRequest.objects.create(
        owner=run.owner, run=run, kind=kind, title=title, prompt=prompt, payload=payload,
    )
    run.status = 'waiting_approval'
    run.save(update_fields=['status', 'updated_at'])
    publish_user_event(run.owner_id, 'approval_requested', {'approval_id': approval.id, 'run_id': run.id, 'kind': kind})
    return approval


def _handle_profile(run: AgentRun) -> dict[str, Any]:
    health = profile_health(run.owner)
    if health['questions']:
        reply = f"Your profile is {health['completeness']}% complete. The highest-value question is: {health['questions'][0]}"
    else:
        reply = f"Your profile is {health['completeness']}% complete with {health['unverified_count']} facts still awaiting review."
    return {
        'reply': reply,
        'profile_health': health,
        'actions': [{'kind': 'link', 'label': 'Review candidate profile', 'route': '/profile'}],
    }


def _handle_sourcing(run: AgentRun) -> dict[str, Any]:
    sources = list(JobSource.objects.filter(owner=run.owner, enabled=True))
    summaries = []
    for source in sources:
        source_run = SourceRun.objects.create(owner=run.owner, source=source)
        execute_source_run(source_run)
        summaries.append({
            'source': source.name,
            'status': source_run.status,
            'imported': source_run.imported_count,
            'updated': source_run.updated_count,
            'errors': source_run.error_count,
        })
    imported = sum(item['imported'] for item in summaries)
    action = (
        {'kind': 'link', 'label': 'Review ranked opportunities', 'route': '/matches'}
        if sources else {'kind': 'link', 'label': 'Set up job sources', 'route': '/sources'}
    )
    return {
        'reply': f'I refreshed {len(sources)} sources and found {imported} new roles.',
        'source_runs': summaries,
        'actions': [action],
    }


def _handle_matching(run: AgentRun) -> dict[str, Any]:
    briefing = today_briefing(run.owner)
    queue = briefing['review_queue']
    if not queue:
        return {
            'reply': 'There are no fresh scored opportunities yet. Run your sources or import a job, then I can rank the results.',
            'review_queue': [],
            'actions': [{'kind': 'link', 'label': 'Open job sources', 'route': '/sources'}],
        }

    requested_job_id = run.input.get('job_id')
    best = next((item for item in queue if item['id'] == requested_job_id), queue[0])
    job = JobPosting.objects.filter(owner=run.owner, pk=best['id']).select_related('match').first()
    match = getattr(job, 'match', None) if job else None
    explanation = (match.explanation_json or {}) if match else {}
    covered = explanation.get('covered_skills', [])[:4]
    gaps = (match.missing_requirements or [])[:3] if match else []
    location = best['location'] or best['remote_policy'].title() or 'Location not specified'
    evidence = ', '.join(covered) if covered else 'your verified profile evidence'
    risk = ', '.join(gaps) if gaps else 'no material skill gaps identified'
    reply = (
        f"Top recommendation\n{best['title']} at {best['company'] or 'Company not listed'}\n"
        f"{best['score']}% match · {best['eligibility'].title()} eligibility · {best['confidence'].title()} confidence\n\n"
        f"Why it ranks first: {best['summary'] or 'It has the strongest overall alignment in your current review queue.'}\n"
        f"Strongest evidence: {evidence}.\n"
        f"Watch-outs: {risk}.\n"
        f"Location: {location}."
    )
    actions = [
        {'kind': 'link', 'label': 'Review full match', 'route': '/matches', 'job_id': best['id']},
        {
            'kind': 'prompt',
            'label': 'Prepare application materials',
            'prompt': f"Prepare application materials for {best['title']} at {best['company'] or 'this company'}",
            'job_id': best['id'],
        },
    ]
    return {'reply': reply, 'job_id': best['id'], 'review_queue': queue[:5], 'actions': actions}


def _handle_documents(run: AgentRun) -> dict[str, Any]:
    job = _job_from_run(run)
    if not job:
        return {'reply': 'Choose or import a job before preparing application materials.'}
    approval = _approval(
        run,
        kind='prepare_application',
        title=f'Prepare application for {job.title}',
        prompt=f'Create an evidence-backed resume and cover letter for {job.title} at {job.company or "this company"}?',
        payload={'job_id': job.id},
    )
    return {
        'reply': f'I have {job.title} at {job.company or "the company"} and your verified evidence ready. Approve the request on the right before I draft anything.',
        'approval_id': approval.id,
        'job_id': job.id,
    }


def _handle_application(run: AgentRun) -> dict[str, Any]:
    due = today_briefing(run.owner)['due_actions']
    if due:
        return {
            'reply': f"You have {len(due)} follow-up action{'s' if len(due) != 1 else ''} due. Start with {due[0]['title']}.",
            'due_actions': due,
            'actions': [{'kind': 'link', 'label': 'Open application pipeline', 'route': '/pipeline'}],
        }
    job = _job_from_run(run)
    if job:
        approval = _approval(
            run,
            kind='prepare_application',
            title=f'Move {job.title} forward',
            prompt='Approve this opportunity and prepare its application materials?',
            payload={'job_id': job.id},
        )
        return {
            'reply': 'There are no overdue follow-ups. I can move your strongest opportunity forward.',
            'approval_id': approval.id,
            'job_id': job.id,
        }
    return {
        'reply': 'Your pipeline is clear. Import or discover jobs to create the next action.',
        'actions': [{'kind': 'link', 'label': 'Find opportunities', 'route': '/sources'}],
    }


def _handle_concierge(run: AgentRun) -> dict[str, Any]:
    briefing = today_briefing(run.owner)
    queue = briefing['review_queue']
    health = briefing['profile_health']
    summary = (
        f"Current search status\n{briefing['review_count']} roles to review · "
        f"{briefing['pending_approvals']} approvals waiting · {briefing['followups_due']} follow-ups due"
    )
    actions: list[dict[str, Any]] = []
    if briefing['pending_approvals']:
        priority = 'Your first priority is the approval waiting on this page so the paused workflow can continue.'
    elif briefing['followups_due']:
        priority = f"Start with {briefing['due_actions'][0]['title']}; it is already due."
        actions.append({'kind': 'link', 'label': 'Open application pipeline', 'route': '/pipeline'})
    elif queue:
        best = queue[0]
        priority = f"Start by reviewing {best['title']} at {best['company'] or 'the company'}, currently your strongest match at {best['score']}%."
        actions.extend([
            {'kind': 'prompt', 'label': 'Explain the top match', 'prompt': 'Give me the top one please', 'job_id': best['id']},
            {'kind': 'link', 'label': 'Review opportunities', 'route': '/matches'},
        ])
    elif health['questions']:
        priority = f"Improve sourcing quality by answering this profile question: {health['questions'][0]}"
        actions.append({'kind': 'link', 'label': 'Complete candidate profile', 'route': '/profile'})
    else:
        priority = 'Your profile is ready. Refresh your sources to create a ranked review queue.'
        actions.append({'kind': 'link', 'label': 'Open job sources', 'route': '/sources'})
    return {'reply': f'{summary}\n\nRecommended next move: {priority}', 'briefing': briefing, 'actions': actions}


HANDLERS = {
    'profile': _handle_profile,
    'sourcing': _handle_sourcing,
    'matching': _handle_matching,
    'application': _handle_application,
    'documents': _handle_documents,
    'concierge': _handle_concierge,
}


def execute_agent_run(run: AgentRun) -> AgentRun:
    if run.status in {'succeeded', 'cancelled'}:
        return run
    run.status = 'running'
    run.started_at = run.started_at or timezone.now()
    run.save(update_fields=['status', 'started_at', 'updated_at'])
    publish_user_event(run.owner_id, 'agent_run_started', {'run_id': run.id, 'agent': run.agent})
    try:
        output = _record_step(run, f'{run.agent}.execute', lambda: HANDLERS[run.agent](run))
        run.output = output
        if run.status != 'waiting_approval':
            run.status = 'succeeded'
            run.completed_at = timezone.now()
        if run.thread and output.get('reply'):
            metadata = {'run_id': run.id, 'agent': run.agent}
            for key in ('job_id', 'actions', 'approval_id'):
                if output.get(key) is not None:
                    metadata[key] = output[key]
            ConversationMessage.objects.create(
                owner=run.owner, thread=run.thread, role='assistant', content=output['reply'], metadata=metadata,
            )
            run.thread.save(update_fields=['updated_at'])
    except Exception as exc:
        run.status = 'failed'
        run.error = str(exc)[:4000]
        run.completed_at = timezone.now()
        if run.thread:
            ConversationMessage.objects.create(
                owner=run.owner, thread=run.thread, role='assistant',
                content='I could not complete that workflow. The failure was recorded so it can be retried safely.',
                metadata={'run_id': run.id, 'error': run.error},
            )
    run.save()
    publish_user_event(run.owner_id, 'agent_run_updated', {'run_id': run.id, 'agent': run.agent, 'status': run.status})
    return run


@transaction.atomic
def decide_approval(approval: ApprovalRequest, *, approved: bool, response: dict[str, Any] | None = None) -> ApprovalRequest:
    if approval.status != 'pending':
        return approval
    approval.status = 'approved' if approved else 'rejected'
    approval.response = response or {}
    approval.decided_at = timezone.now()
    approval.save(update_fields=['status', 'response', 'decided_at', 'updated_at'])
    run = approval.run
    if not approved:
        if run:
            run.status = 'cancelled'
            run.completed_at = timezone.now()
            run.save(update_fields=['status', 'completed_at', 'updated_at'])
        return approval

    if approval.kind == 'prepare_application':
        job = JobPosting.objects.get(owner=approval.owner, pk=approval.payload['job_id'])
        application, _ = Application.objects.get_or_create(
            owner=approval.owner, job=job, defaults={'status': 'preparing'},
        )
        application.status = 'preparing'
        application.save(update_fields=['status', 'updated_at'])
        materials = prepare_application_materials(approval.owner, job, application=application)
        ApplicationEvent.objects.create(
            owner=approval.owner, application=application, event_type='materials_prepared',
            happened_at=timezone.now(), notes='Resume and cover letter drafts prepared after user approval.',
            metadata={'resume_id': materials['resume'].id, 'cover_letter_id': materials['cover_letter'].id},
        )
        if run:
            run.output = {**(run.output or {}), 'application_id': application.id, 'resume_id': materials['resume'].id, 'cover_letter_id': materials['cover_letter'].id}
    elif approval.kind == 'verify_fact':
        fact = ProfileFact.objects.get(owner=approval.owner, pk=approval.payload['fact_id'])
        fact.verified_by_user = True
        fact.lifecycle = 'verified'
        fact.save(update_fields=['verified_by_user', 'lifecycle', 'updated_at'])
    elif approval.kind == 'render_bundle':
        application = Application.objects.get(owner=approval.owner, pk=approval.payload['application_id'])
        artifacts = render_application_bundle(approval.owner, application=application)
        if run:
            run.output = {**(run.output or {}), 'artifact_ids': [artifact.id for artifact in artifacts]}

    if run:
        run.status = 'succeeded'
        run.completed_at = timezone.now()
        run.save(update_fields=['status', 'output', 'completed_at', 'updated_at'])
    publish_user_event(approval.owner_id, 'approval_decided', {'approval_id': approval.id, 'status': approval.status})
    return approval
