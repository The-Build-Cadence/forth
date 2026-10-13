"""Shared search vocabulary and cheap evidence gates for web discovery."""
import re

from core.ai import clean_text, keywords


ENGINEERING_LEADERS = (
    'engineering lead', 'engineering manager', 'technical lead', 'lead software engineer',
    'software engineering lead', 'software engineering manager', 'software development manager',
    'software team lead', 'tech lead', 'team lead engineering', 'engineering team lead',
    'team lead software engineering',
)


def normalized(text):
    return re.sub(r'[^a-z0-9]+', ' ', clean_text(text).lower()).strip()


def contains_phrase(text, phrase):
    return f' {normalized(phrase)} ' in f' {normalized(text)} '


def role_variants(roles):
    variants = []
    for role in roles:
        role = normalized(role)
        if role:
            variants.append(role)
        if role in ENGINEERING_LEADERS:
            variants.extend(ENGINEERING_LEADERS[:4])
    return list(dict.fromkeys(variants))[:8]


def cheap_assessment(profile, record, *, profile_evidence=''):
    """Query terms must never become evidence for a job's fit or location."""
    title = normalized(record.title)
    snippet = clean_text((record.payload or {}).get('snippet') or record.description)
    evidence = f'{record.title}\n{record.location}\n{snippet}'
    text = normalized(evidence)
    targets = [normalized(role) for role in profile.target_roles or []]
    target_words = set(keywords(' '.join(targets), limit=80))
    title_words = set(keywords(title, limit=40))
    result = {'eligible': False, 'score': None, 'method': 'role_family_evidence_v3'}

    def reject(code, reason):
        return {**result, 'reason_code': code, 'reason': reason}

    unrelated = {'mechanical', 'civil', 'electrical', 'construction', 'manufacturing', 'industrial',
                 'qa', 'quality', 'testing', 'sales', 'recruiter', 'recruitment', 'support', 'ux', 'hardware'}
    if (title_words & unrelated) - target_words:
        return reject('role_mismatch', 'The title belongs to a different discipline than your target roles.')
    if {'project', 'engineering'} <= title_words and 'project' not in target_words:
        return reject('role_mismatch', 'Project engineering is outside the requested software leadership roles.')
    family = any(role in ENGINEERING_LEADERS for role in targets)
    exact = any(contains_phrase(title, role) for role in targets)
    equivalent = family and any(contains_phrase(title, role) for role in ENGINEERING_LEADERS)
    if not exact and not equivalent:
        return reject('role_mismatch', 'The title is not a target role or a supported equivalent.')
    native_mobile = {'mobile', 'native'} <= title_words or bool(title_words & {'ios', 'android'})
    candidate_text = normalized(profile_evidence or ' '.join([
        str(getattr(profile, 'professional_summary', '') or ''),
        str(getattr(profile, 'headline', '') or ''), ' '.join(targets),
    ]))
    if native_mobile and not any(contains_phrase(candidate_text, skill) for skill in ['ios', 'android', 'swift', 'kotlin', 'react native']):
        return reject('specialty_mismatch', 'This is a native mobile role, but your profile does not establish iOS, Android, Swift, Kotlin or React Native experience.')
    if len(snippet) < 50 or any(phrase in text for phrase in (
        'we cannot provide a description', 'enable javascript', 'job is no longer available',
        'position has been filled', 'job has expired', 'no longer accepting applications',
    )):
        return reject('insufficient_evidence', 'The result has no usable job description or appears closed.')
    # "Engineering" by itself is not proof of a software role.
    software = bool(set(keywords(text, limit=200)) & {
        'software', 'developers', 'developer', 'backend', 'frontend', 'fullstack', 'saas',
        'python', 'typescript', 'kubernetes', 'apis', 'microservices', 'devops',
        'coding', 'code', 'react', 'observability',
    })
    if family and not software:
        return reject('discipline_unverified', 'The snippet does not establish that this is a software role.')

    authorized = {normalized(country) for country in profile.authorized_countries or []}
    aliases = {
        'canada': r'\b(canada|canadian|ontario|toronto|vancouver|montreal|ottawa|kitchener|waterloo)\b',
        'united states': r'\b(united states|usa|us only|u s only)\b',
        'united kingdom': r'\b(united kingdom|uk only)\b',
    }
    authorized = {'canada' if c == 'ca' else 'united states' if c in {'us', 'usa'} else c for c in authorized}
    explicit_locations = ' '.join(normalized(value) for value in (record.payload or {}).get('eligibility_locations', []))
    explicit_locations = re.sub(r'\bca\b', 'canada', explicit_locations)
    explicit_locations = re.sub(r'\bus\b', 'united states', explicit_locations)
    if authorized and explicit_locations and not any(
        re.search(aliases.get(country, rf'\b{re.escape(country)}\b'), explicit_locations) for country in authorized
    ) and not re.search(r'\b(worldwide|anywhere|global)\b', explicit_locations):
        return reject('location_mismatch', 'The structured posting limits eligibility to locations outside your work authorization.')
    # Prefer advertised location over company boilerplate (e.g. "customers
    # across the US and Canada" is not permission to work from Canada).
    geography = normalized(record.location) if (record.payload or {}).get('structured_job') and record.location else text
    country_matches = {country for country, pattern in aliases.items() if re.search(pattern, geography)}
    allowed = bool(authorized & country_matches) or any(contains_phrase(geography, c) for c in authorized)
    worldwide = bool(re.search(r'\b(remote worldwide|worldwide remote|work from anywhere|globally remote|remote anywhere)\b', text))
    explicitly_us_only = bool(re.search(r'\b(us only|usa only|united states only|must (?:be|reside|live) (?:based )?in (?:the )?(?:us|united states))\b', text))
    if explicitly_us_only and 'united states' not in authorized:
        return reject('location_mismatch', 'The posting explicitly restricts applicants to the United States.')
    if authorized and not allowed and not worldwide:
        if country_matches - authorized:
            return reject('location_mismatch', 'The posting names a country outside your work authorization.')
        return reject('location_unverified', 'The result does not confirm eligibility in your authorized country.')
    modes = {normalized(mode) for mode in profile.work_modes or []}
    remote = bool(re.search(r'\b(remote|work from home|distributed team)\b', text))
    onsite = bool(re.search(r'\b(on site|onsite|hybrid|in office|office based)\b', text))
    if modes == {'remote'} and (not remote or onsite):
        return reject('remote_unverified', 'Remote work is not confirmed, or the posting specifies office attendance.')
    # Equivalent roles earn the same role credit. Embeddings refine the rank;
    # a raw cosine value is not treated as a percentage fit.
    result.update(eligible=True, role_strength=100, exact_title_match=exact,
                  equivalent_role=equivalent and not exact, remote_confirmed=remote,
                  location_confirmed=allowed or worldwide,
                  lexical_score=70 + (10 if allowed or worldwide or not authorized else 0) + (5 if remote or modes != {'remote'} else 0),
                  reason_code='qualified', reason='Role, software discipline, location and work mode match the available evidence.')
    return result
