from unittest.mock import patch
from types import SimpleNamespace
from django.test import TestCase, SimpleTestCase, override_settings
from django.contrib.auth import get_user_model
from core.ai import extract_job
from core.domain.job_skills import ensure_job_skills
from core.domain.sourcing import persist_job_structure
from core.domain.matching import recompute_match
from core.models import JobPosting, CandidateProfile

class JobSkillInferenceTests(SimpleTestCase):
    @patch('core.ai.generate_json')
    def test_llm_infers_from_duties_when_extraction_has_no_skills(self, generate):
        generate.side_effect = [SimpleNamespace(data={'title':'Visitor host','required_skills':[], 'preferred_skills':[]}, source='openai'), SimpleNamespace(data={'skills':['Visitor assistance', 'Queue coordination', 'Issue resolution']})]
        result = extract_job('Welcome arriving visitors, organize the queue and resolve requests.')
        self.assertEqual(result.data['required_skills'], result.data['inferred_skills'])
        self.assertIn('Visitor assistance', result.data['required_skills'])
        self.assertEqual(result.data['skill_inference_source'], 'ai')

    @patch('core.ai.generate_json', return_value=None)
    def test_offline_nontechnical_posting_still_has_inferred_capabilities(self, generate):
        result = extract_job('Brand director\nPlan campaigns and guide the marketing team.')
        self.assertTrue(result.data['required_skills'])
        self.assertEqual(result.data['inferred_skills'], result.data['required_skills'])

    @patch('core.ai.generate_json')
    def test_explicit_capabilities_remain_distinct(self, generate):
        result = ensure_job_skills({'required_skills':['Brand strategy'],'preferred_skills':['Budget management']}, 'Description')
        self.assertEqual(result['inferred_skills'], [])
        generate.assert_not_called()

@override_settings(OPENAI_API_KEY='')
class JobSkillsPersistenceTests(TestCase):
    def test_old_empty_structure_is_repaired_without_duplicate_version(self):
        user = get_user_model().objects.create_user(username='skill-repair')
        CandidateProfile.objects.create(owner=user)
        job = JobPosting.objects.create(owner=user,title='Marketing manager',description_text='Plan campaigns and lead a team.',content_hash='skill-repair')
        with patch('core.ai.generate_json', return_value=None):
            persist_job_structure(job)
            self.assertTrue(job.requirements.filter(category='skill').exists())
            job.requirements.all().delete()
            persist_job_structure(job)
            self.assertEqual(job.versions.count(),1)
            self.assertTrue(job.requirements.filter(metadata__inferred=True).exists())
            match = recompute_match(job)
        signal = match.signals.get(kind='skills')
        self.assertNotIn('0 of 0 required and 0 of 0', signal.explanation)
        self.assertIn('inferred from duties', signal.explanation)
