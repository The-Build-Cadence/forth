from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from core.domain.material_preferences import readable_match_summary
from core.domain.profiles import profile_health, candidate_profile
from core.models import Application, ApprovalRequest, JobPosting, SourceRun, ProfileDocument
from core.serializers import SourceRunSerializer


def today_briefing(owner) -> dict:
    now = timezone.now()
    queue = list(
        JobPosting.objects.filter(owner=owner, freshness_status='fresh')
        .select_related('match')
        .exclude(applications__status__in=['applied', 'rejected', 'archived'])
        .order_by('-match__score', '-discovered_at')[:8]
    )
    due = list(
        Application.objects.filter(owner=owner, follow_up_at__lte=now)
        .exclude(status__in=['rejected', 'archived', 'offer'])
        .select_related('job')[:5]
    )
    stale_cutoff = now - timedelta(days=10)
    profile = candidate_profile(owner)
    run = SourceRun.objects.filter(owner=owner, source__kind='brave').first()
    draft = Application.objects.filter(owner=owner, job__materials_status='ready').exclude(status__in=['applied', 'rejected', 'archived']).first()
    next_action = {'title': 'Find your next opportunity', 'detail': 'Search using your saved roles, location and work preferences.', 'label': 'Find jobs for me', 'path': '/sources'}
    if not profile.onboarding_completed_at:
        next_action = {'title': 'Make Forth your own', 'detail': 'Add your experience and a few preferences to get started.', 'label': 'Continue setup', 'path': '/start'}
    elif due:
        next_action = {'title': 'Keep the conversation moving', 'detail': 'You have an application follow-up due.', 'label': 'Review follow-ups', 'path': '/pipeline'}
    elif draft:
        next_action = {'title': 'Your application draft is ready', 'detail': 'Review the wording and confirm the details before downloading.', 'label': 'Review documents', 'path': '/resume-lab', 'params': {'job': draft.job_id}}
    elif queue:
        next_action = {'title': 'Take a look at your matches', 'detail': 'See why each role fits and choose where to focus.', 'label': 'Review jobs', 'path': '/matches'}
    elif run and run.status in ['queued', 'running']:
        next_action = {'title': 'Finding jobs for you', 'detail': 'Your search is running. You can leave this page and come back.', 'label': 'View search progress', 'path': '/sources'}
    return {
        'next_action': next_action,
        'setup_complete': bool(profile.onboarding_completed_at),
        'has_resume': ProfileDocument.objects.filter(owner=owner, kind='resume', status='ready').exists(),
        'search_run': SourceRunSerializer(run).data if run else None,
        'greeting': 'Your search, distilled to the decisions that matter.',
        'profile_health': profile_health(owner),
        'pending_approvals': ApprovalRequest.objects.filter(owner=owner, status='pending').count(),
        'review_count': len(queue),
        'followups_due': len(due),
        'aging_jobs': JobPosting.objects.filter(owner=owner, discovered_at__lte=stale_cutoff, freshness_status='fresh').count(),
        'review_queue': [
            {
                'id': job.id,
                'title': job.title,
                'company': job.company,
                'location': job.location,
                'remote_policy': job.remote_policy,
                'freshness_status': job.freshness_status,
                'discovered_at': job.discovered_at,
                'score': getattr(getattr(job, 'match', None), 'score', 0),
                'confidence': getattr(getattr(job, 'match', None), 'confidence', 'low'),
                'eligibility': getattr(getattr(job, 'match', None), 'hard_filter_status', 'uncertain'),
                'summary': readable_match_summary((getattr(getattr(job, 'match', None), 'explanation_json', {}) or {}).get('summary', '')),
            }
            for job in queue
        ],
        'due_actions': [
            {
                'application_id': application.id,
                'title': f'Follow up with {application.job.company or application.job.title}',
                'detail': application.job.title,
                'due_at': application.follow_up_at,
            }
            for application in due
        ],
    }

