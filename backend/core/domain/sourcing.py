from __future__ import annotations

import html
import json
import ipaddress
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from xml.etree import ElementTree
from urllib.parse import urlencode, urlparse, urljoin

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from core.ai import clean_text, embed_text_result, keywords, stable_hash
from core.domain.embeddings import profile_embedding_text, refresh_profile_embedding, vector_similarity
from core.domain.discovery_quality import cheap_assessment, role_variants
from core.models import JobPosting, JobPostingVersion, JobRequirement, JobSource, SourceRun, SourceSearchQuery


def _plain(value: Any) -> str:
    text = html.unescape(str(value or ''))
    text = re.sub(r'<(br|/p|/li)>', '\n', text, flags=re.I)
    return clean_text(re.sub(r'<[^>]+>', ' ', text))


@dataclass
class SourceRecord:
    external_id: str
    title: str
    company: str
    location: str
    description: str
    source_url: str
    application_url: str
    posted_at: datetime | None = None
    payload: dict[str, Any] | None = None


class SourceConnector:
    def __init__(self, source: JobSource):
        self.source = source
        self.config = source.config or {}
        self.timeout = int(getattr(settings, 'SOURCE_HTTP_TIMEOUT_SECONDS', 20))
        self.on_progress = None

    def emit_progress(self, event: dict) -> None:
        self.events.append(event)
        if self.on_progress:
            self.on_progress(event)

    def fetch(self) -> list[SourceRecord]:
        return []

    def get_json(self, url: str) -> Any:
        validate_public_url(url)
        response = requests.get(url, timeout=self.timeout, headers={'User-Agent': 'Forth/1.0'})
        response.raise_for_status()
        return response.json()


