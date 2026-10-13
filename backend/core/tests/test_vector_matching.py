from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.ai import embed_text_result
from core.domain.embeddings import (
    job_embedding_text,
    profile_embedding_text,
    refresh_fact_embedding,
    refresh_job_embedding,
    refresh_profile_embedding,
)
from core.domain.matching import recompute_match
from core.domain.profiles import authoritative_facts
from core.domain.scoring import normalize_match_score
from core.models import CandidateProfile, JobPosting, JobRequirement, ProfileFact


@override_settings(
    OPENAI_API_KEY='',
    OPENAI_EMBEDDING_MODEL='text-embedding-3-large',
    OPENAI_EMBEDDING_DIMENSIONS=3072,
)
class VectorMatchingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='vector-user', password='password')
        self.profile = CandidateProfile.objects.create(
            owner=self.user,
            headline='Staff platform engineer',
            professional_summary='Builds reliable distributed developer platforms.',
            target_roles=['Staff Platform Engineer'],
            work_modes=['remote'],
        )
        self.fact = ProfileFact.objects.create(
            owner=self.user,
            fact_type='achievement',
            title='Reliable platform delivery',
            statement='Led Python, Django, PostgreSQL, and Celery platform delivery.',
            verified_by_user=True,
            lifecycle='verified',
        )
        self.job = JobPosting.objects.create(
            owner=self.user,
            title='Staff Platform Engineer',
            company='Northstar',
            remote_policy='remote',
            description_text='Lead a reliable Python and Django platform backed by PostgreSQL and Celery.',
            content_hash='vector-job',
        )
        JobRequirement.objects.create(
            owner=self.user,
            job=self.job,
            kind='required',
            category='skill',
            text='Python',
            normalized_value='python',
            is_hard=True,
            weight=90,
        )

    def test_canonical_text_includes_candidate_and_job_evidence(self):
        self.assertIn('Staff platform engineer', profile_embedding_text(self.user))
        self.assertIn('Reliable platform delivery', profile_embedding_text(self.user))
        self.assertIn('required skill: Python', job_embedding_text(self.job))

    def test_normalized_score_anchors_profile_threshold_at_eighty(self):
        self.assertEqual(normalize_match_score(50, 50), 80)
        self.assertEqual(normalize_match_score(60, 60), 80)
        self.assertEqual(normalize_match_score(100, 50), 100)

    def test_refresh_persists_fixed_width_pgvector_values_and_metadata(self):
        refresh_fact_embedding(self.fact)
        refresh_profile_embedding(self.user)
        refresh_job_embedding(self.job)
        self.fact.refresh_from_db()
        self.profile.refresh_from_db()
        self.job.refresh_from_db()

        for item in (self.fact, self.profile, self.job):
            self.assertEqual(len(item.semantic_embedding), 3072)
            self.assertEqual(item.embedding_provider, 'local_fallback')
            self.assertTrue(item.embedding_content_hash)
            self.assertIsNotNone(item.embedding_updated_at)

    def test_match_uses_dedicated_semantic_signal_and_nearest_fact(self):
        refresh_fact_embedding(self.fact)
        match = recompute_match(self.job)

        semantic = match.signals.get(kind='semantic')
        self.assertGreater(semantic.score, 0)
        self.assertEqual(semantic.weight, 35)
        self.assertEqual(match.explanation_json['score_version'], '2026-10-v6-grounded-inference')
        self.assertIn('top_evidence_similarity', match.explanation_json)
        self.assertIn('blended_semantic_similarity', match.explanation_json)
        self.assertEqual(match.explanation_json['embedding_provider'], 'local_fallback')
        self.assertIn(self.fact.id, [item['fact_id'] for item in match.supporting_facts])

    def test_changed_job_content_invalidates_embedding_hash(self):
        refresh_job_embedding(self.job)
        self.job.refresh_from_db()
        original_hash = self.job.embedding_content_hash
        self.job.description_text += ' Own Kubernetes infrastructure and observability.'
        self.job.save(update_fields=['description_text', 'updated_at'])

        refresh_job_embedding(self.job)
        self.job.refresh_from_db()
        self.assertNotEqual(self.job.embedding_content_hash, original_hash)

    def test_match_splits_requirement_prose_and_does_not_count_preferred_gaps_as_required(self):
        JobRequirement.objects.all().delete()
        JobRequirement.objects.create(
            owner=self.user,
            job=self.job,
            kind='required',
            category='skill',
            text='In-depth experience with Python and Django web applications.',
            normalized_value='in-depth experience with python and django web applications',
            is_hard=True,
        )
        JobRequirement.objects.create(
            owner=self.user,
            job=self.job,
            kind='preferred',
            category='skill',
            text='React and LLM evaluation experience.',
            normalized_value='react and llm evaluation experience',
            is_hard=False,
        )

        match = recompute_match(self.job)

        self.assertIn('python', match.explanation_json['covered_skills'])
        self.assertIn('django', match.explanation_json['covered_skills'])
        self.assertNotIn('react', match.missing_requirements)
        self.assertIn('react', match.explanation_json['preferred_gaps'])

    def test_django_evidence_partially_covers_python_without_claiming_api_experience(self):
        self.fact.statement = 'Led delivery of reliable Django web applications.'
        self.fact.save(update_fields=['statement', 'updated_at'])
        JobRequirement.objects.all().delete()
        for name in ('Python', 'API'):
            JobRequirement.objects.create(
                owner=self.user,
                job=self.job,
                kind='required',
                category='skill',
                text=name,
                normalized_value=name.lower(),
                is_hard=True,
            )

        match = recompute_match(self.job)

        self.assertIn('python', match.explanation_json['covered_skills'])
        self.assertIn('api', match.missing_requirements)
        self.assertEqual(match.explanation_json['inferred_capabilities'], [{
            'capability': 'python',
            'basis': 'Django/DRF/Flask/FastAPI/Celery experience is Python-framework evidence.',
            'credit': 'partial',
        }])
        supporting = next(item for item in match.supporting_facts if item['fact_id'] == self.fact.id)
        self.assertEqual(supporting['inferred_skills'], ['python'])

    def test_candidate_source_of_truth_overrides_older_imported_facts(self):
        ProfileFact.objects.create(
            owner=self.user,
            fact_type='skill',
            title='Current LinkedIn skill',
            statement='Current LinkedIn skill is the candidate-designated source of truth.',
            metadata={'source_of_truth': True, 'source': 'linkedin'},
            verified_by_user=True,
            lifecycle='verified',
        )

        facts = list(authoritative_facts(self.user))

        self.assertEqual([fact.title for fact in facts], ['Current LinkedIn skill'])

    def test_verified_resume_skill_still_counts_when_linkedin_is_source_of_truth(self):
        self.fact.statement = 'Led reliable Django platform delivery.'
        self.fact.metadata = {'source_of_truth': True, 'source': 'linkedin'}
        self.fact.save(update_fields=['statement', 'metadata', 'updated_at'])
        ProfileFact.objects.create(
            owner=self.user,
            fact_type='skill',
            title='Python and Django application development',
            statement='Python and Django application development, testing, and upgrades.',
            verified_by_user=True,
            lifecycle='verified',
            metadata={'source': 'resume'},
        )

        match = recompute_match(self.job)

        self.assertIn('python', match.explanation_json['covered_skills'])
        self.assertNotIn('python', match.missing_requirements)

    @patch('core.ai._openai_available', return_value=True)
    @patch('core.ai.openai_client')
    def test_openai_embedding_uses_configured_model_and_fixed_dimensions(self, client_factory, _available):
        client = Mock()
        client.embeddings.create.return_value = SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.25] * 3072)],
        )
        client_factory.return_value = client

        result = embed_text_result('Staff platform engineering')

        self.assertEqual(result.provider, 'openai')
        self.assertEqual(result.model, 'text-embedding-3-large')
        self.assertEqual(len(result.vector), 3072)
        client.embeddings.create.assert_called_once_with(
            model='text-embedding-3-large',
            input='Staff platform engineering',
            dimensions=3072,
        )
