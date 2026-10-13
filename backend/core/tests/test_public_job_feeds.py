from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from datetime import timedelta
from django.utils import timezone

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from core.domain.sourcing import ArbeitnowConnector, BraveSearchConnector, JobicyConnector, SourceRecord, _triage_records, _verify_job_page, connector_for, execute_source_run
from core.domain.discovery_quality import cheap_assessment, role_variants
from core.models import JobSource, SourceSearchQuery, SourceRun


class PublicJobFeedConnectorTests(SimpleTestCase):
    def source(self, connector, **config):
        return SimpleNamespace(kind='api', config={'connector': connector, **config})

    def test_jobicy_preserves_structured_job_metadata(self):
        connector = JobicyConnector(self.source(
            'jobicy', count=12, geo='canada', industry='engineering', tag='platform engineer',
        ))
        response = {'jobs': [{
            'id': 149241,
            'url': 'https://jobicy.com/jobs/149241-platform-engineer',
            'jobTitle': 'Platform Engineer',
            'companyName': 'Northstar',
            'jobGeo': 'Canada',
            'jobType': ['Full-Time'],
            'jobLevel': 'Senior',
            'jobDescription': '<p>Build dependable platform services.</p>',
            'pubDate': '2026-08-14T04:45:02+00:00',
            'salaryMin': 180000,
            'salaryMax': 220000,
            'salaryCurrency': 'CAD',
            'salaryPeriod': 'yearly',
        }]}

        with patch.object(connector, 'get_json', return_value=response) as get_json:
            records = connector.fetch()

        self.assertIn('geo=canada', get_json.call_args.args[0])
        self.assertIn('tag=platform+engineer', get_json.call_args.args[0])
        self.assertEqual(records[0].company, 'Northstar')
        self.assertEqual(records[0].location, 'Canada')
        self.assertIn('CAD 180000 - 220000 yearly', records[0].description)
        self.assertEqual(records[0].posted_at.isoformat(), '2026-08-14T04:45:02+00:00')
        self.assertEqual(records[0].payload['_source_attribution'], 'Jobicy')

    def test_arbeitnow_applies_remote_and_relevance_caps(self):
        connector = ArbeitnowConnector(self.source(
            'arbeitnow', pages=1, max_results=1, remote_only=True,
            keywords=['platform', 'backend'],
        ))
        response = {'data': [
            {
                'slug': 'onsite-role', 'title': 'Platform Engineer', 'company_name': 'OfficeCo',
                'location': 'Berlin', 'remote': False, 'description': 'Platform work',
                'url': 'https://www.arbeitnow.com/jobs/onsite-role', 'created_at': 1786708828,
                'tags': ['Engineering'],
            },
            {
                'slug': 'remote-role', 'title': 'Backend Lead', 'company_name': 'RemoteCo',
                'location': 'Europe', 'remote': True, 'description': '<p>Lead backend systems.</p>',
                'url': 'https://www.arbeitnow.com/jobs/remote-role', 'created_at': 1786708828,
                'tags': ['Software Development'],
            },
        ]}

        with patch.object(connector, 'get_json', return_value=response):
            records = connector.fetch()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].external_id, 'remote-role')
        self.assertEqual(records[0].company, 'RemoteCo')
        self.assertEqual(records[0].payload['_source_attribution'], 'Arbeitnow')

    def test_connector_factory_only_allows_brave_discovery(self):
        source = SimpleNamespace(kind='brave', config={'connector': 'brave'}, owner=SimpleNamespace())
        self.assertIsInstance(connector_for(source), BraveSearchConnector)
        with self.assertRaisesRegex(ValueError, 'Only Brave'):
            connector_for(self.source('jobicy'))

    def test_brave_rejects_aggregator_brands_hosted_on_an_ats(self):
        self.assertFalse(BraveSearchConnector._direct_job_result(
            'https://jobs.lever.co/jobgether/123',
            'Jobgether - Senior Engineering Manager',
        ))

    def test_modern_greenhouse_details_are_accepted_but_boards_are_not(self):
        self.assertTrue(BraveSearchConnector._direct_job_result('https://job-boards.greenhouse.io/acme/jobs/123456', 'Engineering Manager'))
        self.assertFalse(BraveSearchConnector._direct_job_result('https://job-boards.greenhouse.io/acme', 'Acme careers'))
        self.assertFalse(BraveSearchConnector._direct_job_result('https://job-boards.greenhouse.io.evil.example/acme/123', 'Engineering Manager'))


