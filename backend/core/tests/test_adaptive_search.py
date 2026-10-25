from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.domain.search_criteria import static_search_criteria
from core.domain.sourcing import BraveSearchConnector
from core.models import CandidateProfile, JobSource, ProfileFact
from core.serializers import JobSourceSerializer


class AdaptiveSearchTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='adaptive-search')
        self.profile, _ = CandidateProfile.objects.get_or_create(owner=self.owner)
        self.profile.target_roles = ['Platform Engineer']
        self.profile.authorized_countries = ['Canada']
        self.profile.work_modes = ['remote']
        self.profile.save()
        self.source = JobSource.objects.create(owner=self.owner, kind='brave', name='Search', config={
            'adaptive_search': False, 'queries_per_run': 8,
            'static_criteria': static_search_criteria(self.owner),
        })

    def test_static_search_survives_profile_drift(self):
        before = BraveSearchConnector(self.source)._query_plan()
        self.profile.target_roles = ['Data Engineer']
        self.profile.save()
        self.assertEqual(before, BraveSearchConnector(self.source)._query_plan())

    def test_adaptive_search_uses_current_profile_and_owner_skills(self):
        self.source.config.update(adaptive_search=True, queries=['stale marketing search'])
        ProfileFact.objects.create(owner=self.owner, fact_type='skill', title='Python', verified_by_user=True)
        other = get_user_model().objects.create_user(username='other-search')
        ProfileFact.objects.create(owner=other, fact_type='skill', title='PrivateSkill')
        plans = BraveSearchConnector(self.source)._query_plan()
        self.assertTrue(any('Python' in row['query'] for row in plans))
        self.assertTrue(all('remote Canada' in row['query'] or 'remote worldwide' in row['query'] for row in plans))
        self.assertFalse(any('stale' in row['query'] or 'PrivateSkill' in row['query'] for row in plans))
        self.profile.target_roles = ['Data Engineer']
        self.profile.save()
        updated = BraveSearchConnector(self.source)._query_plan()
        self.assertTrue(all('data engineer' in row['query'] for row in updated))
        self.assertTrue(set(row['query_hash'] for row in plans).isdisjoint(row['query_hash'] for row in updated))
        self.source.config['adaptive_search'] = False
        self.assertEqual(BraveSearchConnector(self.source)._query_plan()[0]['query'], 'stale marketing search')

    def test_adaptive_without_skills_still_searches_roles(self):
        self.source.config['adaptive_search'] = True
        self.assertTrue(BraveSearchConnector(self.source)._query_plan())
        self.profile.target_roles = []
        self.profile.save()
        self.assertEqual(BraveSearchConnector(self.source)._query_plan(), [])

    def test_unsuitable_skill_evidence_is_not_used(self):
        self.source.config['adaptive_search'] = True
        ProfileFact.objects.create(owner=self.owner, fact_type='skill', title='UncertainSkill', confidence='low')
        ProfileFact.objects.create(owner=self.owner, fact_type='skill', title='RejectedSkill', lifecycle='rejected')
        plans = BraveSearchConnector(self.source)._query_plan()
        self.assertTrue(plans)
        self.assertTrue(all('specialty' not in row['components'] for row in plans))

    def test_new_api_source_freezes_default_criteria(self):
        serializer = JobSourceSerializer(data={'name': 'New search', 'kind': 'brave'}, context={'request': SimpleNamespace(user=self.owner)})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        source = serializer.save(owner=self.owner)
        self.assertIs(source.config['adaptive_search'], False)
        self.assertEqual(source.config['static_criteria'], static_search_criteria(self.owner))

    def test_migration_preserves_custom_queries(self):
        from importlib import import_module
        from django.apps import apps
        from django.db import connection

        self.source.config = {'queries': ['custom query'], 'country': 'US'}
        self.source.save()
        migration = import_module('core.migrations.0020_static_search_criteria')
        migration.freeze_search_criteria(apps, SimpleNamespace(connection=connection))
        self.source.refresh_from_db()
        self.assertEqual(self.source.config['queries'], ['custom query'])
        self.assertEqual(self.source.config['country'], 'US')
        self.assertEqual(self.source.config['static_criteria'], static_search_criteria(self.owner))

    def test_api_preserves_static_criteria_and_validates_toggle(self):
        context = {'request': SimpleNamespace(user=self.owner)}
        serializer = JobSourceSerializer(self.source, data={'config': {'adaptive_search': True}}, partial=True, context=context)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        saved = serializer.save()
        self.assertEqual(saved.config['static_criteria']['target_roles'], ['Platform Engineer'])
        invalid = JobSourceSerializer(self.source, data={'config': {'adaptive_search': 'false'}}, partial=True, context=context)
        self.assertFalse(invalid.is_valid())
