from __future__ import annotations

import re
from typing import Any

from django.db import transaction

from core.ai import detect_skills, keywords
from core.domain.embeddings import (
    nearest_profile_facts,
    profile_job_similarity,
    refresh_job_embedding,
    refresh_profile_embedding,
    vector_similarity,
)
from core.domain.profiles import matching_facts, profile_context
from core.models import JobMatch, JobPosting, MatchSignal, ProfileFact
from core.domain.scoring import normalize_match_score


WEIGHTS = {
    'skills': 15,
    'evidence': 20,
    'semantic': 35,
    'direction': 15,
    'domain': 5,
    'logistics': 10,
}


# The job extractor may legitimately return a requirement sentence (for example,
# "In-depth experience with TypeScript, Python, and AI-native software
# development") rather than a single technology.  These concepts let matching
# retain the useful non-technology parts of that sentence without treating the
# complete sentence as an indivisible skill.
CAPABILITY_PATTERNS = {
    'engineering management': ('engineering management', 'engineering-management', 'engineering manager', 'manage engineers'),
    'technical leadership': ('technical leadership', 'technical direction', 'technical decision'),
    'full-stack development': ('full-stack', 'full stack'),
    'web applications': ('web application', 'web app', 'frontend', 'front-end'),
    'software architecture': ('software architecture', 'system architecture', 'architecture'),
    'ai platform development': ('ai platform', 'ai-native', 'applied ai'),
    'llm evaluation': ('llm evaluation', 'llm eval', 'evals pipeline', 'test harness'),
}

CAPABILITY_EVIDENCE = {
    'engineering management': ('engineering management', 'engineering manager', 'engineering team lead', 'team lead', 'led a team', 'lead a team'),
    'technical leadership': ('technical leadership', 'technical direction', 'technical decision', 'system design'),
    'full-stack development': ('full-stack', 'full stack', 'front-end', 'frontend', 'backend'),
    'web applications': ('web application', 'application development', 'front-end', 'frontend', 'large websites'),
    'software architecture': ('software architecture', 'system architecture', 'application architecture', 'system design', 'architecture'),
    'ai platform development': ('ai platform', 'ai-native', 'applied ai'),
    'llm evaluation': ('llm evaluation', 'llm eval', 'evals pipeline', 'test harness'),
}

# These are narrow, technically inherent relationships rather than fuzzy
# keyword associations.  They help a profile that says “Django” receive
# appropriate partial credit for Python, while still preserving the distinction
# between what was written and what the matcher can safely infer.
IMPLICIT_CAPABILITY_EVIDENCE = {
    'python': ('django', 'django rest framework', 'drf', 'flask', 'fastapi', 'celery'),
}

MANAGEMENT_TITLE_TOKENS = {'manager', 'management', 'lead', 'leader', 'head', 'director', 'principal'}


def _contains(blob: str, value: str) -> bool:
    return bool(value and re.search(rf'(?<!\w){re.escape(value.lower())}(?!\w)', blob.lower()))


def _contains_any(blob: str, values: tuple[str, ...]) -> bool:
    return any(_contains(blob, value) for value in values)


def _normalized_requirements(job: JobPosting) -> list[dict[str, Any]]:
    """Split extracted requirement prose into matchable atomic capabilities.

    We preserve whether the source called a capability required or preferred.
    A preferred item can improve a score, but an absence must not be presented
    as a hard gap.
    """
    requirements: dict[str, dict[str, Any]] = {}
    for requirement in job.requirements.filter(category='skill'):
        text = requirement.text or requirement.normalized_value
        # "AI" alone is too broad to be meaningful evidence, and AI-native
        # wording is represented by the more specific capability below.
        names = [skill.lower() for skill in detect_skills(text) if skill.lower() != 'ai']
        lowered = text.lower()
        names.extend(
            name for name, patterns in CAPABILITY_PATTERNS.items()
            if _contains_any(lowered, patterns)
        )
        # A short, atomic extracted value still has value even when it is not
        # in the local technology vocabulary.
        if not names and len(keywords(text, limit=8)) <= 3:
            names.append((requirement.normalized_value or text).lower())
        for name in dict.fromkeys(names):
            existing = requirements.get(name)
            candidate = {
                'name': name,
                'required': requirement.kind == 'required' or requirement.is_hard,
                'source_text': text,
            }
            if existing:
                existing['required'] = existing['required'] or candidate['required']
            else:
                requirements[name] = candidate
    return list(requirements.values())


def _requirement_supported(blob: str, name: str) -> bool:
    aliases = CAPABILITY_EVIDENCE.get(name)
    return _contains_any(blob, aliases) if aliases else _contains(blob, name)


