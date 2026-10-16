from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from core.domain.material_preferences import readable_match_summary
from core.domain.profiles import profile_health
from core.models import Application, ApprovalRequest, JobPosting


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
    return {
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

