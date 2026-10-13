from __future__ import annotations

import re
import uuid
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.ai import clean_text, generate_json
from core.domain.matching import recompute_match
from core.domain.profiles import matching_facts
from core.models import JobPosting, ProfileFact, ProfileImprovementProposal


PROPOSAL_SCHEMA = {
    'name': 'profile_improvement_proposals',
    'schema': {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'suggestions': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'properties': {
                        'fact_id': {'type': 'integer'},
                        'proposed_statement': {'type': 'string'},
                        'rationale': {'type': 'string'},
                        'target_requirements': {'type': 'array', 'items': {'type': 'string'}},
                    },
                    'required': ['fact_id', 'proposed_statement', 'rationale', 'target_requirements'],
                },
            },
        },
        'required': ['suggestions'],
    },
}


def _numbers(value: str) -> set[str]:
    return set(re.findall(r'\b\d+(?:[.,]\d+)*%?\b', value or ''))


def _contains(blob: str, value: str) -> bool:
    return bool(value and re.search(rf'(?<!\w){re.escape(value.lower())}(?!\w)', blob.lower()))


def _can_safely_name_capability(fact: ProfileFact, capability: str) -> bool:
    """Allow only explicit evidence or unavoidable framework implications."""
    evidence = f'{fact.title} {fact.statement} {fact.evidence_quote}'.lower()
    normalized = clean_text(capability).lower()
    if _contains(evidence, normalized):
        return True
    # Django is a Python framework; naming Python clarifies, rather than adds,
    # the technology already substantiated by the fact.  APIs are deliberately
    # excluded: Django alone does not establish API implementation experience.
    return normalized == 'python' and any(_contains(evidence, value) for value in (
        'django', 'django rest framework', 'drf', 'flask', 'fastapi', 'celery',
    ))