def _requirement_support_kind(blob: str, name: str) -> str | None:
    """Return whether verified evidence states or safely implies a capability."""
    if _requirement_supported(blob, name):
        return 'direct'
    if _contains_any(blob, IMPLICIT_CAPABILITY_EVIDENCE.get(name, ())):
        return 'inferred'
    return None


def _inference_explanation(name: str) -> str:
    if name == 'python':
        return 'Django/DRF/Flask/FastAPI/Celery experience is Python-framework evidence.'
    return 'Supported by a narrowly defined technical implication in verified evidence.'


def _role_direction_score(title: str, targets: list[str]) -> int:
    """Score title direction while recognizing closely related leadership roles."""
    if not targets:
        return 55
    title_tokens = set(keywords(title, limit=20))
    target_tokens = set(keywords(' '.join(targets), limit=60))
    lexical = 100 * len(title_tokens & target_tokens) / max(1, len(title_tokens))
    title_is_management = bool(title_tokens & MANAGEMENT_TITLE_TOKENS)
    target_is_management = bool(target_tokens & MANAGEMENT_TITLE_TOKENS)
    if 'engineering' in title_tokens and 'engineering' in target_tokens and title_is_management and target_is_management:
        return max(round(lexical), 82)
    return round(lexical)


def _compensation_floor(value: str) -> int | None:
    numbers = [int(raw.replace(',', '')) for raw in re.findall(r'\b(\d{2,3}(?:,\d{3})?)\b', value or '')]
    numbers = [number * 1000 if number < 1000 else number for number in numbers]
    return min(numbers) if numbers else None


