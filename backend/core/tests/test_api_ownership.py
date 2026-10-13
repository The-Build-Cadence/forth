from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import override_settings
from django.utils import timezone
from types import SimpleNamespace
from unittest.mock import patch
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Application, Artifact, JobPosting, JobSource, ProfileDocument, ProfileFact, Resume


class OwnedRelationApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username='owner', password='password')
        self.other = User.objects.create_user(username='other', password='password')
        self.client.force_authenticate(self.owner)

        self.owner_source = JobSource.objects.create(owner=self.owner, name='Owner source', kind='manual')
        self.other_source = JobSource.objects.create(owner=self.other, name='Other source', kind='manual')
        self.owner_job = JobPosting.objects.create(
            owner=self.owner,
            source=self.owner_source,
            title='Owner job',
            description_text='Python role',
            content_hash='owner-job',
            application_url='https://jobs.example.com/owner/apply',
        )
        self.other_job = JobPosting.objects.create(
            owner=self.other,
            source=self.other_source,
            title='Other job',
            description_text='Go role',
            content_hash='other-job',
        )
        self.owner_resume = Resume.objects.create(
            owner=self.owner,
            kind='canonical',
            title='Owner resume',
            content_markdown='# Owner',
        )
        self.other_resume = Resume.objects.create(
            owner=self.other,
            kind='canonical',
            title='Other resume',
            content_markdown='# Other',
        )
        self.owner_application = Application.objects.create(
            owner=self.owner,
            job=self.owner_job,
            resume=self.owner_resume,
        )
        self.other_application = Application.objects.create(
            owner=self.other,
            job=self.other_job,
            resume=self.other_resume,
        )

    def assert_field_rejected(self, response, field):
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn(field, response.data)

    def test_job_cannot_reference_another_owners_source(self):
        response = self.client.post('/api/jobs/', {
            'source': self.other_source.id,
            'title': 'Cross-owner job',
            'description_text': 'Python API role',
        }, format='json')
        self.assert_field_rejected(response, 'source')

    def test_resume_cannot_reference_another_owners_job_or_parent(self):
        response = self.client.post('/api/resumes/', {
            'kind': 'tailored',
            'title': 'Cross-owner resume',
            'content_markdown': '# Test',
            'parent_resume': self.other_resume.id,
            'target_job': self.other_job.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('parent_resume', response.data)
        self.assertIn('target_job', response.data)

    def test_application_cannot_reference_another_owners_job_or_resume(self):
        response = self.client.post('/api/applications/', {
            'job': self.other_job.id,
            'resume': self.other_resume.id,
            'status': 'saved',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('job', response.data)
        self.assertIn('resume', response.data)

        response = self.client.patch(
            f'/api/applications/{self.owner_application.id}/',
            {'resume': self.other_resume.id},
            format='json',
        )
        self.assert_field_rejected(response, 'resume')

    @patch('core.views.regenerate_application_materials_task.delay')
    def test_material_regeneration_is_queued_for_owned_job(self, delay):
        delay.return_value = SimpleNamespace(id='materials-task')

        response = self.client.post(f'/api/jobs/{self.owner_job.id}/regenerate_materials/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data['task_id'], 'materials-task')
        delay.assert_called_once_with(self.owner_job.id)

    @patch('core.views.regenerate_application_materials_task.delay')
    def test_material_regeneration_cannot_target_another_owners_job(self, delay):
        response = self.client.post(f'/api/jobs/{self.other_job.id}/regenerate_materials/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        delay.assert_not_called()

    def test_event_cannot_reference_another_owners_application(self):
        response = self.client.post('/api/application-events/', {
            'application': self.other_application.id,
            'event_type': 'note',
            'happened_at': timezone.now().isoformat(),
            'notes': 'Cross-owner note',
        }, format='json')
        self.assert_field_rejected(response, 'application')

    def test_artifact_cannot_reference_another_owners_records(self):
        response = self.client.post('/api/artifacts/', {
            'application': self.other_application.id,
            'resume': self.other_resume.id,
            'kind': 'note',
            'title': 'Cross-owner artifact',
            'content_text': 'Should not be accepted',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('application', response.data)
        self.assertIn('resume', response.data)

    def test_owner_relations_remain_writable(self):
        response = self.client.post('/api/applications/', {
            'job': self.owner_job.id,
            'resume': self.owner_resume.id,
            'status': 'saved',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        response = self.client.post('/api/artifacts/', {
            'application': response.data['id'],
            'resume': self.owner_resume.id,
            'kind': 'note',
            'title': 'Owner artifact',
            'content_text': 'Allowed',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_application_form_url_defaults_from_job_and_is_editable(self):
        self.assertEqual(self.owner_application.application_form_url, self.owner_job.application_url)

        response = self.client.patch(
            f'/api/applications/{self.owner_application.id}/',
            {'application_form_url': 'https://ats.example.com/forms/owner-job'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['application_form_url'], 'https://ats.example.com/forms/owner-job')

        listing = self.client.get('/api/applications/')
        self.assertEqual(listing.status_code, status.HTTP_200_OK, listing.data)
        record = next(item for item in listing.data['results'] if item['id'] == self.owner_application.id)
        self.assertEqual(record['application_form_url'], 'https://ats.example.com/forms/owner-job')

    def test_foreign_objects_are_not_addressable(self):
        paths = [
            f'/api/sources/{self.other_source.id}/',
            f'/api/jobs/{self.other_job.id}/',
            f'/api/resumes/{self.other_resume.id}/',
            f'/api/applications/{self.other_application.id}/',
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(MEDIA_ROOT='/tmp/job-seeker-private-artifact-tests')
    def test_artifact_download_requires_ownership(self):
        owner_artifact = Artifact.objects.create(
            owner=self.owner,
            application=self.owner_application,
            resume=self.owner_resume,
            kind='resume_pdf',
            title='Owner artifact',
            mime_type='application/pdf',
        )
        owner_artifact.file.save('owner.pdf', ContentFile(b'%PDF-1.4 owner'), save=True)
        artifact = Artifact.objects.create(
            owner=self.other,
            application=self.other_application,
            resume=self.other_resume,
            kind='resume_pdf',
            title='Private artifact',
            mime_type='application/pdf',
        )
        artifact.file.save('private.pdf', ContentFile(b'%PDF-1.4 private'), save=True)

        allowed = self.client.get(f'/api/artifacts/{owner_artifact.id}/download/')
        detail = self.client.get(f'/api/artifacts/{owner_artifact.id}/')
        response = self.client.get(f'/api/artifacts/{artifact.id}/download/')

        self.assertEqual(allowed.status_code, status.HTTP_200_OK)
        self.assertEqual(allowed['Content-Type'], 'application/pdf')
        self.assertNotIn('file', detail.data)
        self.assertTrue(detail.data['file_url'].endswith(f'/api/artifacts/{owner_artifact.id}/download/'))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ProfileFactApiTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username='fact-owner', password='password')
        self.other = User.objects.create_user(username='fact-other', password='password')
        self.client.force_authenticate(self.owner)
        self.owner_document = ProfileDocument.objects.create(
            owner=self.owner,
            kind='note',
            title='Owner document',
            raw_text='Owner profile text',
        )
        self.other_document = ProfileDocument.objects.create(
            owner=self.other,
            kind='note',
            title='Other document',
            raw_text='Other profile text',
        )
        self.fact = ProfileFact.objects.create(
            owner=self.owner,
            fact_type='skill',
            title='Python',
            statement='Builds Python services.',
            source_document=self.owner_document,
        )

    def test_source_provenance_cannot_be_reassigned(self):
        response = self.client.patch(f'/api/profile/facts/{self.fact.id}/', {
            'title': 'Advanced Python',
            'source_document': self.other_document.id,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.fact.refresh_from_db()
        self.assertEqual(self.fact.title, 'Advanced Python')
        self.assertEqual(self.fact.source_document_id, self.owner_document.id)
