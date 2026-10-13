from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from core.models import CandidatePreference, CandidateProfile, OnboardingResponse, ProfileDocument, ProfileFact


def candidate_profile(owner) -> CandidateProfile:
    profile, _ = CandidateProfile.objects.get_or_create(owner=owner)
    return profile


def authoritative_facts(owner):
    """Return the candidate-designated source of truth when one is available.

    Imported material can be useful retrieval context, but it must not override
    a source the candidate has explicitly designated as authoritative (such as
    a current LinkedIn profile).  Older facts remain stored for auditability.
    """
    facts = ProfileFact.objects.filter(owner=owner)
    authoritative = facts.filter(metadata__source_of_truth=True)
    return authoritative if authoritative.exists() else facts


def matching_facts(owner):
    """Return primary profile facts plus corroborating verified evidence.

    A designated source of truth controls profile presentation, but it should
    not erase a verified resume's technical detail during matching.  This keeps
    the primary profile authoritative while allowing a clearly substantiated
    capability such as Python/Django to count as evidence.
    """
    primary = authoritative_facts(owner)
    corroborating = ProfileFact.objects.filter(owner=owner).filter(
        Q(verified_by_user=True) | Q(lifecycle='verified'),
    )
    return (primary | corroborating).distinct()


def compute_profile_completeness(owner) -> int:
    profile = candidate_profile(owner)
    checks = [
        bool(profile.headline),
        bool(profile.professional_summary),
        bool(profile.target_roles),
        bool(profile.location or profile.work_modes),
        bool(profile.authorized_countries),
        ProfileFact.objects.filter(owner=owner, lifecycle='verified').exists()
        or ProfileFact.objects.filter(owner=owner, verified_by_user=True).exists()
        or ProfileFact.objects.filter(
            owner=owner,
            source_document__isnull=False,
            metadata__onboarding_ambiguous=False,
        ).exists(),
        ProfileFact.objects.filter(owner=owner, fact_type='skill').exists(),
        ProfileFact.objects.filter(owner=owner, fact_type='achievement').exists(),
        CandidatePreference.objects.filter(owner=owner).exists(),
        ProfileDocument.objects.filter(owner=owner, status='ready').exists(),
    ]
    completeness = round(sum(checks) / len(checks) * 100)
    if profile.completeness != completeness:
        profile.completeness = completeness
        profile.save(update_fields=['completeness', 'updated_at'])
    return completeness


def profile_context(owner, *, verified_only: bool = False) -> dict[str, Any]:
    profile = candidate_profile(owner)
    facts = authoritative_facts(owner)
    if verified_only:
        facts = facts.filter(lifecycle='verified') | facts.filter(verified_by_user=True)
    facts = facts.order_by('-verified_by_user', 'fact_type', 'title')[:250]
    preferences = CandidatePreference.objects.filter(owner=owner).order_by('category', '-verified_by_user')
    return {
        'profile': {
            'headline': profile.headline,
            'professional_summary': profile.professional_summary,
            'target_roles': profile.target_roles,
            'target_industries': profile.target_industries,
            'location': profile.location,
            'authorized_countries': profile.authorized_countries,
            'work_modes': profile.work_modes,
            'employment_types': profile.employment_types,
            'minimum_compensation': profile.minimum_compensation,
            'compensation_currency': profile.compensation_currency,
            'minimum_match_score': profile.minimum_match_score,
            'excluded_companies': profile.excluded_companies,
            'completeness': compute_profile_completeness(owner),
        },
        'facts': [
            {
                'id': fact.id,
                'type': fact.fact_type,
                'title': fact.title,
                'statement': fact.statement,
                'confidence': fact.confidence,
                'lifecycle': fact.lifecycle,
                'verified': fact.verified_by_user or fact.lifecycle == 'verified',
                'evidence_quote': fact.evidence_quote,
            }
            for fact in facts
        ],
        'preferences': [
            {
                'id': preference.id,
                'category': preference.category,
                'label': preference.label,
                'value': preference.value,
                'importance': preference.importance,
                'verified': preference.verified_by_user,
            }
            for preference in preferences
        ],
    }


