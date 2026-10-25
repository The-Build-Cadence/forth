from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from core.domain.application_journey import document_status
from core.models import Application, ApplicationEvent, CoverLetter, JobPosting, ProfileFact, Resume


@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class ApplicationJourneyTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='journey')
        self.job = JobPosting.objects.create(owner=self.owner, title='Engineer', content_hash='journey')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_saving_is_idempotent_and_does_not_prepare_or_submit(self):
        first = self.api.post(f'/api/jobs/{self.job.id}/create_application/')
        second = self.api.post(f'/api/jobs/{self.job.id}/create_application/')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(Application.objects.count(), 1)
        self.assertEqual(ApplicationEvent.objects.count(), 1)
        self.assertEqual(first.data['status'], 'saved')
        self.assertIsNone(first.data['applied_at'])
        self.assertFalse(Resume.objects.exists())
        self.assertEqual(first.data['job_detail']['document_status'], 'not_created')

    @patch('core.views.regenerate_application_materials_task.delay')
    def test_preparation_is_visible_before_worker_starts(self, delay):
        delay.return_value.id = 'queued'
        ProfileFact.objects.create(owner=self.owner, title='Python')
        response = self.api.post(f'/api/jobs/{self.job.id}/regenerate_materials/')
        self.assertEqual(response.status_code, 202)
        application = Application.objects.get(owner=self.owner, job=self.job)
        self.assertEqual(application.status, 'preparing')
        self.assertIsNone(application.applied_at)
        self.job.refresh_from_db()
        self.assertEqual(document_status(self.job), 'generating')
        self.api.post(f'/api/jobs/{self.job.id}/regenerate_materials/')
        self.assertEqual(delay.call_count, 1)

    @patch('core.views.regenerate_application_materials_task.delay')
    def test_new_documents_do_not_rewind_submitted_application(self, delay):
        delay.return_value.id = 'queued'
        ProfileFact.objects.create(owner=self.owner, title='Python')
        applied_at = timezone.now() - timedelta(days=2)
        application = Application.objects.create(owner=self.owner, job=self.job, status='technical_screen', applied_at=applied_at)
        self.api.post(f'/api/jobs/{self.job.id}/regenerate_materials/')
        application.refresh_from_db()
        self.assertEqual(application.status, 'technical_screen')
        self.assertEqual(application.applied_at, applied_at)

    def test_review_requires_both_current_documents(self):
        resume = Resume.objects.create(owner=self.owner, target_job=self.job, kind='tailored', title='Draft', content_markdown='Resume')
        letter = CoverLetter.objects.create(owner=self.owner, target_job=self.job, title='Letter', content_markdown='Letter')
        self.assertEqual(document_status(self.job), 'needs_review')
        resume.approved = True
        resume.save()
        self.assertEqual(document_status(self.job), 'needs_review')
        letter.approved = True
        letter.save()
        self.assertEqual(document_status(self.job), 'reviewed')
        latest = Resume.objects.create(owner=self.owner, target_job=self.job, kind='tailored', title='New draft', content_markdown='New')
        resume.save()
        self.assertEqual(document_status(self.job), 'needs_review')
        response = self.api.get('/api/resumes/', {'job': self.job.id, 'kind': 'tailored'})
        self.assertEqual(response.data['results'][0]['id'], latest.id)

    def test_failed_and_stale_generation_can_be_retried(self):
        self.job.materials_status = 'failed'
        self.assertEqual(document_status(self.job), 'failed')
        self.job.materials_status = 'running'
        self.job.materials_started_at = timezone.now() - timedelta(minutes=16)
        self.assertEqual(document_status(self.job), 'failed')

    def test_already_applied_does_not_require_documents(self):
        saved = self.api.post(f'/api/jobs/{self.job.id}/create_application/')
        applied_at = timezone.now() - timedelta(days=3)
        response = self.api.patch(f"/api/applications/{saved.data['id']}/", {'status': 'applied', 'applied_at': applied_at.isoformat()}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['resume'])
        application = Application.objects.get(pk=saved.data['id'])
        self.assertEqual(application.applied_at, applied_at)
        self.assertEqual(application.events.filter(event_type='status_changed').count(), 1)

    def test_other_users_cannot_save_or_prepare_this_job(self):
        other = get_user_model().objects.create_user(username='other-journey')
        self.api.force_authenticate(other)
        for action in ['create_application', 'regenerate_materials']:
            self.assertEqual(self.api.post(f'/api/jobs/{self.job.id}/{action}/').status_code, 404)
        self.assertFalse(Application.objects.exists())
