from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APITestCase

from core.models import CandidateProfile, JobSource, ProfileDocument, ProfileFact, SourceRun


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class QuickStartTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username='start@example.com', email='start@example.com', password='My-existing-password-123')
        self.other = get_user_model().objects.create_user(username='other')
        self.client.force_authenticate(self.user)
        self.payload = {'intent': 'discover', 'target_roles': ['Platform Engineer'], 'location': 'Toronto, Canada', 'work_modes': ['remote'], 'authorized_countries': [], 'daily': False}

    def test_minimal_setup_without_resume_does_not_verify_claims(self):
        fact = ProfileFact.objects.create(owner=self.user, title='Uncertain claim', statement='May have led a team', metadata={'onboarding_ambiguous': True})
        response = self.client.post('/api/start/', self.payload, format='json')
        self.assertEqual(response.status_code, 200)
        profile = CandidateProfile.objects.get(owner=self.user)
        self.assertIsNotNone(profile.onboarding_completed_at)
        self.assertEqual(profile.target_roles, ['Platform Engineer'])
        fact.refresh_from_db()
        self.assertFalse(fact.verified_by_user)
        self.assertEqual(self.client.get('/api/today/').data['next_action']['label'], 'Find jobs for me')

    @override_settings(FORTH_BETA_INVITE_CODE='invite-for-tests')
    def test_invitation_is_enforced_without_exposing_code(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/access/').data, {'invitation_required': True})
        payload = {'email': 'invited@example.com', 'password': 'Long-test-password-237'}
        self.assertEqual(self.client.post('/api/auth/signup/', payload).status_code, 400)
        self.assertEqual(self.client.post('/api/auth/signup/', {**payload, 'invite_code': 'invite-for-tests'}).status_code, 201)

    def test_quick_setup_keeps_detailed_review_available(self):
        self.client.post('/api/start/', self.payload, format='json')
        from core.domain.profiles import onboarding_snapshot
        snapshot = onboarding_snapshot(self.user)
        self.assertTrue(snapshot['needs_onboarding'])
        self.assertEqual(snapshot['step']['id'], 'welcome')

    @patch('core.domain.sourcing._verify_job_page', return_value=('page_unverified', 'Blocked'))
    def test_unreadable_job_url_returns_actionable_error(self, verify):
        response = self.client.post('/api/jobs/import_job/', {'source_url': 'https://example.com/jobs/123'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Paste the full job description', response.data['detail'])

    def test_incomplete_draft_resumes_without_activating_search(self):
        draft = {'intent': 'apply', 'step': 3, 'roles': 'Platform Engineer', 'location': '', 'countries': '', 'work_modes': [], 'daily': False}
        self.assertEqual(self.client.patch('/api/start/', draft, format='json').status_code, 200)
        profile = self.client.get('/api/start/').data['profile']
        self.assertIsNone(profile['onboarding_completed_at'])
        self.assertEqual(profile['onboarding_state']['setup_draft'], draft)
        self.client.post('/api/start/', self.payload, format='json')
        self.assertNotIn('setup_draft', self.client.get('/api/start/').data['profile']['onboarding_state'])

    def test_public_assets_are_not_api_rate_limited(self):
        from pathlib import Path
        self.client.force_authenticate(None)
        with TemporaryDirectory() as directory, override_settings(BASE_DIR=Path(directory)):
            root = Path(directory) / 'staticfiles'
            root.mkdir()
            (root / 'styles.css').write_text('body { color: black; }')
            for _ in range(65):
                response = self.client.get('/styles.css')
                self.assertEqual(response.status_code, 200)
                self.assertIn('text/css', response['Content-Type'])
                list(response.streaming_content)

    def test_application_preparation_requires_actual_experience(self):
        from core.models import JobPosting
        job = JobPosting.objects.create(owner=self.user, title='Engineer', content_hash='empty-experience-test')
        with patch('core.views.regenerate_application_materials_task.delay') as delay:
            response = self.client.post(f'/api/jobs/{job.pk}/regenerate_materials/')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'experience_required')
        delay.assert_not_called()

    def test_invalid_preferences_cannot_complete_setup(self):
        for changes in [{'target_roles': []}, {'work_modes': ['anything']}, {'location': ''}, {'intent': 'other'}, {'daily': 'invalid'}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.client.post('/api/start/', {**self.payload, **changes}, format='json').status_code, 400)

    def test_snapshot_is_scoped_to_owner(self):
        ProfileDocument.objects.create(owner=self.other, title='Private resume', kind='resume')
        self.assertIsNone(self.client.get('/api/start/').data['document'])
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/start/').status_code, 401)

    @override_settings(BRAVE_SEARCH_API_KEY='test')
    @patch('core.start_views.execute_source_run_task.delay')
    def test_discovery_retries_reuse_active_run_and_do_not_enable_schedule(self, delay):
        self.client.post('/api/start/', self.payload, format='json')
        first = self.client.post('/api/start/discover/')
        second = self.client.post('/api/start/discover/')
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(SourceRun.objects.filter(owner=self.user).count(), 1)
        self.assertFalse(JobSource.objects.get(owner=self.user).enabled)
        delay.assert_called_once()

    @override_settings(BRAVE_SEARCH_API_KEY='')
    def test_unavailable_discovery_preserves_setup(self):
        self.client.post('/api/start/', self.payload, format='json')
        self.assertEqual(self.client.post('/api/start/discover/').status_code, 503)
        self.assertFalse(SourceRun.objects.exists())
        self.assertTrue(self.client.get('/api/start/').data['profile']['onboarding_completed_at'])

    @override_settings(BRAVE_SEARCH_API_KEY='test')
    @patch('core.start_views.execute_source_run_task.delay', side_effect=RuntimeError('broker offline'))
    def test_queue_failure_is_recoverable(self, delay):
        self.client.post('/api/start/', self.payload, format='json')
        self.assertEqual(self.client.post('/api/start/discover/').status_code, 503)
        self.assertEqual(SourceRun.objects.get(owner=self.user).status, 'failed')

    def test_account_deletion_requires_password_and_only_deletes_own_files(self):
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            doc = ProfileDocument.objects.create(owner=self.user, title='Resume', upload=ContentFile(b'private', name='resume.txt'))
            other = ProfileDocument.objects.create(owner=self.other, title='Other', upload=ContentFile(b'other', name='other.txt'))
            self.assertEqual(self.client.post('/api/account/delete/', {'password': 'wrong', 'confirmation': 'DELETE'}).status_code, 400)
            with self.captureOnCommitCallbacks(execute=True):
                result = self.client.post('/api/account/delete/', {'password': 'My-existing-password-123', 'confirmation': 'DELETE'})
            self.assertEqual(result.status_code, 204)
            self.assertFalse(doc.upload.storage.exists(doc.upload.name))
            self.assertTrue(other.upload.storage.exists(other.upload.name))
            self.assertTrue(get_user_model().objects.filter(pk=self.other.pk).exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', FORTH_PUBLIC_URL='https://forth.example')
    def test_recovery_hides_account_existence_and_reset_is_single_use(self):
        self.client.force_authenticate(None)
        existing = self.client.post('/api/auth/recovery/', {'email': self.user.email})
        unknown = self.client.post('/api/auth/recovery/', {'email': 'unknown@example.com'})
        self.assertEqual(existing.data, unknown.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('https://forth.example/reset-password?', mail.outbox[0].body)
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(self.user)
        old_token = str(refresh.access_token)
        old_refresh = str(refresh)
        payload = {'uid': urlsafe_base64_encode(force_bytes(self.user.pk)), 'token': default_token_generator.make_token(self.user), 'password': 'Replacement-password-123', 'confirmation': 'Replacement-password-123'}
        self.assertEqual(self.client.post('/api/auth/reset/', payload).status_code, 200)
        self.assertEqual(self.client.post('/api/auth/reset/', payload).status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(payload['password']))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {old_token}')
        self.assertEqual(self.client.get('/api/start/').status_code, 401)
        self.assertEqual(self.client.post('/api/auth/refresh/', {'refresh': old_refresh}).status_code, 401)
