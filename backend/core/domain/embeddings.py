from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.conf import settings
from django.db import connection
from django.utils import timezone
from pgvector.django import CosineDistance

from core.ai import clean_text, cosine_similarity, embed_text_result, stable_hash
from core.models import CandidatePreference, CandidateProfile, JobPosting, ProfileFact
from core.domain.profiles import matching_facts


def _line(label: str, value: Any) -> str:
    if isinstance(value, (list, tuple)):
        value = ', '.join(clean_text(item) for item in value if clean_text(item))
    value = clean_text(value)
    return f'{label}: {value}' if value else ''


def profile_embedding_text(owner) -> str:
    """Build the canonical, evidence-rich candidate profile used for retrieval."""
    profile, _ = CandidateProfile.objects.get_or_create(owner=owner)
    sections = [
        _line('Professional headline', profile.headline),
        _line('Professional summary', profile.professional_summary),
        _line('Target roles', profile.target_roles),
        _line('Target industries', profile.target_industries),
        _line('Location', profile.location),
        _line('Authorized countries', profile.authorized_countries),
        _line('Preferred work modes', profile.work_modes),
        _line('Employment types', profile.employment_types),
        _line(
            'Minimum compensation',
            f'{profile.compensation_currency} {profile.minimum_compensation}' if profile.minimum_compensation else '',
        ),
    ]
    facts = matching_facts(owner).order_by(
        '-verified_by_user', '-confidence', 'fact_type', 'id',
    )[:250]
    if facts:
        sections.append('Candidate evidence:')
        sections.extend(
            f'- {fact.get_fact_type_display()}: {fact.title}. {clean_text(fact.statement)}'
            for fact in facts
        )
    preferences = CandidatePreference.objects.filter(owner=owner).order_by('category', 'label')[:100]
    if preferences:
        sections.append('Candidate preferences and constraints:')
        sections.extend(
            f'- {preference.category} ({preference.importance}): {preference.label}'
            for preference in preferences
        )
    return '\n'.join(section for section in sections if section).strip()


def job_embedding_text(job: JobPosting) -> str:
    """Build the normalized job profile embedded for matching and search."""
    sections = [
        _line('Job title', job.title),
        _line('Company', job.company),
        _line('Location', job.location),
        _line('Work mode', job.remote_policy if job.remote_policy != 'unknown' else ''),
        _line('Seniority', job.seniority),
        _line('Compensation', job.compensation),
    ]
    requirements = list(job.requirements.all().order_by('-is_hard', 'kind', '-weight', 'id'))
    if requirements:
        sections.append('Requirements and responsibilities:')
        sections.extend(
            f'- {requirement.kind} {requirement.category}: {clean_text(requirement.text)}'
            for requirement in requirements
        )
    sections.extend(['Job description:', clean_text(job.description_text)])
    return '\n'.join(section for section in sections if section).strip()


def fact_embedding_text(fact: ProfileFact) -> str:
    return '\n'.join(filter(None, [
        _line('Evidence type', fact.get_fact_type_display()),
        _line('Title', fact.title),
        _line('Statement', fact.statement),
        _line('User notes', fact.user_notes),
    ]))


def _desired_hash(text: str) -> str:
    model = getattr(settings, 'OPENAI_EMBEDDING_MODEL', 'text-embedding-3-large')
    dimensions = int(getattr(settings, 'OPENAI_EMBEDDING_DIMENSIONS', 3072))
    return stable_hash(f'{model}:{dimensions}:{text}')


def _has_current_embedding(instance, content_hash: str) -> bool:
    return bool(instance.semantic_embedding is not None and instance.embedding_content_hash == content_hash)


def _save_embedding(instance, text: str, *, force: bool = False):
    content_hash = _desired_hash(text)
    if not text:
        return instance
    if not force and _has_current_embedding(instance, content_hash):
        return instance
    result = embed_text_result(text)
    instance.semantic_embedding = result.vector
    instance.embedding_model = result.model
    instance.embedding_provider = result.provider
    instance.embedding_content_hash = content_hash
    instance.embedding_updated_at = timezone.now()
    instance.save(update_fields=[
        'semantic_embedding', 'embedding_model', 'embedding_provider',
        'embedding_content_hash', 'embedding_updated_at', 'updated_at',
    ])
    return instance


def refresh_profile_embedding(owner, *, force: bool = False) -> CandidateProfile:
    profile, _ = CandidateProfile.objects.get_or_create(owner=owner)
    return _save_embedding(profile, profile_embedding_text(owner), force=force)


def refresh_job_embedding(job: JobPosting, *, force: bool = False) -> JobPosting:
    return _save_embedding(job, job_embedding_text(job), force=force)


def refresh_fact_embedding(fact: ProfileFact, *, force: bool = False) -> ProfileFact:
    return _save_embedding(fact, fact_embedding_text(fact), force=force)


def vector_similarity(left: Sequence[float] | None, right: Sequence[float] | None) -> float:
    if left is None or right is None:
        return 0.0
    return cosine_similarity(list(left), list(right))


def profile_job_similarity(profile: CandidateProfile, job: JobPosting) -> float:
    """Return cosine similarity, using pgvector in PostgreSQL and Python in tests."""
    if profile.semantic_embedding is None or job.semantic_embedding is None:
        return 0.0
    if connection.vendor == 'postgresql':
        distance = (
            JobPosting.objects.filter(pk=job.pk)
            .annotate(distance=CosineDistance('semantic_embedding', profile.semantic_embedding))
            .values_list('distance', flat=True)
            .first()
        )
        if distance is not None:
            return max(-1.0, min(1.0, 1.0 - float(distance)))
    return vector_similarity(profile.semantic_embedding, job.semantic_embedding)


def nearest_profile_facts(owner, query_embedding: Sequence[float] | None, *, limit: int = 12) -> list[ProfileFact]:
    if query_embedding is None:
        return []
    queryset = ProfileFact.objects.filter(owner=owner, semantic_embedding__isnull=False)
    if connection.vendor == 'postgresql':
        return list(
            queryset.annotate(vector_distance=CosineDistance('semantic_embedding', query_embedding))
            .order_by('vector_distance', '-verified_by_user', 'id')[:limit]
        )
    facts = list(queryset)
    facts.sort(
        key=lambda fact: (
            -vector_similarity(fact.semantic_embedding, query_embedding),
            -int(fact.verified_by_user),
            fact.id,
        ),
    )
    return facts[:limit]


def rank_jobs_by_profile(queryset, profile: CandidateProfile):
    """Keep discovery lists chronological while preserving score annotations."""
    if connection.vendor != 'postgresql' or profile.semantic_embedding is None:
        return queryset.order_by('-discovered_at', '-id')
    return queryset.annotate(
        semantic_distance=CosineDistance('semantic_embedding', profile.semantic_embedding),
    ).order_by('-discovered_at', '-id')


def rank_jobs_by_query(queryset, query: str):
    """Rank stored jobs against a natural-language search query with pgvector."""
    if connection.vendor != 'postgresql' or not clean_text(query):
        return queryset.filter(title__icontains=query).order_by(
            '-match__score', '-posted_at', '-discovered_at',
        )
    query_embedding = embed_text_result(query).vector
    return queryset.filter(semantic_embedding__isnull=False).annotate(
        semantic_distance=CosineDistance('semantic_embedding', query_embedding),
    ).order_by('semantic_distance', '-match__score', '-posted_at', '-discovered_at')