class BraveSearchConnector(SourceConnector):
    """Discover public job pages using Brave; the secret stays on the server."""

    endpoint = 'https://api.search.brave.com/res/v1/web/search'
    ATS_DOMAINS = ('job-boards.greenhouse.io', 'boards.greenhouse.io', 'jobs.lever.co', 'jobs.ashbyhq.com', 'jobs.smartrecruiters.com', 'myworkdayjobs.com', 'apply.workable.com')
    REJECTED_DOMAINS = ('indeed.', 'linkedin.', 'glassdoor.', 'ziprecruiter.', 'talent.com', 'jooble.', 'simplyhired.', 'careerbuilder.', 'jobgether.', 'builtin.com', 'remoterocketship.com', 'randstad.', 'turing.com')
    REJECTED_BRANDS = ('jobgether', 'talent.com', 'jooble', 'simplyhired', 'careerbuilder')

    def _query_plan(self) -> list[dict[str, Any]]:
        """Build a bounded search space, then choose the least-recently used paths.

        A query is identified by a canonical hash of its role, ATS, location,
        and optional specialty rather than by opaque text. This makes the
        exploration history survive copy changes and prevents a scheduled run
        from repeatedly spending API calls on the same keyword combination.
        """
        configured = self.config.get('queries') or []
        if isinstance(configured, str):
            configured = configured.split('\n')
        configured = [clean_text(value) for value in configured if clean_text(value)]
        candidates: list[dict[str, Any]] = []
        if configured:
            candidates = [{'query': query, 'components': {'mode': 'focused', 'query': query.lower()}} for query in configured]
        else:
            candidates = self._profile_query_candidates()
        if not candidates:
            return []

        unique: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            components = candidate['components']
            query_hash = stable_hash('|'.join(f'{key}={components[key]}' for key in sorted(components)))
            unique.setdefault(query_hash, {**candidate, 'query_hash': query_hash})
        candidates = list(unique.values())
        history = {
            item.query_hash: item
            for item in SourceSearchQuery.objects.filter(source=self.source, query_hash__in=list(unique))
        }
        now = timezone.now()
        available = []
        for candidate in candidates:
            memory = history.get(candidate['query_hash'])
            outcomes = (memory.components.get('_outcomes') or {}) if memory else {}
            # Revisit successful searches daily; cool down empty/unqualified
            # searches for a week. Repeated clicks do not spend the same query.
            cooldown = timedelta(hours=24) if memory and (outcomes.get('qualified', memory.last_result_count) > 0) else timedelta(days=7)
            if memory and memory.last_searched_at and memory.last_searched_at > now - cooldown:
                continue
            candidate['priority'] = 0 if outcomes.get('imported', 0) else 1 if outcomes.get('qualified', 0) else 2 if not memory else 3
            candidate['last_used'] = memory.last_searched_at if memory else datetime.min.replace(tzinfo=UTC)
            available.append(candidate)
        max_queries = max(1, min(10, int(self.config.get('queries_per_run') or 8)))
        selected = []
        roles_used: dict[str, int] = {}
        domains_used: dict[str, int] = {}
        while available and len(selected) < max_queries:
            # General search discovers employers, but tends to rank job-board
            # indexes. Reserve most of every pass for direct posting sites.
            if not configured and sum(not row['components'].get('domain') for row in selected) >= 2:
                available = [row for row in available if row['components'].get('domain')]
                if not available:
                    break
            available.sort(key=lambda item: (
                item['priority'], roles_used.get(item['components'].get('role', ''), 0), item['components'].get('tier', 0),
                domains_used.get(item['components'].get('domain', ''), 0),
                item['last_used'], item['components'].get('tier', 0), item['query'],
            ))
            item = available.pop(0)
            role, domain = item['components'].get('role', ''), item['components'].get('domain', '')
            roles_used[role] = roles_used.get(role, 0) + 1
            domains_used[domain] = domains_used.get(domain, 0) + 1
            selected.append({key: value for key, value in item.items() if key not in {'priority', 'last_used'}})
        return selected

    def _profile_query_candidates(self) -> list[dict[str, Any]]:
        profile = getattr(self.source.owner, 'candidate_profile', None)
        if not profile:
            return []
        variants = role_variants(getattr(profile, 'target_roles', None) or [])
        location = clean_text(getattr(profile, 'location', '')).split(',', 1)[0]
        work_modes = [str(mode).lower() for mode in (getattr(profile, 'work_modes', None) or [])]
        # Keep every automated query geographically intentional. An unscoped
        # query is only a fallback when the profile has neither a location nor
        # a remote preference; otherwise it mostly finds attractive-but-
        # ineligible roles around the world.
        countries = [clean_text(country) for country in (getattr(profile, 'authorized_countries', None) or []) if clean_text(country)]
        locations = [f'remote {country}' for country in countries] if 'remote' in work_modes else []
        if 'remote' in work_modes:
            locations += ['remote worldwide']
        else:
            locations += [location] if location else countries
        if not locations:
            locations = ['']
        locations = list(dict.fromkeys(locations))
        candidates: list[dict[str, Any]] = []
        for role in variants:
            for domain in ['', *self.ATS_DOMAINS]:
                for location_term in locations:
                    # ATS pages often lack search-engine freshness metadata.
                    # Verify the actual posting; date-filtered queries are a
                    # later exploration lane, never the only route to a job.
                    for freshness in ['', 'pm']:
                        components = {'strategy': 'profile-v3', 'role': role, 'domain': domain, 'location': location_term.lower(), 'freshness': freshness, 'tier': (1 if domain else 0) + (2 if freshness else 0)}
                        query = ' '.join(part for part in [f'"{role}"', location_term, 'jobs', f'site:{domain}' if domain else '-site:linkedin.com -site:indeed.com'] if part)
                        candidates.append({'query': query, 'components': components})
        return candidates

    def _record_query(self, plan: dict[str, Any], result_count: int) -> None:
        memory, _ = SourceSearchQuery.objects.get_or_create(
            source=self.source,
            query_hash=plan['query_hash'],
            defaults={'owner': self.source.owner, 'query': plan['query'], 'components': plan['components']},
        )
        memory.query = plan['query']
        memory.components = {**plan['components'], '_outcomes': {}}
        memory.search_count += 1
        memory.last_searched_at = timezone.now()
        memory.last_result_count = result_count
        memory.save(update_fields=['query', 'components', 'search_count', 'last_searched_at', 'last_result_count', 'updated_at'])

    @classmethod
    def _direct_job_result(cls, url: str, title: str) -> bool:
        host = (urlparse(url).hostname or '').lower()
        if any(blocked in host for blocked in cls.REJECTED_DOMAINS):
            return False
        if any(brand in title.lower() for brand in cls.REJECTED_BRANDS):
            return False
        ats = any(host == domain or host.endswith('.' + domain) for domain in cls.ATS_DOMAINS)
        if re.search(r'\b[\d,]+\b.{0,60}\b(?:jobs|roles|openings)\b', title, flags=re.I):
            return False
        path = urlparse(url).path.strip('/')
        if ats:
            return len(path.split('/')) >= 2
        # Allow direct employer job details discovered on the open web, but
        # exclude generic careers/search pages and editorial content.
        return bool(re.search(r'/(?:jobs?|careers|positions|openings)/(?:[^/?#]+/)*[^/?#]*\d{4,}', '/' + path, re.I)
                    or re.search(r'(?:^|&)gh_jid=\d+(?:&|$)', urlparse(url).query))

    def fetch(self) -> list[SourceRecord]:
        key = getattr(settings, 'BRAVE_SEARCH_API_KEY', '')
        if not key:
            raise ValueError('Brave search is not configured. Add BRAVE_SEARCH_API_KEY to the server environment.')
        plans = self._query_plan()
        if not plans:
            self.events, self.query_plans = [], []
            self.emit_progress({'level': 'notice', 'message': 'No untried searches are due. Add target roles or focused queries, or wait for the query cooldown.'})
            return []
        country = clean_text(self.config.get('country') or 'CA').upper()[:2]
        count = max(1, min(10, int(self.config.get('results_per_query') or 5)))
        records: list[SourceRecord] = []
        self.events = []
        self.query_plans = []
        seen_urls: set[str] = set()
        for plan in plans:
            query = plan['query']
            self.emit_progress({'level': 'searching', 'message': f'Searching: {query}', 'query': query})
            response = requests.get(
                self.endpoint,
                params={'q': query, 'count': count, 'country': country, 'search_lang': 'en',
                        **({'freshness': plan['components']['freshness']} if plan['components'].get('freshness') else {})},
                headers={'Accept': 'application/json', 'X-Subscription-Token': key}, timeout=self.timeout,
            )
            response.raise_for_status()
            rows = (response.json().get('web') or {}).get('results') or []
            before = len(records)
            direct_count = 0
            for row in rows:
                url = clean_text(row.get('url'))
                if any((urlparse(url).hostname or '') == domain or (urlparse(url).hostname or '').endswith('.' + domain) for domain in self.ATS_DOMAINS):
                    url = urlparse(url)._replace(query='', fragment='').geturl()
                title = clean_text(row.get('title'))
                snippet = clean_text(row.get('description'))
                if not url or not title or not self._direct_job_result(url, title):
                    continue
                direct_count += 1
                if url in seen_urls:
                    for previous in records:
                        if previous.source_url == url:
                            previous.payload.setdefault('query_hashes', []).append(plan['query_hash'])
                    continue
                # The query and snippet are discovery evidence, not a substitute for an application form.
                description = clean_text(f'{title}. {snippet}')
                seen_urls.add(url)
                records.append(SourceRecord(
                    external_id=stable_hash(url)[:40], title=title, company='', location='',
                    description=description, source_url=url, application_url=url,
                    payload={'_source_attribution': 'Brave Search', 'query': query, 'snippet': snippet, 'query_hashes': [plan['query_hash']]},
                ))
            self._record_query(plan, direct_count)
            self.query_plans.append({**plan, 'results': len(rows), 'direct_pages': direct_count})
            # If a site-scoped query fails, use an eligible open-web variant
            # next, inside the same query budget (never add unbounded retries).
            if len(records) == before and plan['components'].get('domain'):
                next_index = len(self.query_plans)
                broad = next((i for i in range(next_index, len(plans)) if not plans[i]['components'].get('domain')), None)
                if broad is not None:
                    plans[next_index], plans[broad] = plans[broad], plans[next_index]
                    self.emit_progress({'level': 'broaden', 'message': 'No new direct pages from this site; widening the next search to the open web.'})
            self.emit_progress({'level': 'search', 'message': f'Searched: {query} · {len(records)} direct pages found so far.',
                                'query': query, 'query_hash': plan['query_hash'], 'results': len(rows), 'discovered_count': len(records)})
        self.emit_progress({'level': 'identify', 'message': f'Identified {len(records)} unique candidate pages.', 'count': len(records)})
        return records