def profile_health(owner) -> dict[str, Any]:
    counts = dict(
        ProfileFact.objects.filter(owner=owner)
        .values('fact_type')
        .annotate(count=Count('id'))
        .values_list('fact_type', 'count')
    )
    unverified = ProfileFact.objects.filter(owner=owner, verified_by_user=False).exclude(lifecycle='verified').count()
    questions = []
    profile = candidate_profile(owner)
    if not profile.target_roles:
        questions.append('Which two or three role titles should the search prioritize?')
    if not profile.work_modes:
        questions.append('Do you prefer remote, hybrid, or on-site work?')
    if not profile.authorized_countries:
        questions.append('Where are you currently authorized to work?')
    if not counts.get('achievement'):
        questions.append('What accomplishment best demonstrates your impact?')
    return {
        'completeness': compute_profile_completeness(owner),
        'fact_counts': counts,
        'unverified_count': unverified,
        'questions': questions[:3],
    }


ONBOARDING_STEPS = {
    'welcome': ('Meet your Profile Steward', 'We’ll start with your current resume, then I’ll ask only what the evidence leaves unclear or incomplete.'),
    'source': ('Add your current resume', 'I’ll analyze the whole document before deciding what to ask. Clear facts are reused; ambiguity comes back to you.'),
    'source_processing': ('I’m analyzing your resume', 'I’m separating evidence from assumptions and finding the smallest set of useful follow-up questions.'),
    'interview': ('One useful question at a time', 'This question was selected from your resume, the profile built so far, and what is still missing.'),
    'review': ('Your candidate profile is ready', 'The required evidence, intent, constraints, and preferences are now usable across Forth.'),
}