class DiscoveryEvidenceTests(SimpleTestCase):
    def setUp(self):
        self.profile = SimpleNamespace(target_roles=['Engineering Lead'], authorized_countries=['Canada'], work_modes=['remote'])

    def record(self, title='Engineering Manager', snippet='Lead our software developers building backend services. This is a fully remote role based in Canada.'):
        return SourceRecord('test', title, '', '', snippet, 'https://jobs.lever.co/acme/test', '', payload={'snippet': snippet, 'query': 'engineering lead remote Canada'})

    def test_equivalent_titles_get_equal_credit_without_awkward_variants(self):
        for title in ['Engineering Lead', 'Engineering Manager', 'Technical Lead', 'Lead Software Engineer']:
            result = cheap_assessment(self.profile, self.record(title))
            self.assertTrue(result['eligible'], result)
            self.assertEqual(result['lexical_score'], 85)
        self.assertNotIn('engineering technical lead', role_variants(self.profile.target_roles))

    def test_query_location_is_not_job_evidence(self):
        result = cheap_assessment(self.profile, self.record(snippet='Lead software developers building reliable backend services with our distributed team.'))
        self.assertEqual(result['reason_code'], 'location_unverified')

    def test_wrong_discipline_and_office_roles_still_fail(self):
        self.assertEqual(cheap_assessment(self.profile, self.record('Mechanical Engineering Manager'))['reason_code'], 'role_mismatch')
        self.assertEqual(cheap_assessment(self.profile, self.record(snippet='Lead our software team in Canada. Hybrid office attendance with occasional remote work.'))['reason_code'], 'remote_unverified')

    def test_native_mobile_specialism_requires_profile_evidence(self):
        record = self.record('Lead Software Engineer (Mobile Native)')
        self.assertEqual(cheap_assessment(self.profile, record, profile_evidence='Lead full-stack Python and React web teams')['reason_code'], 'specialty_mismatch')
        self.assertTrue(cheap_assessment(self.profile, record, profile_evidence='Led native mobile delivery with Swift and Kotlin')['eligible'])

    def test_canada_us_postings_allowed_but_explicit_us_only_rejected(self):
        self.assertTrue(cheap_assessment(self.profile, self.record(snippet='Lead software developers remotely in Canada or the United States. Join our remote team.'))['eligible'])
        self.assertEqual(cheap_assessment(self.profile, self.record(snippet='Lead software developers. Remote US-only position. Our company also has customers in Canada.'))['reason_code'], 'location_mismatch')

    def test_redirect_to_closed_board_is_rejected(self):
        response = MagicMock(status_code=302, is_redirect=True, headers={'Location': '/acme?error=true'})
        response.__enter__.return_value = response
        with patch('core.domain.sourcing.validate_public_url'), patch('core.domain.sourcing.requests.get', return_value=response):
            self.assertEqual(_verify_job_page(self.record())[0], 'closed')

    def test_structured_eligibility_overrides_incidental_country_mentions(self):
        record = self.record()
        record.payload['eligibility_locations'] = ['US']
        self.assertEqual(cheap_assessment(self.profile, record)['reason_code'], 'location_mismatch')
        record.payload['eligibility_locations'] = ['US', 'CA']
        self.assertTrue(cheap_assessment(self.profile, record)['eligible'])

    def test_company_customer_countries_are_not_hiring_eligibility(self):
        record = self.record(snippet='Lead software developers remotely. We sell to customers in Canada and the United States.')
        record.location = 'Santa Cruz, California'
        record.payload['structured_job'] = True
        self.assertFalse(cheap_assessment(self.profile, record)['eligible'])

    def test_repost_resolves_original_employer_and_custom_greenhouse_redirect(self):
        repost = MagicMock(status_code=200, is_redirect=False)
        repost.__enter__.return_value = repost
        repost.iter_content.return_value = [b'<a href="https://boards.greenhouse.io/acme/jobs/12345">Apply</a>']
        redirect = MagicMock(status_code=302, is_redirect=True, headers={'Location': 'https://acme.careers/job?gh_jid=12345'})
        redirect.__enter__.return_value = redirect
        employer = MagicMock(status_code=200, is_redirect=False)
        employer.__enter__.return_value = employer
        employer.iter_content.return_value = [b'<html>Engineering Manager, software team, Remote Canada</html>']
        record = self.record()
        record.source_url = 'https://repost.example/job/12345-engineering-manager'
        with patch('core.domain.sourcing.validate_public_url'), patch('core.domain.sourcing.requests.get', side_effect=[repost, redirect, employer]):
            self.assertIsNone(_verify_job_page(record))
        self.assertEqual(record.source_url, 'https://acme.careers/job?gh_jid=12345')
        self.assertEqual(record.application_url, record.source_url)
        self.assertIn('repost.example', record.payload['discovery_url'])

    def test_unverified_repost_does_not_pass(self):
        response = MagicMock(status_code=200, is_redirect=False)
        response.__enter__.return_value = response
        response.iter_content.return_value = [b'<html>Engineering Manager, remote Canada</html>']
        record = self.record()
        record.source_url = 'https://repost.example/job/12345-engineering-manager'
        with patch('core.domain.sourcing.validate_public_url'), patch('core.domain.sourcing.requests.get', return_value=response):
            self.assertEqual(_verify_job_page(record)[0], 'employer_unverified')

    def test_structured_page_recovers_missing_search_snippet(self):
        response = MagicMock(status_code=200, is_redirect=False)
        response.__enter__.return_value = response
        response.iter_content.return_value = [b'''<script type="application/ld+json">{"@type":"JobPosting","title":"Engineering Manager","description":"Lead software developers building reliable backend services in a distributed team.","jobLocationType":"TELECOMMUTE","applicantLocationRequirements":{"@type":"Country","name":"Canada"},"hiringOrganization":{"name":"Example"}}</script>''']
        record = self.record(snippet='You need to enable JavaScript to run this app')
        with patch('core.domain.sourcing.validate_public_url'), patch('core.domain.sourcing.requests.get', return_value=response):
            self.assertIsNone(_verify_job_page(record))
        self.assertTrue(cheap_assessment(self.profile, record)['eligible'])
        self.assertEqual(record.company, 'Example')


class BraveQueryMemoryTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='query-memory@example.com', email='query-memory@example.com')
        self.source = JobSource.objects.create(
            owner=self.owner,
            name='Brave query memory',
            kind='brave',
            config={'connector': 'brave', 'queries_per_run': 1, 'queries': ['"engineering lead" remote', '"technical lead" Toronto']},
        )

    def test_query_plan_exhausts_unseen_combinations_before_repeating(self):
        connector = BraveSearchConnector(self.source)
        first = connector._query_plan()[0]
        connector._record_query(first, 3)

        next_plan = BraveSearchConnector(self.source)._query_plan()[0]
        self.assertNotEqual(next_plan['query_hash'], first['query_hash'])
        self.assertEqual(SourceSearchQuery.objects.get(source=self.source, query_hash=first['query_hash']).search_count, 1)

    def test_exhausted_recent_queries_are_not_repeated(self):
        self.source.config['queries_per_run'] = 2
        connector = BraveSearchConnector(self.source)
        for plan in connector._query_plan():
            connector._record_query(plan, 0)
        self.assertEqual(connector._query_plan(), [])

    def test_productive_search_returns_after_cooldown(self):
        connector = BraveSearchConnector(self.source)
        plan = connector._query_plan()[0]
        connector._record_query(plan, 4)
        memory = SourceSearchQuery.objects.get(source=self.source, query_hash=plan['query_hash'])
        memory.components['_outcomes'] = {'qualified': 2, 'imported': 1}
        memory.last_searched_at = timezone.now() - timedelta(hours=25)
        memory.save()
        self.assertEqual(connector._query_plan()[0]['query_hash'], plan['query_hash'])

    def test_remote_profile_searches_country_not_city_or_exact_specialty(self):
        from core.models import CandidateProfile
        profile, _ = CandidateProfile.objects.get_or_create(owner=self.owner)
        profile.target_roles = ['Engineering Lead']
        profile.location = 'Kitchener, Ontario, Canada'
        profile.authorized_countries = ['Canada']
        profile.work_modes = ['remote']
        profile.target_industries = ['Developer tools']
        profile.save()
        candidates = BraveSearchConnector(self.source)._profile_query_candidates()
        self.assertTrue(any('remote Canada' in row['query'] for row in candidates))
        self.assertTrue(any(not row['components']['domain'] for row in candidates))
        self.assertFalse(any('Kitchener' in row['query'] or 'Developer tools' in row['query'] or 'engineering technical lead' in row['query'] for row in candidates))
        self.source.config = {'queries_per_run': 8}
        plans = BraveSearchConnector(self.source)._query_plan()
        self.assertEqual(sum(not row['components']['domain'] for row in plans), 2)
        self.assertTrue(all(row['components']['freshness'] == '' for row in plans))
        self.assertTrue(any(row['components']['freshness'] == 'pm' for row in candidates))

    def test_rejected_pages_do_not_spend_embedding_calls(self):
        self.source.config['min_triage_score'] = 85
        profile = SimpleNamespace(target_roles=['Engineering Lead'], authorized_countries=['Canada'], work_modes=['remote'], semantic_embedding=[1., 0.])
        good = SourceRecord('good', 'Engineering Manager', '', '', 'Software team leadership, remote in Canada, building robust backend services.', 'https://jobs.lever.co/acme/good', '')
        bad = SourceRecord('bad', 'Mechanical Engineering Manager', '', '', good.description, 'https://jobs.lever.co/acme/bad', '')
        with patch('core.domain.sourcing.refresh_profile_embedding', return_value=profile), \
             patch('core.domain.sourcing._verify_job_page', return_value=None), \
             patch('core.domain.sourcing.cache.get', return_value=None), \
             patch('core.domain.sourcing.embed_text_result', return_value=SimpleNamespace(vector=[.5, .5], provider='local_fallback')) as embed:
            selected = _triage_records(self.source, [bad, good])
        self.assertEqual(selected, [good])
        self.assertEqual(embed.call_count, 1)
        self.assertGreaterEqual(good.payload['triage']['score'], 85)
        self.assertEqual(bad.payload['triage']['reason_code'], 'role_mismatch')

    @override_settings(BRAVE_SEARCH_API_KEY='test-key')
    def test_progress_is_persisted_during_search_and_each_import(self):
        self.source.config['queries_per_run'] = 2
        self.source.save()
        run = SourceRun.objects.create(owner=self.owner, source=self.source)
        request_number = 0

        def search(*args, **kwargs):
            nonlocal request_number
            request_number += 1
            if request_number == 2:
                live = SourceRun.objects.get(pk=run.pk)
                self.assertEqual(live.status, 'running')
                self.assertEqual(live.discovered_count, 1)
                self.assertEqual(sum(event['level'] == 'search' for event in live.log), 1)
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'web': {'results': [{
                'title': 'Software Engineering Lead',
                'url': f'https://jobs.lever.co/example/{request_number}',
                'description': 'Lead a software team building distributed infrastructure, remote anywhere in Canada.',
            }]}})

        imports = 0

        def save_record(*args, **kwargs):
            nonlocal imports
            live = SourceRun.objects.get(pk=run.pk)
            self.assertEqual(live.discovered_count, 2)
            self.assertEqual(live.imported_count, imports)
            self.assertEqual(sum(event['level'] == 'candidate' for event in live.log), 2)
            imports += 1
            return None, True

        with patch('core.domain.sourcing.requests.get', side_effect=search), \
             patch('core.domain.sourcing._triage_records', side_effect=lambda source, records: records), \
             patch('core.domain.sourcing.upsert_source_record', side_effect=save_record), \
             patch('core.realtime_events.publish_user_event') as publish:
            execute_source_run(run)

        run.refresh_from_db()
        self.assertEqual((run.status, run.discovered_count, run.imported_count), ('succeeded', 2, 2))
        snapshots = [call.args[2] for call in publish.call_args_list]
        self.assertEqual([item['sequence'] for item in snapshots], list(range(1, len(snapshots) + 1)))
        self.assertEqual(snapshots[-1]['counts']['imported_count'], 2)

    @override_settings(BRAVE_SEARCH_API_KEY='test-key')
    def test_direct_page_with_short_snippet_reaches_verification(self):
        connector = BraveSearchConnector(self.source)
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'web': {'results': [{
            'title': 'Engineering Manager', 'url': 'https://jobs.ashbyhq.com/acme/123456',
            'description': 'Enable JavaScript',
        }]}})
        with patch('core.domain.sourcing.requests.get', return_value=response):
            records = connector.fetch()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].payload['snippet'], 'Enable JavaScript')

    @override_settings(BRAVE_SEARCH_API_KEY='test-key')
    def test_zero_results_do_not_report_phantom_pages(self):
        run = SourceRun.objects.create(owner=self.owner, source=self.source)
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'web': {'results': []}})
        with patch('core.domain.sourcing.requests.get', return_value=response), \
             patch('core.domain.sourcing._triage_records', return_value=[]), \
             patch('core.realtime_events.publish_user_event'):
            execute_source_run(run)
        run.refresh_from_db()
        self.assertEqual((run.status, run.discovered_count, run.imported_count), ('succeeded', 0, 0))
        self.assertEqual(next(event for event in run.log if event['level'] == 'evaluate')['count'], 0)