def _fallback_suggestions(facts: list[ProfileFact], supporting: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Produce conservative suggestions when the configured text model is unavailable."""
    facts_by_id = {fact.id: fact for fact in facts}
    suggestions = []
    for support in supporting:
        fact = facts_by_id.get(support.get('fact_id'))
        skills = [clean_text(skill) for skill in support.get('skills', []) if clean_text(skill)]
        if not fact or not skills:
            continue
        prefix = ', '.join(dict.fromkeys(skills[:4]))
        proposed = f'{prefix}: {fact.statement}'
        suggestions.append({
            'fact_id': fact.id,
            'proposed_statement': proposed,
            'rationale': f'Lead with the verified capabilities this role asks for: {prefix}.',
            'target_requirements': skills[:4],
        })
        if len(suggestions) == 5:
            break
    return suggestions


def _validated_suggestions(
    raw_suggestions: list[dict[str, Any]],
    facts: list[ProfileFact],
) -> list[dict[str, Any]]:
    facts_by_id = {fact.id: fact for fact in facts}
    suggestions = []
    used_fact_ids: set[int] = set()
    for raw in raw_suggestions[:8]:
        try:
            fact_id = int(raw.get('fact_id'))
        except (TypeError, ValueError):
            continue
        fact = facts_by_id.get(fact_id)
        proposed = clean_text(raw.get('proposed_statement', ''))
        if not fact or fact_id in used_fact_ids or not proposed or proposed == clean_text(fact.statement):
            continue
        # Rewording may clarify an existing claim, but must never manufacture a
        # metric that is absent from both the fact and its source quotation.
        grounded_numbers = _numbers(f'{fact.statement} {fact.evidence_quote}')
        if not _numbers(proposed).issubset(grounded_numbers):
            continue
        target_requirements = [
            clean_text(item) for item in raw.get('target_requirements', [])[:8]
            if clean_text(item)
        ]
        # A proposal may make a directly stated capability (or Python implied
        # by a named Python framework) clearer, but cannot promote an inferred
        # adjacency such as “Django” into an unproven API claim.
        introduced_capabilities = [
            capability for capability in target_requirements
            if _contains(proposed, capability) and not _can_safely_name_capability(fact, capability)
        ]
        if introduced_capabilities:
            continue
        suggestions.append({
            'id': uuid.uuid4().hex,
            'fact_id': fact.id,
            'fact_title': fact.title,
            'current_statement': fact.statement,
            'proposed_statement': proposed[:3000],
            'rationale': clean_text(raw.get('rationale', ''))[:1000],
            'target_requirements': target_requirements,
        })
        used_fact_ids.add(fact_id)
        if len(suggestions) == 6:
            break
    return suggestions


def propose_profile_improvements(job: JobPosting) -> ProfileImprovementProposal:
    match = getattr(job, 'match', None) or recompute_match(job)
    facts = list(
        matching_facts(job.owner)
        .filter(verified_by_user=True)
        .order_by('-confidence', 'fact_type', 'id')[:80]
    )
    fact_payload = [
        {
            'id': fact.id,
            'type': fact.fact_type,
            'title': fact.title,
            'statement': fact.statement,
            'source_evidence': fact.evidence_quote,
        }
        for fact in facts
    ]
    generated = generate_json(
        (
            'You are an evidence-preserving career profile editor. Propose clearer wording for existing, '
            'verified profile facts so genuinely relevant experience is easier to recognize for the target job. '
            'Never invent a skill, responsibility, employer, date, scope, outcome, or metric. Focus on required '
            'capabilities that are missing or present only implicitly. Never turn adjacent experience into a claimed '
            'requirement: Django may be clarified as Python-framework experience, but do not claim API/REST work from '
            'Django alone. Keep every claim supported by the original statement or source evidence. Return at most six '
            'useful changes; return an empty list when no safe improvement exists.'
        ),
        (
            f'Target job: {job.title} at {job.company}\n'
            f'Job description:\n{job.description_text[:10000]}\n\n'
            f'Current required gaps: {match.missing_requirements}\n'
            f'Covered capabilities: {match.explanation_json.get("covered_skills", [])}\n'
            f'Partially credited inferred capabilities (make wording explicit only when safe): '
            f'{match.explanation_json.get("inferred_capabilities", [])}\n'
            f'Current supporting evidence: {match.supporting_facts[:16]}\n\n'
            f'Verified facts available to reword:\n{fact_payload}'
        ),
        PROPOSAL_SCHEMA,
    )
    raw_suggestions = generated.data.get('suggestions', []) if generated else []
    if not raw_suggestions:
        raw_suggestions = _fallback_suggestions(facts, match.supporting_facts)
    suggestions = _validated_suggestions(raw_suggestions, facts)

    ProfileImprovementProposal.objects.filter(
        owner=job.owner, job=job, status='pending',
    ).update(status='superseded')
    return ProfileImprovementProposal.objects.create(
        owner=job.owner,
        job=job,
        source_score=match.score,
        suggestions=suggestions,
    )


@transaction.atomic
def apply_profile_improvements(
    proposal: ProfileImprovementProposal,
    accepted_suggestion_ids: list[str],
) -> list[int]:
    if proposal.status != 'pending':
        raise ValueError('This proposal has already been decided.')
    accepted_ids = {str(value) for value in accepted_suggestion_ids}
    accepted = [item for item in proposal.suggestions if item.get('id') in accepted_ids]
    applied_fact_ids: list[int] = []

    for suggestion in accepted:
        fact = ProfileFact.objects.select_for_update().filter(
            owner=proposal.owner, pk=suggestion.get('fact_id'), verified_by_user=True,
        ).first()
        if not fact:
            continue
        if clean_text(fact.statement) != clean_text(suggestion.get('current_statement', '')):
            raise ValueError(f'“{fact.title}” changed after this proposal was generated. Generate a fresh proposal.')
        history = list(fact.metadata.get('wording_history', []))
        history.append({
            'previous_statement': fact.statement,
            'job_id': proposal.job_id,
            'proposal_id': proposal.id,
            'changed_at': timezone.now().isoformat(),
        })
        fact.statement = suggestion['proposed_statement']
        fact.metadata = {**fact.metadata, 'wording_history': history[-20:]}
        fact.save(update_fields=['statement', 'metadata', 'updated_at'])
        applied_fact_ids.append(fact.id)

    proposal.status = 'applied' if applied_fact_ids else 'rejected'
    proposal.decision = {
        'accepted_suggestion_ids': [item['id'] for item in accepted if item.get('fact_id') in applied_fact_ids],
        'rejected_suggestion_ids': [item['id'] for item in proposal.suggestions if item.get('id') not in accepted_ids],
        'applied_fact_ids': applied_fact_ids,
    }
    proposal.applied_at = timezone.now() if applied_fact_ids else None
    proposal.save(update_fields=['status', 'decision', 'applied_at', 'updated_at'])
    return applied_fact_ids
