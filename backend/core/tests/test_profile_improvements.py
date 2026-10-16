from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from core.domain.matching import recompute_match
from core.models import (
    CandidateProfile,
    JobPosting,
    JobRequirement,
    ProfileFact,
    ProfileImprovementProposal,
)


@override_settings(OPENAI_API_KEY='')
class ProfileImprovementApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='improvements', password='password')
        CandidateProfile.objects.create(
            owner=self.user,
            headline='Platform engineer',
            target_roles=['Staff Platform Engineer'],
            work_modes=['remote'],
        )
        self.fact = ProfileFact.objects.create(
            owner=self.user,
            fact_type='achievement',
            title='Platform delivery',
            statement='Led platform delivery using Python and Django for reliable services.',
            evidence_quote='Led platform delivery using Python and Django for reliable services.',
            confidence='high',
            verified_by_user=True,
            lifecycle='verified',
        )
        self.job = JobPosting.objects.create(
            owner=self.user,
            title='Staff Platform Engineer',
            company='Northstar',
            remote_policy='remote',
            description_text='Lead reliable Python and Django platform services.',
            content_hash='profile-improvement-job',
        )
        JobRequirement.objects.create(
            owner=self.user,
            job=self.job,
            kind='required',
            category='skill',
            text='Python and Django platform engineering',
            normalized_value='python django platform engineering',
            is_hard=True,
        )
        recompute_match(self.job)
        self.client.force_authenticate(self.user)

    @patch('core.domain.profile_improvements.generate_json')
    def test_proposes_reviewable_grounded_rewording(self, generate_json):
        generate_json.return_value = SimpleNamespace(data={'suggestions': [{
            'fact_id': self.fact.id,
            'proposed_statement': 'Led reliable Python and Django platform-service delivery.',
            'rationale': 'Makes the relevant platform capabilities explicit earlier.',
            'target_requirements': ['Python', 'Django', 'platform engineering'],
        }]})

        response = self.client.post(f'/api/jobs/{self.job.id}/profile_improvements/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'pending')
        self.assertEqual(len(response.data['suggestions']), 1)
        suggestion = response.data['suggestions'][0]
        self.assertEqual(suggestion['current_statement'], self.fact.statement)
        self.assertEqual(suggestion['fact_id'], self.fact.id)

    @patch('core.views.refresh_profile_search_task.delay')
    @patch('core.domain.profile_improvements.generate_json')
    def test_accepting_selected_changes_preserves_history_and_queues_global_rescore(self, generate_json, delay):
        delay.return_value = SimpleNamespace(id='rescore-task')
        proposed = 'Led reliable Python and Django platform-service delivery.'
        generate_json.return_value = SimpleNamespace(data={'suggestions': [{
            'fact_id': self.fact.id,
            'proposed_statement': proposed,
            'rationale': 'Leads with relevant evidence.',
            'target_requirements': ['Python', 'Django'],
        }]})
        proposal_response = self.client.post(f'/api/jobs/{self.job.id}/profile_improvements/', {}, format='json')
        proposal_id = proposal_response.data['id']
        suggestion_id = proposal_response.data['suggestions'][0]['id']

        response = self.client.post(
            f'/api/jobs/{self.job.id}/apply_profile_improvements/',
            {'proposal_id': proposal_id, 'accepted_suggestion_ids': [suggestion_id]},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['rescore_mode'], 'async')
        self.fact.refresh_from_db()
        self.assertEqual(self.fact.statement, proposed)
        self.assertEqual(self.fact.metadata['wording_history'][-1]['previous_statement'], 'Led platform delivery using Python and Django for reliable services.')
        self.assertEqual(ProfileImprovementProposal.objects.get(pk=proposal_id).status, 'applied')
        delay.assert_called_once_with(self.user.id)

    @patch('core.domain.profile_improvements.generate_json')
    def test_rejecting_all_leaves_profile_unchanged(self, generate_json):
        generate_json.return_value = SimpleNamespace(data={'suggestions': [{
            'fact_id': self.fact.id,
            'proposed_statement': 'Led reliable Python and Django platform-service delivery.',
            'rationale': 'Leads with relevant evidence.',
            'target_requirements': ['Python'],
        }]})
        proposal_response = self.client.post(f'/api/jobs/{self.job.id}/profile_improvements/', {}, format='json')

        response = self.client.post(
            f'/api/jobs/{self.job.id}/apply_profile_improvements/',
            {'proposal_id': proposal_response.data['id'], 'accepted_suggestion_ids': []},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['rescore_mode'], 'not_needed')
        self.fact.refresh_from_db()
        self.assertEqual(self.fact.statement, 'Led platform delivery using Python and Django for reliable services.')
        self.assertEqual(ProfileImprovementProposal.objects.get(pk=proposal_response.data['id']).status, 'rejected')

    @patch('core.domain.profile_improvements.generate_json')
    def test_rejects_ai_wording_that_introduces_an_unsupported_metric(self, generate_json):
        generate_json.return_value = SimpleNamespace(data={'suggestions': [{
            'fact_id': self.fact.id,
            'proposed_statement': 'Improved platform reliability by 40% using Python and Django.',
            'rationale': 'Adds impact.',
            'target_requirements': ['Python'],
        }]})

        response = self.client.post(f'/api/jobs/{self.job.id}/profile_improvements/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['suggestions'], [])

    @patch('core.domain.profile_improvements.generate_json')
    def test_allows_python_clarification_from_django_but_rejects_unproven_api_claim(self, generate_json):
        self.fact.statement = 'Led Django platform delivery for reliable services.'
        self.fact.evidence_quote = self.fact.statement
        self.fact.save(update_fields=['statement', 'evidence_quote', 'updated_at'])
        generate_json.return_value = SimpleNamespace(data={'suggestions': [
            {
                'fact_id': self.fact.id,
                'proposed_statement': 'Led Python and Django platform delivery for reliable services.',
                'rationale': 'Clarifies the language of the Django framework.',
                'target_requirements': ['Python'],
            },
            {
                'fact_id': self.fact.id,
                'proposed_statement': 'Led Django REST APIs for reliable services.',
                'rationale': 'Makes API experience explicit.',
                'target_requirements': ['API'],
            },
        ]})

        response = self.client.post(f'/api/jobs/{self.job.id}/profile_improvements/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data['suggestions']), 1)
        self.assertIn('Python and Django', response.data['suggestions'][0]['proposed_statement'])

    @patch('core.views.refresh_profile_search_task.delay')
    @patch('core.domain.profile_improvements.generate_json', return_value=None)
    def test_confirmed_gap_is_reviewed_then_persisted_as_user_evidence(self, generate_json, delay):
        delay.return_value = SimpleNamespace(id='rescore')
        match = self.job.match
        match.missing_requirements = ['REST APIs']
        match.supporting_facts = [{'fact_id': self.fact.id, 'title': self.fact.title, 'statement': self.fact.statement}]
        match.save()
        original = self.fact.statement
        response = self.client.post(f'/api/jobs/{self.job.id}/profile_improvements/', {
            'gap_links': [{'fact_id': self.fact.id, 'gap': 'REST APIs'}],
        }, format='json')
        self.assertEqual(response.status_code, 201)
        suggestion = response.data['suggestions'][0]
        self.assertIn('REST APIs', suggestion['proposed_statement'])
        self.fact.refresh_from_db()
        self.assertEqual(self.fact.statement, original)
        self.assertNotIn('REST APIs', self.fact.evidence_quote)
        applied = self.client.post(f'/api/jobs/{self.job.id}/apply_profile_improvements/', {
            'proposal_id': response.data['id'], 'accepted_suggestion_ids': [suggestion['id']],
        }, format='json')
        self.assertEqual(applied.status_code, 200)
        self.fact.refresh_from_db()
        self.assertIn('REST APIs', self.fact.statement)
        self.assertIn('User-confirmed experience: REST APIs', self.fact.evidence_quote)
        self.assertEqual(self.fact.metadata['wording_history'][-1]['confirmed_gaps'], ['REST APIs'])

    @patch('core.domain.profile_improvements.generate_json')
    def test_rejects_invalid_stale_and_foreign_gap_links_before_generation(self, generate_json):
        other = get_user_model().objects.create_user(username='other-gap-user')
        foreign = ProfileFact.objects.create(owner=other, title='Other evidence', statement='Private', verified_by_user=True)
        match = self.job.match
        match.missing_requirements = ['REST APIs']
        match.supporting_facts = [{'fact_id': self.fact.id}, {'fact_id': foreign.id}]
        match.save()
        for links in ['bad', [None], [{'fact_id': self.fact.id, 'gap': 'Invented gap'}], [{'fact_id': foreign.id, 'gap': 'REST APIs'}]]:
            response = self.client.post(f'/api/jobs/{self.job.id}/profile_improvements/', {'gap_links': links}, format='json')
            self.assertEqual(response.status_code, 400)
        generate_json.assert_not_called()

    @patch('core.domain.profile_improvements.generate_json', return_value=None)
    def test_rejecting_linked_gap_does_not_record_experience(self, generate_json):
        match = self.job.match
        match.missing_requirements = ['REST APIs']
        match.supporting_facts = [{'fact_id': self.fact.id}]
        match.save()
        response = self.client.post(f'/api/jobs/{self.job.id}/profile_improvements/', {
            'gap_links': [{'fact_id': self.fact.id, 'gap': 'REST APIs'}],
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.client.post(f'/api/jobs/{self.job.id}/apply_profile_improvements/', {
            'proposal_id': response.data['id'], 'accepted_suggestion_ids': [],
        }, format='json')
        self.fact.refresh_from_db()
        self.assertNotIn('REST APIs', self.fact.statement)
        self.assertNotIn('REST APIs', self.fact.evidence_quote)
