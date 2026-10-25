from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from core.domain.documents import document_html, prepare_application_materials, render_application_bundle
from core.domain.matching import recompute_match
from core.domain.orchestration import create_concierge_run, decide_approval, execute_agent_run
from core.domain.sourcing import validate_public_url
from core.models import (
    AgentRun,
    Application,
    ApprovalRequest,
    Artifact,
    CandidateProfile,
    ConversationMessage,
    CoverLetter,
    JobPosting,
    JobRequirement,
    JobSource,
    OnboardingResponse,
    ProfileFact,
    Resume,
    SourceRun,
)
from core.tasks import regenerate_application_materials_task


class AgenticWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='agent-user', password='password')
        CandidateProfile.objects.create(
            owner=self.user,
            headline='Senior platform engineer',
            target_roles=['Staff Platform Engineer'],
            location='Toronto, Canada',
            authorized_countries=['Canada'],
            work_modes=['remote', 'hybrid'],
            minimum_compensation=150000,
        )
        ProfileFact.objects.create(
            owner=self.user,
            fact_type='achievement',
            title='Platform reliability',
            statement='Built Python and Django services with Celery and PostgreSQL for reliable platform workflows.',
            confidence='high',
            verified_by_user=True,
            lifecycle='verified',
        )
        self.job = JobPosting.objects.create(
            owner=self.user,
            title='Staff Platform Engineer',
            company='Northstar',
            location='Toronto, Canada',
            remote_policy='hybrid',
            compensation='CAD 170,000–190,000',
            description_text='Build Python Django platform services using PostgreSQL and Celery.',
            content_hash='agentic-job',
            freshness_status='fresh',
        )
        for skill in ['Python', 'Django', 'PostgreSQL', 'Celery']:
            JobRequirement.objects.create(
                owner=self.user, job=self.job, kind='required', category='skill', text=skill,
                normalized_value=skill.lower(), is_hard=True, weight=90,
            )
        Resume.objects.create(
            owner=self.user,
            kind='canonical',
            title='Canonical Resume',
            content_markdown='# Candidate\n\n## Experience\n\n- Built Python and Django services with Celery and PostgreSQL for reliable platform workflows.',
        )

    def test_match_decomposes_fit_and_eligibility(self):
        match = recompute_match(self.job)

        self.assertEqual(match.hard_filter_status, 'pass')
        # Offline embeddings need not clear a production relevance threshold.
        # The score must faithfully combine the six published fit signals.
        self.assertEqual(match.score, round(sum(signal.score * signal.weight for signal in match.signals.all()) / 100))
        self.assertEqual(match.signals.count(), 6)
        self.assertTrue(match.supporting_facts)
        self.assertIn('score_version', match.explanation_json)
        self.assertTrue(match.signals.filter(kind='semantic').exists())
        self.assertEqual(match.explanation_json['score_version'], '2026-10-v6-grounded-inference')

    def test_document_workflow_waits_for_approval_then_prepares_materials(self):
        run = create_concierge_run(self.user, message='Prepare my strongest opportunity')
        execute_agent_run(run)
        run.refresh_from_db()

        self.assertEqual(run.status, 'waiting_approval')
        approval = ApprovalRequest.objects.get(run=run)
        decide_approval(approval, approved=True)

        application = Application.objects.get(owner=self.user, job=self.job)
        self.assertEqual(application.status, 'materials_ready')
        self.assertIsNotNone(application.resume_id)
        self.assertTrue(self.job.cover_letters.exists())
        run.refresh_from_db()
        self.assertEqual(run.status, 'succeeded')

    def test_material_regeneration_creates_fresh_versions_and_updates_application(self):
        first = regenerate_application_materials_task(self.job.id)
        first_resume_id = first['resume_id']

        second = regenerate_application_materials_task(self.job.id)

        application = Application.objects.get(owner=self.user, job=self.job)
        self.assertNotEqual(second['resume_id'], first_resume_id)
        self.assertEqual(application.resume_id, second['resume_id'])
        self.assertEqual(application.status, 'materials_ready')
        self.assertEqual(second['cover_letter_version'], 2)
        self.assertEqual(CoverLetter.objects.filter(owner=self.user, target_job=self.job).count(), 2)
        self.assertEqual(application.events.filter(event_type='materials_regenerated').count(), 2)

    def test_chat_understands_top_role_follow_up_and_keeps_job_context(self):
        recompute_match(self.job)
        thread = None

        recommendation = create_concierge_run(self.user, message='Give me the top one please')
        thread = recommendation.thread
        self.assertEqual(recommendation.agent, 'matching')
        execute_agent_run(recommendation)

        answer = ConversationMessage.objects.filter(thread=thread, role='assistant').latest('created_at')
        self.assertIn('Top recommendation', answer.content)
        self.assertIn(self.job.title, answer.content)
        self.assertEqual(answer.metadata['job_id'], self.job.id)
        self.assertEqual(len(answer.metadata['actions']), 2)

        preparation = create_concierge_run(self.user, message='Prepare it', thread=thread)
        self.assertEqual(preparation.agent, 'documents')
        self.assertEqual(preparation.input['job_id'], self.job.id)
        execute_agent_run(preparation)

        approval = ApprovalRequest.objects.get(run=preparation)
        self.assertEqual(approval.payload['job_id'], self.job.id)

    @override_settings(GOTENBERG_URL='', MEDIA_ROOT='/tmp/job-seeker-test-media')
    def test_rendering_has_recoverable_html_fallback(self):
        application = Application.objects.create(owner=self.user, job=self.job, status='preparing')
        prepare_application_materials(self.user, self.job, application=application)

        artifacts = render_application_bundle(self.user, application=application)

        self.assertEqual(len(artifacts), 2)
        self.assertTrue(all(artifact.kind.endswith('_html') for artifact in artifacts))
        self.assertTrue(all(artifact.file for artifact in artifacts))
        self.assertEqual(Artifact.objects.count(), 2)

    def test_resume_design_is_stored_and_rendered_consistently(self):
        application = Application.objects.create(owner=self.user, job=self.job, status='preparing')
        materials = prepare_application_materials(self.user, self.job, application=application)
        resume = materials['resume']
        design = resume.content_json['design']

        self.assertIn(design['template'], {'modern', 'classic', 'minimal'})
        self.assertIn(design['density'], {'compact', 'balanced', 'spacious'})
        rendered = document_html(resume.title, resume.content_markdown, kind='resume', design=design)
        self.assertIn(f"size: {design['page_size']}", rendered)
        self.assertIn(design['accent'], rendered)
        self.assertIn('<h1>', rendered)


class AgenticApiOwnershipTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username='owner-agentic', password='password')
        self.other = User.objects.create_user(username='other-agentic', password='password')
        self.client.force_authenticate(self.owner)
        self.other_approval = ApprovalRequest.objects.create(
            owner=self.other, kind='verify_fact', title='Other approval', prompt='No access', payload={},
        )

    def test_signup_creates_account_and_returns_an_immediate_session(self):
        self.client.force_authenticate(user=None)
        response = self.client.post('/api/auth/signup/', {
            'email': 'New.Candidate@example.com',
            'password': 'A-strong-career-password-2026',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(response.data['access'])
        self.assertTrue(response.data['refresh'])
        user = get_user_model().objects.get(email='new.candidate@example.com')
        self.assertEqual(user.username, 'new.candidate@example.com')
        self.assertTrue(user.check_password('A-strong-career-password-2026'))

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        onboarding = self.client.get('/api/profile/onboarding/')
        self.assertEqual(onboarding.status_code, status.HTTP_200_OK)
        self.assertTrue(onboarding.data['needs_onboarding'])
        self.assertEqual(onboarding.data['step']['id'], 'welcome')

    def test_signup_rejects_duplicate_email_and_weak_password(self):
        self.client.force_authenticate(user=None)
        get_user_model().objects.create_user(username='taken@example.com', email='taken@example.com', password='Existing-password-2026')

        duplicate = self.client.post('/api/auth/signup/', {'email': 'TAKEN@example.com', 'password': 'Another-password-2026'}, format='json')
        weak = self.client.post('/api/auth/signup/', {'email': 'fresh@example.com', 'password': 'password'}, format='json')

        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', duplicate.data)
        self.assertEqual(weak.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', weak.data)

    def test_candidate_profile_is_owner_scoped_and_created_lazily(self):
        response = self.client.get('/api/profile/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(CandidateProfile.objects.filter(owner=self.owner).exists())

        response = self.client.patch('/api/profile/', {'target_roles': ['Platform Engineer']}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['target_roles'], ['Platform Engineer'])

    @override_settings(OPENAI_API_KEY='')
    def test_profile_editor_cannot_overwrite_newer_agent_answers(self):
        original = self.client.get('/api/profile/').data
        profile = CandidateProfile.objects.get(owner=self.owner)
        profile.professional_summary = 'A newly saved adaptive interview answer with enough detail to remain authoritative.'
        profile.save()

        stale = self.client.patch('/api/profile/', {
            'base_updated_at': original['updated_at'],
            'professional_summary': '',
        }, format='json')

        self.assertEqual(stale.status_code, status.HTTP_409_CONFLICT)
        profile.refresh_from_db()
        self.assertTrue(profile.professional_summary)

    @override_settings(OPENAI_API_KEY='', CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_onboarding_agent_uses_resume_then_adapts_until_profile_is_ready(self):
        response = self.client.get('/api/profile/onboarding/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['step']['id'], 'welcome')

        def answer(step, answers=None):
            result = self.client.post('/api/profile/onboarding/', {'step': step, 'answers': answers or {}}, format='json')
            self.assertEqual(result.status_code, status.HTTP_200_OK, result.data)
            return result

        self.assertEqual(answer('welcome').data['step']['id'], 'source')
        refused_skip = self.client.post('/api/profile/onboarding/', {'step': 'source', 'answers': {'skip': True}}, format='json')
        self.assertEqual(refused_skip.status_code, status.HTTP_400_BAD_REQUEST)

        resume = self.client.post('/api/profile/documents/', {
            'kind': 'resume',
            'title': 'Current resume.html',
            'raw_text': (
                'Senior platform engineer. Built Python and Django services with PostgreSQL and Celery. '
                'Led a reliability program that reduced deployment recovery time by 40 percent.'
            ),
        }, format='json')
        self.assertEqual(resume.status_code, status.HTTP_201_CREATED, resume.data)

        snapshot = self.client.get('/api/profile/onboarding/').data
        self.assertEqual(snapshot['step']['id'], 'interview')
        self.assertIn('overview', snapshot['resume']['analysis'])
        answered_targets = []
        values = {
            'target_roles': ['Staff Platform Engineer', 'Engineering Lead'],
            'headline': 'Product-minded platform engineer',
            'location': 'Toronto, Canada',
            'authorized_countries': ['Canada'],
            'work_modes': ['Remote', 'Hybrid'],
            'employment_types': ['Full-time'],
            'target_industries': ['Developer tools', 'AI infrastructure'],
            'minimum_compensation': '150000',
            'preference_ideal': ['High ownership', 'Calm collaboration'],
            'preference_avoid': ['Always-on culture'],
            'professional_summary': 'Product-minded platform engineer who builds dependable systems and helps teams make clear technical decisions.',
            'experience': 'Staff Platform Engineer at Northstar from 2021 to present, leading platform architecture and reliability across four teams.',
            'education': 'Bachelor of Software Engineering, Example University, 2014.',
            'soft_skills': ['Technical leadership', 'Clear communication'],
            'hobbies': ['Mentoring', 'Open-source work'],
            'skill': ['Python', 'Platform architecture'],
            'achievement': 'Led a reliability program that reduced deployment recovery time by 40 percent across the platform.',
        }
        for _ in range(20):
            if snapshot['step']['id'] == 'review':
                break
            question = snapshot['step']['question']
            target = question['target']
            answered_targets.append(target)
            snapshot = answer('interview', {
                'question_id': question['id'],
                'value': values[target],
            }).data

        self.assertEqual(snapshot['step']['id'], 'review')
        self.assertTrue(snapshot['readiness']['ready'])
        self.assertEqual(snapshot['readiness']['score'], 100)
        self.assertIn('target_roles', answered_targets)
        self.assertIn('authorized_countries', answered_targets)
        self.assertIn('preference_ideal', answered_targets)
        self.assertEqual(len([target for target in answered_targets if target != 'fact_confirmation']), len(set(target for target in answered_targets if target != 'fact_confirmation')))
        self.assertEqual(OnboardingResponse.objects.filter(owner=self.owner).count(), len(answered_targets))

        completed = answer('complete')
        self.assertFalse(completed.data['needs_onboarding'])
        self.assertIsNotNone(completed.data['profile']['onboarding_completed_at'])

    def test_foreign_approval_cannot_be_addressed(self):
        response = self.client.post(f'/api/approvals/{self.other_approval.id}/decide/', {'approved': True}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_concierge_creates_message_and_run(self):
        response = self.client.post('/api/conversations/', {'title': 'Concierge', 'status': 'active', 'context': {}}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        thread_id = response.data['id']

        with self.settings(CELERY_TASK_ALWAYS_EAGER=True):
            response = self.client.post(f'/api/conversations/{thread_id}/send/', {'content': 'What should I focus on today?'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertTrue(ConversationMessage.objects.filter(owner=self.owner, thread_id=thread_id, role='user').exists())

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_profile_source_is_ingested_and_becomes_canonical_resume(self):
        response = self.client.post('/api/profile/documents/', {
            'kind': 'resume',
            'title': 'Integration resume',
            'raw_text': 'Senior Python engineer who built Django APIs with PostgreSQL and Celery.',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        from core.models import ProfileDocument

        document = ProfileDocument.objects.get(owner=self.owner, pk=response.data['id'])
        self.assertEqual(document.status, 'ready')
        self.assertTrue(ProfileFact.objects.filter(owner=self.owner, source_document=document).exists())
        self.assertTrue(Resume.objects.filter(owner=self.owner, kind='canonical').exists())

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_brave_source_run_reaches_a_terminal_success_state(self):
        source = JobSource.objects.create(owner=self.owner, name='Brave QA', kind='brave', config={'demo': True})

        response = self.client.post(f'/api/sources/{source.id}/run/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        run = SourceRun.objects.get(owner=self.owner, source=source)
        source.refresh_from_db()
        self.assertEqual(run.status, 'succeeded')
        self.assertEqual(source.last_status, 'succeeded')

    def test_application_can_be_marked_applied_with_an_unapproved_resume(self):
        job = JobPosting.objects.create(
            owner=self.owner, title='QA Engineer', description_text='Python Django', content_hash='qa-guard',
        )
        resume = Resume.objects.create(owner=self.owner, title='Draft', kind='tailored', target_job=job)
        application = Application.objects.create(owner=self.owner, job=job, resume=resume, status='materials_ready')

        allowed = self.client.patch(f'/api/applications/{application.id}/', {'status': 'applied'}, format='json')
        self.assertEqual(allowed.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(allowed.data['applied_at'])
        resume.refresh_from_db()
        self.assertFalse(resume.approved)

    def test_rejecting_a_material_approval_cancels_without_side_effects(self):
        job = JobPosting.objects.create(
            owner=self.owner, title='Do Not Prepare', description_text='Python', content_hash='qa-reject',
        )
        run = AgentRun.objects.create(owner=self.owner, agent='documents', objective='Prepare', status='waiting_approval')
        approval = ApprovalRequest.objects.create(
            owner=self.owner, run=run, kind='prepare_application', title='Prepare', prompt='Proceed?', payload={'job_id': job.id},
        )

        response = self.client.post(f'/api/approvals/{approval.id}/decide/', {'approved': False}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        run.refresh_from_db()
        self.assertEqual(run.status, 'cancelled')
        self.assertFalse(Application.objects.filter(owner=self.owner, job=job).exists())


class SourceSafetyTests(SimpleTestCase):
    def test_private_source_addresses_are_rejected(self):
        from unittest.mock import patch

        with patch('core.domain.sourcing.socket.getaddrinfo', return_value=[(None, None, None, None, ('127.0.0.1', 80))]):
            with self.assertRaisesMessage(ValueError, 'public network address'):
                validate_public_url('http://localhost/jobs.xml')