def _onboarding_readiness(owner, state: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = candidate_profile(owner)
    state = dict(state if state is not None else (profile.onboarding_state or {}))
    answered = _answered_targets(state)
    checks = {
        'current resume analyzed': ProfileDocument.objects.filter(owner=owner, kind='resume', status='ready').exists(),
        'career direction': bool(profile.target_roles and profile.headline),
        'location and authorization': bool(profile.authorized_countries and (profile.location or profile.work_modes)),
        'experience and chronology': ProfileFact.objects.filter(owner=owner, fact_type='role').exists() or 'experience' in answered,
        'core capabilities': ProfileFact.objects.filter(owner=owner, fact_type='skill').exists(),
        'proof of impact': ProfileFact.objects.filter(owner=owner, fact_type='achievement').exists(),
        'education assessed': ProfileFact.objects.filter(owner=owner, fact_type='education').exists() or 'education' in answered,
        'people strengths assessed': ProfileFact.objects.filter(owner=owner, fact_type='skill', metadata__profile_category='soft_skill').exists() or 'soft_skills' in answered,
        'interests assessed': CandidatePreference.objects.filter(owner=owner, category='interest').exists() or 'hobbies' in answered,
        'work preferences': CandidatePreference.objects.filter(owner=owner, category='culture').exists(),
        'professional summary': bool(profile.professional_summary),
    }
    complete = sum(checks.values())
    return {
        'score': round(complete / len(checks) * 100),
        'ready': all(checks.values()),
        'checks': checks,
        'missing': [label for label, passed in checks.items() if not passed],
    }


def _suggested_summary(owner) -> str:
    profile = candidate_profile(owner)
    skills = list(ProfileFact.objects.filter(owner=owner, fact_type='skill').values_list('title', flat=True)[:5])
    impact = ProfileFact.objects.filter(owner=owner, fact_type='achievement').order_by('-verified_by_user', '-id').first()
    target = ', '.join(profile.target_roles[:2])
    parts = []
    if profile.headline:
        parts.append(profile.headline.rstrip('.'))
    if skills:
        parts.append(f"Brings strength in {', '.join(skills)}")
    if impact:
        parts.append(f'Known for results such as: {impact.statement.rstrip(".")}')
    if target:
        parts.append(f'Seeking {target} opportunities where this experience can create meaningful impact')
    return '. '.join(parts) + ('.' if parts else '')


def _resume_document(owner):
    return ProfileDocument.objects.filter(owner=owner, kind='resume').order_by('-updated_at', '-id').first()


def _unresolved_ambiguities(owner) -> list[ProfileFact]:
    return list(
        ProfileFact.objects.filter(
            owner=owner,
            verified_by_user=False,
            metadata__onboarding_ambiguous=True,
        ).order_by('id')[:8]
    )


def _answered_targets(state: dict[str, Any]) -> set[str]:
    return {str(value) for value in state.get('answered_targets', [])}


def _target_needed(owner, target: str, state: dict[str, Any], *, fact_id: int = 0) -> bool:
    profile = candidate_profile(owner)
    answered = _answered_targets(state)
    if target == 'fact_confirmation':
        return any(fact.id == fact_id for fact in _unresolved_ambiguities(owner))
    checks = {
        'headline': not bool(profile.headline),
        'target_roles': not bool(profile.target_roles),
        'target_industries': not bool(profile.target_industries) and target not in answered,
        'location': not bool(profile.location),
        'authorized_countries': not bool(profile.authorized_countries),
        'work_modes': not bool(profile.work_modes),
        'employment_types': not bool(profile.employment_types),
        'minimum_compensation': profile.minimum_compensation is None and target not in answered,
        'experience': not ProfileFact.objects.filter(owner=owner, fact_type='role').exists() and target not in answered,
        'skill': not ProfileFact.objects.filter(owner=owner, fact_type='skill').exists(),
        'achievement': not ProfileFact.objects.filter(owner=owner, fact_type='achievement').exists(),
        'education': not ProfileFact.objects.filter(owner=owner, fact_type='education').exists() and target not in answered,
        'soft_skills': not ProfileFact.objects.filter(owner=owner, fact_type='skill', metadata__profile_category='soft_skill').exists() and target not in answered,
        'hobbies': not CandidatePreference.objects.filter(owner=owner, category='interest').exists() and target not in answered,
        'preference_ideal': not CandidatePreference.objects.filter(owner=owner, category='culture').exclude(importance='avoid').exists() and target not in answered,
        'preference_avoid': not CandidatePreference.objects.filter(owner=owner, category='culture', importance='avoid').exists() and target not in answered,
        'professional_summary': not bool(profile.professional_summary),
    }
    return checks.get(target, False)


def _required_interview_complete(owner, state: dict[str, Any]) -> bool:
    profile = candidate_profile(owner)
    answered = _answered_targets(state)
    return bool(
        _onboarding_readiness(owner, state)['ready']
        and profile.employment_types
        and (profile.target_industries or 'target_industries' in answered)
        and (profile.minimum_compensation is not None or 'minimum_compensation' in answered)
        and CandidatePreference.objects.filter(owner=owner, category='culture').exclude(importance='avoid').exists()
        and (CandidatePreference.objects.filter(owner=owner, category='culture', importance='avoid').exists() or 'preference_avoid' in answered)
        and not _unresolved_ambiguities(owner)
    )


def _resume_analysis(owner) -> dict[str, Any]:
    document = _resume_document(owner)
    return dict((document.metadata or {}).get('resume_analysis') or {}) if document else {}


def _question_suggestions(owner, target: str, prefill: str = '') -> tuple[list[str], str]:
    """Build safe local proposals when the LLM is unavailable or omits them."""
    analysis = _resume_analysis(owner)
    facts = ProfileFact.objects.filter(owner=owner)
    titles = lambda fact_type: list(facts.filter(fact_type=fact_type).values_list('title', flat=True)[:5])
    profile = candidate_profile(owner)
    suggestions: dict[str, list[str]] = {
        'target_roles': [analysis.get('career_headline', '')] + titles('role')[:3],
        'headline': [analysis.get('career_headline', '')],
        'location': [analysis.get('likely_location', '')],
        'authorized_countries': [str(analysis.get('likely_location', '')).split(',')[-1].strip()],
        'work_modes': ['Remote', 'Hybrid'],
        'employment_types': ['Full-time'],
        'experience': [value for value in titles('role')[:2]],
        'skill': titles('skill')[:5],
        'achievement': list(facts.filter(fact_type='achievement').values_list('statement', flat=True)[:2]),
        'education': list(facts.filter(fact_type='education').values_list('statement', flat=True)[:2]),
        'soft_skills': ['Technical leadership', 'Clear communication', 'Cross-functional collaboration'],
        'hobbies': ['Mentoring', 'Open-source work', 'Continuous learning'],
        'target_industries': list(analysis.get('likely_industries', []))[:5],
        'minimum_compensation': ['150000'],
        'preference_ideal': ['High ownership', 'Calm collaboration'],
        'preference_avoid': ['Always-on culture'],
        'professional_summary': [prefill or _suggested_summary(owner)],
        'fact_confirmation': [prefill],
    }
    values = []
    for value in suggestions.get(target, []):
        cleaned = str(value or '').strip()
        if cleaned and cleaned not in values:
            values.append(cleaned)
    evidence_targets = {'headline', 'location', 'experience', 'skill', 'achievement', 'education', 'target_industries', 'professional_summary', 'fact_confirmation'}
    reason = (
        'Drafted from your resume and the profile assembled so far—edit anything that overstates or misses your intent.'
        if target in evidence_targets
        else 'These are starting points, not assumed facts. Choose or edit only what is true for you.'
    )
    if target == 'authorized_countries':
        reason = 'Your location suggests a useful starting point, but only you can confirm where you are authorized to work.'
    if target == 'minimum_compensation':
        reason = f'An editable starting point in {profile.compensation_currency}; change it or skip if you do not have a firm floor.'
    return values[:6], reason


def _fallback_question(owner, state: dict[str, Any]) -> dict[str, Any] | None:
    analysis = _resume_analysis(owner)
    ambiguity = next(iter(_unresolved_ambiguities(owner)), None)
    if ambiguity:
        suggestions, suggestion_reason = _question_suggestions(owner, 'fact_confirmation', ambiguity.statement)
        return {
            'target': 'fact_confirmation', 'kind': 'confirm',
            'title': 'Can you clarify this resume detail?',
            'prompt': (ambiguity.metadata or {}).get('ambiguity_reason') or 'I found a useful claim whose meaning is not fully clear.',
            'why': 'Confirming it keeps matching and generated documents accurate.',
            'placeholder': 'Edit the claim if it needs correction.', 'prefill': ambiguity.statement,
            'options': [], 'suggestions': suggestions,
            'suggestion_reason': suggestion_reason,
            'required': True, 'fact_id': ambiguity.id,
            'evidence': ambiguity.evidence_quote,
        }

    questions = [
        ('target_roles', 'tags', 'Where do you want to go next?', 'Which role titles should I actively search for?', 'Your next role is an intention; I will not infer it from your current title.', 'Staff Engineer, Engineering Lead', '', [], True),
        ('headline', 'text', 'How should I describe your professional identity?', 'Give me the short headline that should anchor your profile.', 'This becomes shared context for sourcing, matching, and document generation.', 'Product-minded platform engineer', analysis.get('career_headline', ''), [], True),
        ('location', 'text', 'Where are you currently based?', 'What city and country should I use for location-aware opportunities?', 'Resume locations can refer to an employer, not necessarily where you live now.', 'Toronto, Canada', analysis.get('likely_location', ''), [], True),
        ('authorized_countries', 'tags', 'Where can you legally work?', 'List the countries where you currently have work authorization.', 'Authorization is a hard eligibility signal and should never be guessed.', 'Canada, United States', '', [], True),
        ('work_modes', 'multi_choice', 'How do you want to work?', 'Choose every work mode you would genuinely consider.', 'This prevents strong-looking but impractical matches.', '', '', ['Remote', 'Hybrid', 'On-site'], True),
        ('employment_types', 'multi_choice', 'Which arrangements work for you?', 'Choose the employment types you want included in your search.', 'It keeps sourcing aligned with the kind of commitment you want.', '', 'Full-time', ['Full-time', 'Contract', 'Part-time'], True),
        ('experience', 'textarea', 'What experience should anchor your profile?', 'Your resume did not give me a clear role history. Describe the most relevant role, scope, and dates.', 'A grounded experience record keeps matching and tailored resumes truthful.', 'Role, company, dates, scope, and key responsibilities.', '', [], True),
        ('skill', 'tags', 'What capabilities should lead your profile?', 'Your resume did not give me a clear skills signal. Add the capabilities you want matching to prioritize.', 'Skills help retrieve and rank roles even when job titles differ.', 'Python, product strategy, stakeholder leadership', '', [], True),
        ('achievement', 'textarea', 'What result best shows your impact?', 'Describe one accomplishment: the situation, what you did, and what changed.', 'A concrete proof point is more valuable than generic responsibilities.', 'Include scale, collaborators, constraints, and a measurable result when possible.', '', [], True),
        ('education', 'textarea', 'Is there education or training worth carrying forward?', 'Confirm the most relevant degree, certification, program, or equivalent learning—or skip if none belongs in your profile.', 'This prevents missing credentials while respecting experience-based career paths.', 'Program or credential, institution, and year if useful.', '', [], False),
        ('soft_skills', 'tags', 'Which people strengths show up consistently?', 'Choose or edit the interpersonal strengths that colleagues would recognize in your work.', 'These help assess team and leadership fit without relying on generic personality claims.', 'Technical leadership, clear communication', '', [], False),
        ('hobbies', 'tags', 'Any interests that add useful context?', 'Add hobbies, communities, or interests you would be comfortable using for culture fit—or skip.', 'Personal context can improve fit and writing tone, but it is never required for eligibility.', 'Mentoring, open source, distance running', '', [], False),
        ('target_industries', 'tags', 'Any domains you want me to favor?', 'List industries or problem spaces you are excited by, or skip if you are open.', 'This is a preference signal, not a hard filter.', 'Developer tools, healthcare, climate', ', '.join(analysis.get('likely_industries', [])), [], False),
        ('minimum_compensation', 'number', 'Do you have a compensation floor?', 'Share the minimum annual compensation worth considering, or skip for now.', 'A floor helps avoid opportunities that cannot meet your needs.', '150000', '', [], False),
        ('preference_ideal', 'multi_choice', 'When do you do your best work?', 'Choose the conditions that matter most in your next team.', 'These signals help separate two jobs that look equally strong on paper.', '', '', ['High ownership', 'Calm collaboration', 'Strong mentorship', 'Deep technical work', 'Customer proximity', 'Clear mission'], True),
        ('preference_avoid', 'multi_choice', 'What should I actively avoid?', 'Choose any work conditions that would make a role a poor fit, or skip.', 'Explicit boundaries make recommendations more useful and honest.', '', '', ['Always-on culture', 'Unclear ownership', 'Heavy travel', 'Pure people management'], False),
        ('professional_summary', 'textarea', 'Does this capture your professional through-line?', 'Review and edit the profile summary I assembled from your evidence and answers.', 'This is the concise shared narrative every specialist will use.', 'A concise description of your experience, strengths, impact, and direction.', _suggested_summary(owner), [], True),
    ]
    for target, kind, title, prompt, why, placeholder, prefill, options, required in questions:
        if _target_needed(owner, target, state):
            suggestions, suggestion_reason = _question_suggestions(owner, target, prefill)
            if not prefill and kind in {'text', 'textarea', 'tags', 'number', 'confirm'} and suggestions:
                prefill = suggestions[0] if kind not in {'tags'} else ', '.join(suggestions)
            return {
                'target': target, 'kind': kind, 'title': title, 'prompt': prompt,
                'why': why, 'placeholder': placeholder, 'prefill': prefill,
                'options': options, 'suggestions': suggestions,
                'suggestion_reason': suggestion_reason,
                'required': required, 'fact_id': 0,
                'evidence': '',
            }
    return None


def _question_context(owner, state: dict[str, Any]) -> dict[str, Any]:
    context = profile_context(owner)
    context['resume_analysis'] = _resume_analysis(owner)
    context['unresolved_ambiguities'] = [
        {
            'fact_id': fact.id,
            'title': fact.title,
            'claim': fact.statement,
            'evidence': fact.evidence_quote,
            'reason': (fact.metadata or {}).get('ambiguity_reason', ''),
        }
        for fact in _unresolved_ambiguities(owner)
    ]
    context['interview_history'] = list(state.get('interview_history', []))[-12:]
    context['answered_targets'] = list(_answered_targets(state))
    context['required_signals_complete'] = _required_interview_complete(owner, state)
    context['assessment'] = _onboarding_readiness(owner, state)
    return context


def _next_question(owner, state: dict[str, Any]) -> dict[str, Any] | None:
    if _required_interview_complete(owner, state):
        return None
    fallback = _fallback_question(owner, state)
    from core.ai import plan_onboarding_question

    generated = plan_onboarding_question(_question_context(owner, state))
    raw = dict(generated.data.get('question') or {}) if generated and not generated.data.get('complete') else {}
    target = str(raw.get('target', ''))
    fact_id = int(raw.get('fact_id') or 0)
    if not raw or not _target_needed(owner, target, state, fact_id=fact_id):
        question = fallback
    else:
        question = {
            'target': target,
            'kind': raw.get('kind', 'text'),
            'title': str(raw.get('title', 'A quick follow-up'))[:180],
            'prompt': str(raw.get('prompt', ''))[:600],
            'why': str(raw.get('why', ''))[:400],
            'placeholder': str(raw.get('placeholder', ''))[:240],
            'prefill': str(raw.get('prefill', ''))[:3000],
            'options': [str(value)[:120] for value in raw.get('options', [])][:10],
            'suggestions': [str(value)[:600] for value in raw.get('suggestions', []) if str(value).strip()][:6],
            'suggestion_reason': str(raw.get('suggestion_reason', ''))[:400],
            'required': bool(raw.get('required')),
            'fact_id': fact_id,
            'evidence': '',
        }
        optional_targets = {'target_industries', 'minimum_compensation', 'preference_avoid', 'education', 'soft_skills', 'hobbies'}
        question['required'] = target not in optional_targets
        if target == 'fact_confirmation':
            fact = next((value for value in _unresolved_ambiguities(owner) if value.id == fact_id), None)
            if fact:
                question['prefill'] = question['prefill'] or fact.statement
                question['evidence'] = fact.evidence_quote
                question['required'] = True
        if not question['suggestions']:
            question['suggestions'], question['suggestion_reason'] = _question_suggestions(owner, target, question['prefill'])
        if not question['suggestion_reason']:
            _, question['suggestion_reason'] = _question_suggestions(owner, target, question['prefill'])
    if not question:
        return None
    turn = len(state.get('interview_history', [])) + 1
    question['id'] = f"q{turn}-{question['target']}-{question.get('fact_id', 0)}"
    return question


def _reconcile_legacy_answers(owner, profile: CandidateProfile, state: dict[str, Any]) -> dict[str, Any]:
    """One-time repair for answers saved before durable response rows existed.

    Older builds kept the interview transcript but a stale profile editor could
    overwrite the structured field. Replaying only still-missing, non-skipped
    answers prevents the candidate from being asked for the same information.
    """
    if state.get('legacy_answers_reconciled_at') or not state.get('interview_history'):
        return state
    for entry in state.get('interview_history', []):
        question_id = str(entry.get('question_id') or '')
        target = str(entry.get('target') or '')
        skipped = bool(entry.get('skipped')) or entry.get('answer') == 'Skipped'
        value = entry.get('value', entry.get('answer'))
        if question_id and target:
            OnboardingResponse.objects.update_or_create(
                owner=owner, question_id=question_id,
                defaults={
                    'target': target,
                    'question': {'id': question_id, 'target': target, 'title': entry.get('question', '')},
                    'answer': {'value': value}, 'skipped': skipped,
                    'applied_at': timezone.now(),
                },
            )
        if skipped or target == 'fact_confirmation':
            continue
        replay_state = {**state, 'answered_targets': [item for item in state.get('answered_targets', []) if item != target]}
        if not _target_needed(owner, target, replay_state):
            continue
        try:
            _apply_onboarding_value(owner, profile, {'target': target, 'required': False}, value)
        except ValueError:
            continue
    state['legacy_answers_reconciled_at'] = timezone.now().isoformat()
    profile.onboarding_state = state
    profile.save()
    return state


def _build_onboarding_snapshot(owner) -> dict[str, Any]:
    profile = candidate_profile(owner)
    state = dict(profile.onboarding_state or {})
    documents = ProfileDocument.objects.filter(owner=owner)
    resume = _resume_document(owner)
    processing = bool(resume and resume.status in {'new', 'queued', 'processing'})
    has_source = bool(resume and resume.status == 'ready')
    fact_counts = dict(ProfileFact.objects.filter(owner=owner).values('fact_type').annotate(count=Count('id')).values_list('fact_type', 'count'))
    preference_count = CandidatePreference.objects.filter(owner=owner).count()
    question = None

    if profile.onboarding_completed_at:
        step_id = 'review'
    elif not state.get('started'):
        step_id = 'welcome'
    elif processing:
        step_id = 'source_processing'
    elif not has_source:
        step_id = 'source'
    else:
        question = state.get('current_question')
        if question and not _target_needed(owner, question.get('target', ''), state, fact_id=int(question.get('fact_id') or 0)):
            question = None
        if not question:
            question = _next_question(owner, state)
            if question:
                state['current_question'] = question
                profile.onboarding_state = state
                profile.save(update_fields=['onboarding_state', 'updated_at'])
        step_id = 'interview' if question else 'review'

    title, prompt = ONBOARDING_STEPS[step_id]
    if question:
        title = question['title']
        prompt = question['prompt']
    readiness = _onboarding_readiness(owner, state)
    return {
        'needs_onboarding': profile.onboarding_completed_at is None,
        'step': {'id': step_id, 'title': title, 'prompt': prompt, 'question': question},
        'progress': max(5, min(100, readiness['score'] if step_id != 'welcome' else 5)),
        'readiness': readiness,
        'assessment': {
            'confidence': readiness['score'],
            'gate': 100,
            'ready': readiness['ready'] and not _unresolved_ambiguities(owner),
            'missing': readiness['missing'],
            'rationale': 'Confidence is reassessed from resume evidence, confirmed answers, intent, eligibility, impact, and unresolved ambiguity after every turn.',
        },
        'stats': {
            'documents': documents.count(),
            'facts': sum(fact_counts.values()),
            'skills': fact_counts.get('skill', 0),
            'achievements': fact_counts.get('achievement', 0),
            'preferences': preference_count,
        },
        'suggested_summary': _suggested_summary(owner),
        'resume': {
            'id': resume.id,
            'name': resume.title,
            'status': resume.status,
            'message': resume.status_message,
            'analysis': _resume_analysis(owner),
        } if resume else None,
        'interview': {
            'turn': len(state.get('interview_history', [])) + (1 if question else 0),
            'history': list(state.get('interview_history', []))[-6:],
            'unresolved_ambiguities': len(_unresolved_ambiguities(owner)),
        },
    }


def onboarding_snapshot(owner) -> dict[str, Any]:
    # Serialize question planning and answer application for this candidate. Two
    # simultaneous GET/POST requests can no longer restore a stale question or
    # discard the latest answered-target memory.
    with transaction.atomic():
        profile = CandidateProfile.objects.select_for_update().filter(owner=owner).first()
        if profile is None:
            profile = candidate_profile(owner)
            profile = CandidateProfile.objects.select_for_update().get(pk=profile.pk)
        _reconcile_legacy_answers(owner, profile, dict(profile.onboarding_state or {}))
        return _build_onboarding_snapshot(owner)


def _verified_fact(owner, *, fact_type: str, title: str, statement: str, metadata: dict[str, Any] | None = None) -> None:
    title = str(title or '').strip()[:220]
    statement = str(statement or '').strip()
    if not title or not statement:
        return
    fact, _ = ProfileFact.objects.update_or_create(
        owner=owner,
        fact_type=fact_type,
        title=title,
        defaults={
            'statement': statement,
            'normalized_value': title.lower()[:220],
            'confidence': 'high',
            'verified_by_user': True,
            'lifecycle': 'verified',
            'strength': 'strong',
            'metadata': {'source': 'onboarding', **(metadata or {})},
        },
    )
    from core.domain.embeddings import refresh_fact_embedding

    refresh_fact_embedding(fact)


def _apply_onboarding_value(owner, profile: CandidateProfile, question: dict[str, Any], value: Any) -> None:
    target = str(question.get('target', ''))
    values = value if isinstance(value, list) else [part.strip() for part in str(value or '').split(',') if part.strip()]
    if target in {'target_roles', 'target_industries'}:
        if not values:
            raise ValueError('Add at least one answer before continuing.')
        setattr(profile, target, values[:12])
    elif target in {'authorized_countries', 'work_modes', 'employment_types'}:
        if not values:
            raise ValueError('Choose at least one option before continuing.')
        normalized = [str(item).strip().lower() if target != 'authorized_countries' else str(item).strip() for item in values]
        setattr(profile, target, normalized[:12])
    elif target in {'headline', 'location'}:
        text = str(value or '').strip()
        if not text:
            raise ValueError('Add an answer before continuing.')
        setattr(profile, target, text[:220])
    elif target == 'minimum_compensation':
        if not str(value or '').isdigit():
            raise ValueError('Enter a whole annual compensation amount, or skip this question.')
        profile.minimum_compensation = int(value)
    elif target == 'experience':
        text = str(value or '').strip()
        if len(text) < 20:
            raise ValueError('Add the role, scope, and enough context to make this experience useful.')
        _verified_fact(owner, fact_type='role', title=text[:100], statement=text)
    elif target == 'skill':
        if not values:
            raise ValueError('Add at least one capability.')
        for skill in values[:20]:
            _verified_fact(owner, fact_type='skill', title=skill, statement=f'{skill} is a user-verified core capability.')
    elif target == 'achievement':
        text = str(value or '').strip()
        if len(text) < 30:
            raise ValueError('Add enough detail to explain what you did and what changed.')
        _verified_fact(owner, fact_type='achievement', title=text[:100], statement=text)
    elif target == 'education':
        text = str(value or '').strip()
        if len(text) < 5:
            raise ValueError('Add the relevant education or skip this question.')
        _verified_fact(owner, fact_type='education', title=text[:100], statement=text)
    elif target == 'soft_skills':
        if not values:
            raise ValueError('Choose at least one strength or skip this question.')
        for skill in values[:12]:
            _verified_fact(
                owner, fact_type='skill', title=skill,
                statement=f'{skill} is a candidate-confirmed people strength.',
                metadata={'profile_category': 'soft_skill'},
            )
    elif target == 'hobbies':
        if not values:
            raise ValueError('Add at least one interest or skip this question.')
        for label in values[:12]:
            CandidatePreference.objects.update_or_create(
                owner=owner, category='interest', label=label,
                defaults={'importance': 'flexible', 'verified_by_user': True, 'value': {}, 'rationale': 'Candidate-confirmed personal context.'},
            )
    elif target in {'preference_ideal', 'preference_avoid'}:
        if not values and question.get('required'):
            raise ValueError('Choose at least one preference.')
        importance = 'avoid' if target == 'preference_avoid' else 'strong'
        for label in values[:12]:
            CandidatePreference.objects.update_or_create(
                owner=owner, category='culture', label=label,
                defaults={'importance': importance, 'verified_by_user': True, 'value': {}, 'rationale': 'Collected by the adaptive onboarding interview.'},
            )
    elif target == 'professional_summary':
        text = str(value or '').strip()
        if len(text) < 40:
            raise ValueError('Add a little more detail so the specialists have a useful professional through-line.')
        profile.professional_summary = text
    elif target == 'fact_confirmation':
        fact = ProfileFact.objects.filter(owner=owner, pk=question.get('fact_id')).first()
        if not fact:
            raise ValueError('I could not find the resume fact that needs confirmation.')
        text = str(value or fact.statement).strip()
        if len(text) < 5:
            raise ValueError('Confirm the claim or replace it with the accurate version.')
        fact.statement = text
        fact.verified_by_user = True
        fact.lifecycle = 'verified'
        fact.confidence = 'high'
        fact.metadata = {**(fact.metadata or {}), 'onboarding_ambiguous': False, 'confirmed_during_onboarding': True}
        fact.save(update_fields=['statement', 'verified_by_user', 'lifecycle', 'confidence', 'metadata', 'updated_at'])
        from core.domain.embeddings import refresh_fact_embedding

        refresh_fact_embedding(fact)
    else:
        raise ValueError('That profile question is not supported.')


def answer_onboarding(owner, *, step: str, answers: dict[str, Any]) -> dict[str, Any]:
    with transaction.atomic():
        profile = CandidateProfile.objects.select_for_update().filter(owner=owner).first()
        if profile is None:
            profile = candidate_profile(owner)
            profile = CandidateProfile.objects.select_for_update().get(pk=profile.pk)
        state = dict(profile.onboarding_state or {})
        state['started'] = True
        state['last_step'] = step
        state['updated_at'] = timezone.now().isoformat()

        if step == 'source':
            raise ValueError('Add your current resume so I can avoid making you repeat information it already contains.')
        if step == 'interview':
            question = dict(state.get('current_question') or {})
            if not question or (answers.get('question_id') and answers.get('question_id') != question.get('id')):
                raise ValueError('That question is no longer current. Refresh onboarding and try again.')
            target = question.get('target', '')
            skipped = bool(answers.get('skip'))
            if skipped and question.get('required'):
                raise ValueError('This answer is needed to make your candidate profile ready for action.')
            value = answers.get('value')
            if not skipped:
                _apply_onboarding_value(owner, profile, question, value)

            answered = list(_answered_targets(state))
            if target != 'fact_confirmation' and target not in answered:
                answered.append(target)
            state['answered_targets'] = answered
            history = list(state.get('interview_history', []))
            history.append({
                'question_id': question.get('id'), 'target': target,
                'question': question.get('title'),
                'answer': 'Skipped' if skipped else (', '.join(str(item) for item in value) if isinstance(value, list) else str(value or 'Confirmed'))[:500],
                'value': value,
                'skipped': skipped,
                'saved_at': timezone.now().isoformat(),
            })
            state['interview_history'] = history[-24:]
            state.pop('current_question', None)
            OnboardingResponse.objects.update_or_create(
                owner=owner,
                question_id=str(question.get('id', '')),
                defaults={
                    'target': target,
                    'question': question,
                    'answer': {'value': value},
                    'skipped': skipped,
                    'applied_at': timezone.now(),
                },
            )
        elif step == 'complete':
            readiness = _onboarding_readiness(owner)
            if not _required_interview_complete(owner, state):
                raise ValueError(f"Complete these profile signals first: {', '.join(readiness['missing']) or 'the remaining interview questions'}.")
            profile.onboarding_completed_at = timezone.now()

        profile.onboarding_state = state
        profile.last_reviewed_at = timezone.now()
        profile.save()
        compute_profile_completeness(owner)
    return onboarding_snapshot(owner)