class GreenhouseConnector(SourceConnector):
    def fetch(self) -> list[SourceRecord]:
        board = clean_text(self.config.get('board_token') or self.config.get('board'))
        if not board:
            raise ValueError('Greenhouse sources require config.board_token.')
        validate_slug(board, 'Greenhouse board token')
        rows = self.get_json(f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true').get('jobs', [])
        company = clean_text(self.config.get('company')) or board.replace('-', ' ').title()
        return [SourceRecord(
            external_id=str(row.get('id', '')),
            title=clean_text(row.get('title')),
            company=company,
            location=clean_text((row.get('location') or {}).get('name')),
            description=_plain(row.get('content')),
            source_url=clean_text(row.get('absolute_url')),
            application_url=clean_text(row.get('absolute_url')),
            payload=row,
        ) for row in rows]


class LeverConnector(SourceConnector):
    def fetch(self) -> list[SourceRecord]:
        site = clean_text(self.config.get('site') or self.config.get('company_slug'))
        if not site:
            raise ValueError('Lever sources require config.site.')
        validate_slug(site, 'Lever site')
        rows = self.get_json(f'https://api.lever.co/v0/postings/{site}?mode=json')
        company = clean_text(self.config.get('company')) or site.replace('-', ' ').title()
        records = []
        for row in rows:
            categories = row.get('categories') or {}
            body = '\n'.join([_plain(row.get('descriptionPlain') or row.get('description'))] + [
                _plain(item.get('content')) for item in row.get('lists', [])
            ])
            records.append(SourceRecord(
                external_id=str(row.get('id', '')),
                title=clean_text(row.get('text')),
                company=company,
                location=clean_text(categories.get('location')),
                description=body,
                source_url=clean_text(row.get('hostedUrl')),
                application_url=clean_text(row.get('applyUrl') or row.get('hostedUrl')),
                payload=row,
            ))
        return records


class AshbyConnector(SourceConnector):
    def fetch(self) -> list[SourceRecord]:
        board = clean_text(self.config.get('board') or self.config.get('company_slug'))
        if not board:
            raise ValueError('Ashby sources require config.board.')
        validate_slug(board, 'Ashby board')
        rows = self.get_json(f'https://api.ashbyhq.com/posting-api/job-board/{board}').get('jobs', [])
        company = clean_text(self.config.get('company')) or board.replace('-', ' ').title()
        return [SourceRecord(
            external_id=str(row.get('id') or stable_hash(str(row.get('jobUrl', '')))[:20]),
            title=clean_text(row.get('title')),
            company=company,
            location=clean_text(row.get('location')),
            description=_plain(row.get('descriptionPlain') or row.get('descriptionHtml')),
            source_url=clean_text(row.get('jobUrl')),
            application_url=clean_text(row.get('applyUrl') or row.get('jobUrl')),
            payload=row,
        ) for row in rows]


class JobicyConnector(SourceConnector):
    """Free public remote-job feed with structured location and salary data."""

    def fetch(self) -> list[SourceRecord]:
        count = max(1, min(100, int(self.config.get('count') or 30)))
        params: dict[str, str | int] = {'count': count}
        for key in ('geo', 'industry'):
            value = clean_text(self.config.get(key)).lower()
            if value:
                validate_slug(value, f'Jobicy {key}')
                params[key] = value
        tag = clean_text(self.config.get('tag'))
        if tag:
            params['tag'] = tag[:50]
        payload = self.get_json(f'https://jobicy.com/api/v2/remote-jobs?{urlencode(params)}')
        records = []
        for row in payload.get('jobs', []):
            url = clean_text(row.get('url'))
            job_types = ', '.join(clean_text(value) for value in row.get('jobType', []) if clean_text(value))
            levels = ', '.join(clean_text(value) for value in row.get('jobLevel', []) if clean_text(value)) if isinstance(row.get('jobLevel'), list) else clean_text(row.get('jobLevel'))
            salary = ''
            if row.get('salaryMin') is not None or row.get('salaryMax') is not None:
                salary = ' '.join(str(value) for value in [row.get('salaryCurrency'), row.get('salaryMin'), '-', row.get('salaryMax'), row.get('salaryPeriod')] if value not in {None, ''})
            description = '\n'.join(value for value in [
                _plain(row.get('jobDescription') or row.get('jobExcerpt')),
                f'Employment type: {job_types}' if job_types else '',
                f'Seniority: {levels}' if levels else '',
                f'Compensation: {salary}' if salary else '',
            ] if value)
            records.append(SourceRecord(
                external_id=str(row.get('id') or row.get('jobSlug') or stable_hash(url)[:20]),
                title=clean_text(row.get('jobTitle')),
                company=clean_text(row.get('companyName')),
                location=clean_text(row.get('jobGeo')),
                description=description,
                source_url=url,
                application_url=url,
                posted_at=_source_datetime(row.get('pubDate')),
                payload={**row, '_source_attribution': 'Jobicy'},
            ))
        return records


class ArbeitnowConnector(SourceConnector):
    """Free ATS-derived Europe/UK feed with optional local relevance filtering."""

    def fetch(self) -> list[SourceRecord]:
        pages = max(1, min(5, int(self.config.get('pages') or 1)))
        max_results = max(1, min(100, int(self.config.get('max_results') or 30)))
        remote_only = bool(self.config.get('remote_only'))
        configured_keywords = self.config.get('keywords') or []
        if isinstance(configured_keywords, str):
            configured_keywords = configured_keywords.split(',')
        keywords = [clean_text(value).lower() for value in configured_keywords if clean_text(value)]
        records = []
        for page in range(1, pages + 1):
            payload = self.get_json(f'https://www.arbeitnow.com/api/job-board-api?page={page}')
            for row in payload.get('data', []):
                if remote_only and not bool(row.get('remote')):
                    continue
                haystack = ' '.join([
                    clean_text(row.get('title')),
                    clean_text(row.get('description')),
                    ' '.join(clean_text(value) for value in row.get('tags', [])),
                ]).lower()
                if keywords and not any(keyword in haystack for keyword in keywords):
                    continue
                url = clean_text(row.get('url'))
                records.append(SourceRecord(
                    external_id=clean_text(row.get('slug')) or stable_hash(url)[:20],
                    title=clean_text(row.get('title')),
                    company=clean_text(row.get('company_name')),
                    location=clean_text(row.get('location')),
                    description=_plain(row.get('description')),
                    source_url=url,
                    application_url=url,
                    posted_at=_source_datetime(row.get('created_at')),
                    payload={**row, '_source_attribution': 'Arbeitnow'},
                ))
                if len(records) >= max_results:
                    return records
        return records


class RSSConnector(SourceConnector):
    def fetch(self) -> list[SourceRecord]:
        url = clean_text(self.config.get('url'))
        if not url:
            raise ValueError('RSS sources require config.url.')
        validate_public_url(url)
        response = requests.get(url, timeout=self.timeout, headers={'User-Agent': 'Forth/1.0'})
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        records = []
        for item in root.findall('.//item'):
            field = lambda name: clean_text(item.findtext(name) or '')
            link = field('link')
            description = _plain(item.findtext('description'))
            records.append(SourceRecord(
                external_id=field('guid') or stable_hash(link)[:20],
                title=field('title'),
                company=clean_text(self.config.get('company')),
                location='',
                description=description,
                source_url=link,
                application_url=link,
                payload={'guid': field('guid')},
            ))
        return records


CONNECTORS = {
    'brave': BraveSearchConnector,
    'greenhouse': GreenhouseConnector,
    'lever': LeverConnector,
    'ashby': AshbyConnector,
    'jobicy': JobicyConnector,
    'arbeitnow': ArbeitnowConnector,
    'rss': RSSConnector,
}


def _source_datetime(value: Any) -> datetime | None:
    if value is None or value == '':
        return None
    if isinstance(value, (int, float)) or str(value).isdigit():
        try:
            return datetime.fromtimestamp(int(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def validate_slug(value: str, label: str) -> None:
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}', value):
        raise ValueError(f'{label} contains invalid characters.')


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise ValueError('Source URLs must use http or https.')
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError('The source hostname could not be resolved.') from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError('Source URLs must resolve to a public network address.')


def connector_for(source: JobSource) -> SourceConnector:
    connector_name = clean_text((source.config or {}).get('connector')).lower()
    if (source.config or {}).get('demo') and not connector_name:
        return SourceConnector(source)
    if source.kind == 'brave':
        connector_name = 'brave'
    if source.kind != 'brave':
        raise ValueError('Only Brave web discovery sources are supported.')
    connector_class = CONNECTORS.get(connector_name)
    if connector_class is None:
        raise ValueError('Brave web discovery is the only supported connector.')
    return connector_class(source)


def persist_job_structure(job: JobPosting, *, source_payload: dict | None = None) -> JobPostingVersion:
    content_hash = stable_hash(job.description_text)
    current = job.versions.filter(content_hash=content_hash).first()
    if current:
        job.last_seen_at = timezone.now()
        job.freshness_status = 'fresh'
        job.save(update_fields=['last_seen_at', 'freshness_status', 'updated_at'])
        return current
    job.versions.filter(is_current=True).update(is_current=False)
    version_number = (job.versions.aggregate(value=Max('version'))['value'] or 0) + 1
    version = JobPostingVersion.objects.create(
        owner=job.owner,
        job=job,
        version=version_number,
        content_hash=content_hash,
        description_text=job.description_text,
        extracted_json=job.extracted_json,
        source_payload=source_payload or {},
        fetched_at=timezone.now(),
        is_current=True,
    )
    extracted = job.extracted_json or {}
    JobRequirement.objects.filter(job=job).delete()
    groups = [
        ('required', extracted.get('required_skills', []), 'skill', True, 90),
        ('preferred', extracted.get('preferred_skills', []), 'skill', False, 55),
        ('responsibility', extracted.get('responsibilities', []), 'responsibility', False, 45),
    ]
    for kind, values, category, is_hard, weight in groups:
        for value in values or []:
            text = clean_text(value)
            if text:
                JobRequirement.objects.create(
                    owner=job.owner, job=job, kind=kind, category=category,
                    text=text, normalized_value=text.lower()[:220], is_hard=is_hard, weight=weight,
                )
    return version


def _verify_job_page(record: SourceRecord, *, followed_employer: bool = False) -> tuple[str, str] | None:
    """Verify a bounded public detail page; extract JSON-LD without browser/LLM work."""
    url = record.source_url
    def is_ats(candidate):
        host = (urlparse(candidate).hostname or '').lower()
        return any(host == domain or host.endswith('.' + domain) for domain in BraveSearchConnector.ATS_DOMAINS)
    started_on_ats = is_ats(url)
    try:
        for _ in range(5):
            validate_public_url(url)
            with requests.get(url, timeout=8, allow_redirects=False, stream=True, headers={'User-Agent': 'Forth/1.0'}) as response:
                if response.status_code in {404, 410}:
                    return 'closed', 'The job page is no longer available.'
                if response.is_redirect:
                    target = urljoin(url, response.headers.get('Location', ''))
                    if not BraveSearchConnector._direct_job_result(target, record.title) or 'error=true' in target:
                        return 'closed', 'The link redirects to a job board instead of an active posting.'
                    url = target
                    continue
                if response.status_code != 200:
                    return 'page_unverified', f'The job page could not be verified (HTTP {response.status_code}).'
                content = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    content.extend(chunk)
                    if len(content) > 1_000_000:
                        return 'page_unverified', 'The job page exceeded the verification size limit.'
                page = content.decode('utf-8', errors='replace')
                break
        else:
            return 'page_unverified', 'The job page exceeded the redirect limit.'
    except (requests.RequestException, ValueError):
        return 'page_unverified', 'The job page was blocked or could not be reached.'
    record.payload = {**(record.payload or {}), 'verified_url': url, 'page_verified_at': timezone.now().isoformat()}
    if not started_on_ats and not followed_employer:
        # Reposts can help discovery, but import the verified employer page,
        # never the aggregator's copy. Multiple different jobs are ambiguous.
        targets = set()
        for href in re.findall(r'href=[\"\']([^\"\']+)', page, re.I):
            target = urljoin(url, html.unescape(href))
            if is_ats(target) and BraveSearchConnector._direct_job_result(target, record.title):
                targets.add(urlparse(target)._replace(query='', fragment='').geturl())
        if len(targets) == 1:
            record.payload['discovery_url'] = record.source_url
            record.source_url = record.application_url = next(iter(targets))
            record.external_id = stable_hash(record.source_url)[:40]
            return _verify_job_page(record, followed_employer=True)
    record.source_url = record.application_url = url
    record.external_id = stable_hash(url)[:40]
    employer_verified = started_on_ats or followed_employer

    def job_objects(value):
        if isinstance(value, dict):
            if 'JobPosting' in ([value.get('@type')] if isinstance(value.get('@type'), str) else value.get('@type', [])):
                yield value
            for child in value.values():
                if isinstance(child, (dict, list)):
                    yield from job_objects(child)
        elif isinstance(value, list):
            for child in value:
                yield from job_objects(child)

    for script in re.findall(r'<script\b[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', page, re.I | re.S):
        try:
            postings = list(job_objects(json.loads(script)))
        except (ValueError, RecursionError, TypeError):
            continue
        if not postings:
            continue
        job = postings[0]
        expires = _source_datetime(job.get('validThrough'))
        if expires and expires < timezone.now():
            return 'closed', 'The posting’s advertised closing date has passed.'
        description = _plain(job.get('description'))
        if not description:
            continue
        record.title = clean_text(job.get('title') or record.title)
        organization = job.get('hiringOrganization') or {}
        if isinstance(organization, dict):
            record.company = clean_text(organization.get('name'))
            organization_host = (urlparse(str(organization.get('url') or organization.get('sameAs') or '')).hostname or '').lower().removeprefix('www.')
            page_host = (urlparse(url).hostname or '').lower().removeprefix('www.')
            employer_verified = employer_verified or bool(organization_host and (page_host == organization_host or page_host.endswith('.' + organization_host)))
        locations = job.get('jobLocation') or []
        locations = locations if isinstance(locations, list) else [locations]
        location_parts = []
        location_countries = []
        for location in locations:
            address = location.get('address', {}) if isinstance(location, dict) else {}
            if isinstance(address, dict):
                for key in ['addressLocality', 'addressRegion', 'addressCountry']:
                    value = address.get(key)
                    if isinstance(value, dict):
                        value = value.get('name', '')
                    if value:
                        location_parts.append(str(value))
                        if key == 'addressCountry':
                            location_countries.append(str(value))
        countries = job.get('applicantLocationRequirements') or []
        applicant_countries = []
        for country in countries if isinstance(countries, list) else [countries]:
            if isinstance(country, dict) and country.get('name'):
                location_parts.append(str(country['name']))
                applicant_countries.append(str(country['name']))
        location_parts = ['Canada' if item == 'CA' else 'United States' if item == 'US' else item for item in location_parts]
        if 'TELECOMMUTE' in str(job.get('jobLocationType', '')).upper():
            location_parts.append('Remote')
        record.location = ', '.join(dict.fromkeys(location_parts))
        record.description = clean_text(f'{record.title}. {record.location}. {description}')[:20000]
        record.payload.update(snippet=record.description, search_snippet=record.payload.get('snippet', ''), structured_job=True,
                              eligibility_locations=applicant_countries or location_countries)
        record.posted_at = _source_datetime(job.get('datePosted'))
        break
    if not employer_verified:
        return 'employer_unverified', 'Could not establish an original employer posting behind this search result.'
    return None


@transaction.atomic
def _triage_records(source: JobSource, records: list[SourceRecord]) -> list[SourceRecord]:
    """Cheap, deterministic shortlist. No chat/completion model is called here."""
    profile = refresh_profile_embedding(source.owner)
    profile_evidence = profile_embedding_text(source.owner)
    threshold = max(1, min(99, int((source.config or {}).get('min_triage_score') or 45)))
    existing_urls = set(JobPosting.objects.filter(owner=source.owner).values_list('source_url', flat=True))
    ranked: list[tuple[float, SourceRecord]] = []
    pages_verified = 0
    verified_urls = set()
    for index, record in enumerate(records):
        assessment = cheap_assessment(profile, record, profile_evidence=profile_evidence)
        if index < 80 and assessment['reason_code'] in {'qualified', 'insufficient_evidence', 'discipline_unverified', 'location_unverified', 'remote_unverified'}:
            if pages_verified >= 12:
                assessment.update(eligible=False, reason_code='verification_limit', reason='The 12-page verification budget was reached.')
            else:
                pages_verified += 1
                problem = _verify_job_page(record)
                if problem:
                    assessment.update(eligible=False, reason_code=problem[0], reason=problem[1])
                else:
                    assessment = cheap_assessment(profile, record, profile_evidence=profile_evidence)
        record.payload = {**(record.payload or {}), 'triage': {**assessment, 'threshold': threshold}}
        triage = record.payload['triage']
        if index >= 80:
            triage.update(eligible=False, reason_code='evaluation_limit', reason='The 80-page evaluation budget was reached.')
        if not triage['eligible']:
            continue
        if record.source_url in verified_urls:
            triage.update(eligible=False, reason_code='duplicate', reason='Another search result resolved to this same employer posting.')
            continue
        verified_urls.add(record.source_url)
        evidence = f"{record.title}\n{clean_text((record.payload or {}).get('snippet') or record.description)}"
        embedding_key = stable_hash(f"discovery-v4:{source.owner_id}:{getattr(settings, 'OPENAI_EMBEDDING_MODEL', '')}:{getattr(settings, 'OPENAI_EMBEDDING_DIMENSIONS', '')}:{evidence}")
        vector = cache.get(embedding_key)
        if vector is None:
            result = embed_text_result(evidence)
            vector = result.vector
            if result.provider == 'openai':
                cache.set(embedding_key, vector, timeout=7 * 86400)
        semantic = max(0.0, min(1.0, vector_similarity(profile.semantic_embedding, vector)))
        score = round(min(100, triage['lexical_score'] + semantic * 15))
        triage.update(score=score, semantic_similarity=round(semantic * 100), existing=record.source_url in existing_urls)
        if score < threshold:
            triage.update(eligible=False, reason_code='below_threshold', reason=f'Fit score {score} is below your {threshold} minimum.')
            continue
        ranked.append((score, record))
    ranked.sort(key=lambda item: (item[1].payload['triage']['existing'], -item[0], item[1].title.lower()))
    limit = max(1, min(8, int((source.config or {}).get('max_candidates') or 5)))
    for _, record in ranked[limit:]:
        record.payload['triage'].update(eligible=False, reason_code='run_limit', reason=f'Qualified, but outside this run’s {limit}-job import budget; new opportunities are prioritized.')
    return [record for _, record in ranked[:limit]]


@transaction.atomic
def upsert_source_record(source: JobSource, record: SourceRecord, *, fast: bool = False) -> tuple[JobPosting, bool]:
    from core.services import import_job_posting

    lookup = {'owner': source.owner, 'source': source, 'source_external_id': record.external_id}
    existing = JobPosting.objects.filter(**lookup).first() if record.external_id else None
    if existing is None:
        existing = JobPosting.objects.filter(owner=source.owner, source_url=record.source_url).first()
    if existing:
        if fast:
            extracted = {'extractor': 'search_triage', **(record.payload or {})}
        else:
            from core.ai import extract_job

            extracted_result = extract_job(record.description, source_url=record.source_url)
            extracted = {**extracted_result.data, 'extractor': extracted_result.source}
        existing.title = record.title or existing.title
        existing.company = record.company or existing.company
        existing.location = record.location or existing.location
        existing.description_text = record.description or existing.description_text
        existing.source_url = record.source_url or existing.source_url
        existing.application_url = record.application_url or existing.application_url
        existing.canonical_url = record.source_url or existing.canonical_url
        existing.last_seen_at = timezone.now()
        existing.freshness_status = 'fresh'
        existing.extracted_json = extracted
        existing.save()
        persist_job_structure(existing, source_payload=record.payload)
        from core.domain.embeddings import refresh_job_embedding
        from core.domain.matching import recompute_match

        refresh_job_embedding(existing)
        recompute_match(existing)
        return existing, False

    if fast:
        # Brave snippets are triaged by embeddings before this point. Avoid an
        # expensive completion just to turn a search result into a review card.
        job = JobPosting.objects.create(
            owner=source.owner, source=source, title=record.title[:240], company=record.company[:220],
            location=record.location[:220], description_text=record.description,
            source_url=record.source_url, application_url=record.application_url,
            canonical_url=record.source_url, source_external_id=record.external_id,
            content_hash=stable_hash(record.description), extracted_json={'extractor': 'search_triage', **(record.payload or {})},
            posted_at=record.posted_at, last_seen_at=timezone.now(),
        )
    else:
        job = import_job_posting(source.owner, text=record.description, source_url=record.source_url, source=source, score=False)
    job.title = record.title or job.title
    job.company = record.company or job.company
    job.location = record.location or job.location
    job.application_url = record.application_url or job.application_url
    job.canonical_url = record.source_url
    job.source_external_id = record.external_id
    job.posted_at = record.posted_at
    job.last_seen_at = timezone.now()
    job.save()
    persist_job_structure(job, source_payload=record.payload)
    from core.domain.embeddings import refresh_job_embedding
    from core.domain.matching import recompute_match

    refresh_job_embedding(job)
    recompute_match(job)
    return job, True


def execute_source_run(run: SourceRun) -> SourceRun:
    run.status = 'running'
    run.started_at = timezone.now()
    run.log = []
    run.save(update_fields=['status', 'started_at', 'log', 'updated_at'])
    try:
        from core.realtime_events import publish_user_event

        def progress(event):
            if 'discovered_count' in event:
                run.discovered_count = event['discovered_count']
            run.log.append(event)
            # Persist every stage so HTTP polling and websocket clients see the same snapshot.
            run.save(update_fields=['log', 'discovered_count', 'imported_count', 'updated_count', 'skipped_count', 'error_count', 'updated_at'])
            publish_user_event(run.owner_id, 'source_run_progress', {
                'source_run_id': run.id, 'source_id': run.source_id, 'event': event,
                'sequence': len(run.log),
                'counts': {field: getattr(run, field) for field in ('discovered_count', 'imported_count', 'updated_count', 'skipped_count', 'error_count')},
            })

        connector = connector_for(run.source)
        connector.on_progress = progress
        records = connector.fetch()
        if getattr(connector, 'query_plans', None):
            run.cursor = {'queries': connector.query_plans}
        run.discovered_count = len(records)
        progress({'level': 'evaluating', 'message': f'Checking {len(records)} pages against your profile.'})
        all_records = records
        records = _triage_records(run.source, records) if run.source.kind == 'brave' else records
        run.skipped_count = run.discovered_count - len(records)
        reasons = {}
        for record in all_records:
            triage = (record.payload or {}).get('triage') or {}
            if triage.get('eligible') is False:
                reason = triage.get('reason', 'Not selected')
                code = triage.get('reason_code', 'not_selected')
                reasons[code] = reasons.get(code, 0) + 1
                progress({'level': 'rejected', 'title': record.title, 'url': record.source_url,
                          'reason': reason, 'reason_code': code, 'score': triage.get('score'),
                          'threshold': triage.get('threshold'), 'message': f'{record.title}: {reason}'})
        if reasons:
            progress({'level': 'rejection_summary', 'reasons': reasons,
                      'message': 'Not imported: ' + ', '.join(f'{count} {code.replace("_", " ")}' for code, count in reasons.items()) + '.'})
        progress({'level': 'evaluate', 'count': len(records), 'message': f'Shortlisted {len(records)} of {run.discovered_count} pages using profile fit.'})
        for index, record in enumerate(records, start=1):
            triage = (record.payload or {}).get('triage') or {}
            progress({
                'level': 'candidate', 'rank': index, 'title': record.title,
                'score': triage.get('score', 0),
                'semantic_similarity': triage.get('semantic_similarity', 0),
                'message': f'#{index} · {record.title} · {triage.get("score", 0)} discovery fit',
            })
        imported_ids, refreshed_ids = set(), set()
        for record in records:
            try:
                _, created = upsert_source_record(run.source, record, fast=(run.source.kind == 'brave'))
                if created:
                    run.imported_count += 1
                    imported_ids.add(record.external_id)
                else:
                    run.updated_count += 1
                    refreshed_ids.add(record.external_id)
                progress({'level': 'import', 'created': created, 'external_id': record.external_id,
                          'message': f'{"Imported" if created else "Refreshed"}: {record.title}'})
            except Exception as exc:
                run.error_count += 1
                progress({'level': 'error', 'message': str(exc)[:500], 'external_id': record.external_id})
        for plan in getattr(connector, 'query_plans', []):
            matching = [record for record in all_records if plan['query_hash'] in (record.payload or {}).get('query_hashes', [])]
            memory = SourceSearchQuery.objects.filter(source=run.source, query_hash=plan['query_hash']).first()
            if memory:
                memory.components = {**memory.components, '_outcomes': {
                    'qualified': sum(bool((r.payload or {}).get('triage', {}).get('eligible')) or (r.payload or {}).get('triage', {}).get('reason_code') == 'run_limit' for r in matching),
                    'imported': sum(r.external_id in imported_ids for r in matching),
                    'refreshed': sum(r.external_id in refreshed_ids for r in matching),
                }}
                memory.save(update_fields=['components', 'updated_at'])
        run.status = 'partial' if run.error_count else 'succeeded'
    except Exception as exc:
        run.status = 'failed'
        run.error_count += 1
        run.log.append({'level': 'error', 'message': str(exc)[:500]})
    run.completed_at = timezone.now()
    run.save()
    source = run.source
    source.last_run_at = run.completed_at
    source.last_status = run.status
    source.last_message = f'{run.imported_count} new, {run.updated_count} refreshed, {run.error_count} errors.'
    source.save(update_fields=['last_run_at', 'last_status', 'last_message', 'updated_at'])
    return run