def eligibility(job: JobPosting, context: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    profile = context['profile']
    failures: list[str] = []
    uncertainties: list[str] = []
    company = job.company.lower()
    if any(str(item).lower() in company for item in profile.get('excluded_companies', [])):
        failures.append('Company is on the exclusion list.')
    work_modes = [str(item).lower() for item in profile.get('work_modes', [])]
    if work_modes and job.remote_policy not in work_modes and job.remote_policy != 'unknown':
        strong_mode = any(
            pref['category'] == 'work_mode' and pref['importance'] == 'must'
            for pref in context['preferences']
        )
        (failures if strong_mode else uncertainties).append(f'{job.remote_policy.title()} work may not match the preferred work mode.')
    minimum = profile.get('minimum_compensation')
    offered = _compensation_floor(job.compensation)
    if minimum and offered and offered < minimum:
        failures.append(f'Visible compensation is below the {minimum:,} minimum.')
    elif minimum and not offered:
        uncertainties.append('Compensation is not visible.')
    if profile.get('authorized_countries') and not job.location:
        uncertainties.append('Work location or authorization requirement is unclear.')
    status = 'fail' if failures else 'uncertain' if uncertainties else 'pass'
    return status, failures, uncertainties


def _signal(kind: str, label: str, score: int, explanation: str, evidence: list[Any]) -> dict[str, Any]:
    return {
        'kind': kind,
        'label': label,
        'score': max(0, min(100, round(score))),
        'weight': WEIGHTS.get(kind, 0),
        'explanation': explanation,
        'evidence': evidence,
    }


@transaction.atomic
def recompute_match(job: JobPosting) -> JobMatch:
    context = profile_context(job.owner)
    profile = refresh_profile_embedding(job.owner)
    job = refresh_job_embedding(job)
    facts = list(matching_facts(job.owner).order_by('-verified_by_user', 'fact_type', 'title')[:250])
    fact_text = '\n'.join(f'{fact.title}: {fact.statement}' for fact in facts)
    # Direct capability coverage must be grounded in confirmed evidence.  We
    # still use all facts for semantic retrieval, allowing the UI to show
    # relevant but unconfirmed context without overstating a match.
    verified_profile_blob = '\n'.join(
        f'{fact.title}: {fact.statement}' for fact in facts
        if fact.verified_by_user or fact.lifecycle == 'verified'
    ).lower()
    job_blob = job.description_text.lower()
    requirements = _normalized_requirements(job)
    if not requirements:
        requirements = [
            {'name': skill.lower(), 'required': True, 'source_text': skill}
            for skill in detect_skills(job.description_text)
        ]
    required_requirements = [item for item in requirements if item['required']]
    preferred_requirements = [item for item in requirements if not item['required']]
    support_kinds = {
        item['name']: _requirement_support_kind(verified_profile_blob, item['name'])
        for item in requirements
    }
    covered_requirements = [item for item in requirements if support_kinds[item['name']]]
    covered = [item['name'] for item in covered_requirements]
    # Only unmet required capabilities are visible gaps. Preferred capabilities
    # are recorded separately, so candidates are not penalized as though a nice
    # to have were an eligibility condition.
    missing = [
        item['name'] for item in required_requirements
        if item['name'] not in covered
    ]
    preferred_gaps = [
        item['name'] for item in preferred_requirements
        if item['name'] not in covered
    ]
    def coverage_score(items: list[dict[str, Any]]) -> float:
        # Inferred framework knowledge is useful signal, but direct evidence
        # remains the stronger and more transparent match.
        points = sum(1 if support_kinds[item['name']] == 'direct' else .75 if support_kinds[item['name']] == 'inferred' else 0 for item in items)
        return 100 * points / max(1, len(items))

    required_score = coverage_score(required_requirements)
    preferred_score = coverage_score(preferred_requirements) if preferred_requirements else 100
    skill_score = round(required_score * 0.85 + preferred_score * 0.15)

    supporting_by_id: dict[int, dict[str, Any]] = {}
    for fact in facts:
        fact_blob = f'{fact.title} {fact.statement} {fact.evidence_quote}'
        overlap = [skill for skill in covered if _requirement_support_kind(fact_blob, skill)]
        if overlap:
            inferred_skills = [
                skill for skill in overlap
                if _requirement_support_kind(fact_blob, skill) == 'inferred'
            ]
            supporting_by_id[fact.id] = {
                'fact_id': fact.id,
                'title': fact.title,
                'statement': fact.statement,
                'skills': overlap,
                'verified': fact.verified_by_user or fact.lifecycle == 'verified',
                'inferred_skills': inferred_skills,
                'match_basis': 'framework-inferred capability evidence' if inferred_skills else 'skill evidence',
            }
    for fact in nearest_profile_facts(job.owner, job.semantic_embedding, limit=12):
        similarity = vector_similarity(fact.semantic_embedding, job.semantic_embedding)
        if similarity < 0.18:
            continue
        existing = supporting_by_id.get(fact.id)
        if existing:
            existing['semantic_similarity'] = round(similarity * 100)
            existing['match_basis'] = 'skill and semantic evidence'
            continue
        supporting_by_id[fact.id] = {
            'fact_id': fact.id,
            'title': fact.title,
            'statement': fact.statement,
            'skills': [],
            'verified': fact.verified_by_user or fact.lifecycle == 'verified',
            'semantic_similarity': round(similarity * 100),
            'match_basis': 'semantic evidence',
        }
    supporting = sorted(
        supporting_by_id.values(),
        key=lambda fact: (-int(fact['verified']), -fact.get('semantic_similarity', 0), fact['title'].lower()),
    )
    verified_support = [fact for fact in supporting if fact['verified']]
    direct_evidence = [fact for fact in supporting if fact['skills']]
    verified_direct_evidence = [fact for fact in direct_evidence if fact['verified']]
    # Semantic neighbours are helpful context, but cannot on their own saturate
    # the evidence signal. Direct, verified capability evidence carries most of
    # the score.
    evidence_score = min(
        100,
        20 + len(direct_evidence) * 8 + len(verified_direct_evidence) * 12
        + min(20, len(verified_support) * 2),
    )

    targets = [str(value).lower() for value in context['profile'].get('target_roles', [])]
    direction_score = _role_direction_score(job.title, targets)

    industries = [str(value).lower() for value in context['profile'].get('target_industries', [])]
    domain_score = 80 if any(value in job_blob or value in job.company.lower() for value in industries) else 55 if industries else 60

    hard_status, failures, uncertainties = eligibility(job, context)
    logistics_score = 100 if hard_status == 'pass' else 60 if hard_status == 'uncertain' else 0

    semantic_similarity = profile_job_similarity(profile, job)
    verified_fact_similarities = [
        vector_similarity(fact.semantic_embedding, job.semantic_embedding)
        for fact in facts
        if (fact.verified_by_user or fact.lifecycle == 'verified') and fact.semantic_embedding is not None
    ]
    verified_fact_similarities.sort(reverse=True)
    top_fact_similarity = (
        sum(verified_fact_similarities[:5]) / len(verified_fact_similarities[:5])
        if verified_fact_similarities else 0.0
    )
    # Overall direction and the strongest verified evidence both contribute to
    # semantic fit. Literal capability coverage remains a smaller cross-check.
    blended_semantic_similarity = semantic_similarity * 0.6 + top_fact_similarity * 0.4
    # Embedding cosine values occupy a narrower range than percentages. Treat
    # 0.15 as effectively unrelated and 0.65 as a very strong semantic match,
    # while retaining the raw values in explanation_json for auditability.
    calibrated_semantic_similarity = max(0.0, min(1.0, (blended_semantic_similarity - 0.15) / 0.5))
    semantic_score = round(calibrated_semantic_similarity * 100)

    signals = [
        _signal(
            'skills',
            'Required and preferred capabilities',
            skill_score,
            f'{sum(item["name"] in covered for item in required_requirements)} of {len(required_requirements)} required and '
            f'{sum(item["name"] in covered for item in preferred_requirements)} of {len(preferred_requirements)} preferred capabilities are supported.',
            covered,
        ),
        _signal('evidence', 'Experience evidence', evidence_score, f'{len(direct_evidence)} facts directly support role capabilities; {len(verified_direct_evidence)} are verified.', supporting[:12]),
        _signal(
            'semantic',
            'Whole-profile semantic fit',
            semantic_score,
            'Cosine similarity blending the complete profile and the strongest verified evidence against the normalized job profile.',
            [{
                'candidate_embedding_model': profile.embedding_model,
                'job_embedding_model': job.embedding_model,
                'candidate_provider': profile.embedding_provider,
                'job_provider': job.embedding_provider,
            }],
        ),
        _signal('direction', 'Role direction', direction_score, 'Alignment with the candidate’s stated target roles.', context['profile'].get('target_roles', [])),
        _signal('domain', 'Domain relevance', domain_score, 'Alignment with target industries and prior domain evidence.', industries),
        _signal('logistics', 'Logistics', logistics_score, 'Location, work mode, compensation, and exclusions.', failures + uncertainties),
    ]
    weighted = sum(signal['score'] * signal['weight'] for signal in signals) / 100
    score = round(weighted)
    if hard_status == 'fail':
        score = min(score, 39)
    elif hard_status == 'uncertain':
        score = min(score, 84)
    confidence_points = len(verified_support) * 2 + len(facts) / 10 + (10 if job.requirements.exists() else 0)
    confidence = 'high' if confidence_points >= 24 else 'medium' if confidence_points >= 10 else 'low'
    summary = (
        f'{"Strong" if score >= 80 else "Promising" if score >= 65 else "Possible" if score >= 50 else "Low"} fit: '
        f'{len(covered)} supported capabilities, {len(missing)} required gaps, '
        f'{len(preferred_gaps)} preferred gaps. '
        + {'pass': 'Matches your required conditions.', 'fail': 'Conflicts with your required conditions.',
           'uncertain': 'Some required conditions need confirmation.'}[hard_status]
    )
    explanation = {
        'summary': summary,
        'covered_skills': covered,
        'job_skills': [item['name'] for item in requirements],
        'required_capabilities': [item['name'] for item in required_requirements],
        'preferred_capabilities': [item['name'] for item in preferred_requirements],
        'preferred_gaps': preferred_gaps,
        'inferred_capabilities': [
            {
                'capability': item['name'],
                'basis': _inference_explanation(item['name']),
                'credit': 'partial',
            }
            for item in covered_requirements
            if support_kinds[item['name']] == 'inferred'
        ],
        'eligibility_failures': failures,
        'eligibility_uncertainties': uncertainties,
        'semantic_similarity': round(semantic_similarity, 4),
        'top_evidence_similarity': round(top_fact_similarity, 4),
        'blended_semantic_similarity': round(blended_semantic_similarity, 4),
        'calibrated_semantic_similarity': round(calibrated_semantic_similarity, 4),
        'embedding_model': job.embedding_model,
        'embedding_provider': job.embedding_provider,
        'signals': signals,
        'score_version': '2026-10-v6-grounded-inference',
    }
    # Keep the raw score as the source of truth. The calibrated score makes the
    # profile's chosen ready-to-apply threshold visually consistent at 80.
    explanation['normalized_score'] = normalize_match_score(score, context['profile'].get('minimum_match_score'))
    explanation['profile_minimum_score'] = context['profile'].get('minimum_match_score', 50)
    match, _ = JobMatch.objects.update_or_create(
        owner=job.owner,
        job=job,
        defaults={
            'score': max(0, min(100, score)),
            'hard_filter_status': hard_status,
            'explanation_json': explanation,
            'missing_requirements': missing,
            'supporting_facts': supporting[:16],
            'confidence': confidence,
        },
    )
    MatchSignal.objects.filter(match=match).delete()
    MatchSignal.objects.bulk_create([
        MatchSignal(owner=job.owner, match=match, **signal) for signal in signals
    ])
    return match
