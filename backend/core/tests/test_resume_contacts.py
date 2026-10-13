import io
import os
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from pypdf import PdfReader

from core.domain.documents import render_pdf
from rest_framework.test import APITestCase

from core.domain.resume_contacts import apply_resume_contacts
from core.models import CandidateProfile, JobPosting, Resume
from core.serializers import CandidateProfileSerializer
from core.services import create_tailored_resume


CONTACT = {
    'phone': '+1 (416) 555-0123', 'email': 'alex@example.com',
    'linkedin_url': 'https://www.linkedin.com/in/alex-example/',
    'include_phone': True, 'include_email': True, 'include_linkedin': True,
}
SOURCE = '''# Alex Example

Toronto | old@example.net | +1 (212) 555-0199
LinkedIn: [Old profile](https://www.linkedin.com/in/old-profile/)

## Experience

Engineer, Example Labs, 2021 - 2024
- Built telephone routing in 2020 - 2021, reducing costs by 30%.
- Managed a budget of 100000-150000 for delivery.
'''


class ResumeContactTests(SimpleTestCase):
    def test_replaces_source_contacts_and_preserves_identity_and_evidence(self):
        result = apply_resume_contacts(SOURCE, CONTACT, candidate_name='Alex Example')
        for value in ('Alex Example', 'Toronto', CONTACT['phone'], CONTACT['email'], CONTACT['linkedin_url'], '2021 - 2024', '2020 - 2021', '30%', '100000-150000'):
            self.assertIn(value, result)
        for value in ('old@example.net', '212', 'old-profile', 'Old profile'):
            self.assertNotIn(value, result)
        self.assertLess(result.index('Phone:'), result.index('## Experience'))
        self.assertEqual(apply_resume_contacts(result, CONTACT, candidate_name='Alex Example'), result)

    def test_individual_toggles_and_empty_fields(self):
        for field, toggle in [('phone', 'include_phone'), ('email', 'include_email'), ('linkedin_url', 'include_linkedin')]:
            with self.subTest(field=field):
                result = apply_resume_contacts(SOURCE, {**CONTACT, toggle: False}, candidate_name='Alex')
                self.assertNotIn(CONTACT[field], result)
                for other in {'phone', 'email', 'linkedin_url'} - {field}:
                    self.assertIn(CONTACT[other], result)
        blank = {**CONTACT, 'phone': '', 'email': '', 'linkedin_url': ''}
        result = apply_resume_contacts(SOURCE, blank, candidate_name='Alex')
        self.assertNotIn('Phone:', result)
        self.assertNotIn('Email:', result)
        self.assertNotIn('LinkedIn:', result)
        self.assertNotIn('old@example.net', result)

    def test_unconfigured_profile_preserves_legacy_resume(self):
        self.assertEqual(apply_resume_contacts(SOURCE, {}, candidate_name='Alex'), SOURCE)

    def test_phone_formats_do_not_leave_punctuation_behind(self):
        for phone in ('(416) 555-0199', '416.555.0199', '02 1234 5678', '+44 20 1234 5678'):
            result = apply_resume_contacts(f'# Alex\n\nPhone: {phone}\n\n## Experience\n\nEngineer', {**CONTACT, 'include_phone': False}, candidate_name='Alex')
            self.assertNotIn(phone, result)
            self.assertNotIn('\n(\n', result)
            self.assertNotIn('Phone:', result)

    def test_header_is_added_when_generator_omits_name(self):
        result = apply_resume_contacts('## Experience\n\nBuilt reporting tools.', CONTACT, candidate_name='Alex Example')
        self.assertTrue(result.startswith('# Alex Example\n\nPhone:'))

    def test_contact_settings_validation_on_profile_patch(self):
        for field, value in [('email', 'not-an-email'), ('phone', '<script>123</script>'), ('linkedin_url', 'https://linkedin.com.evil.example/in/alex'), ('linkedin_url', 'https://example.com'), ('linkedin_url', 'https://www.linkedin.com/in/')]:
            with self.subTest(field=field, value=value):
                serializer = CandidateProfileSerializer(data={'resume_contact': {**CONTACT, field: value}}, partial=True)
                self.assertFalse(serializer.is_valid())
                self.assertIn('resume_contact', serializer.errors)
        serializer = CandidateProfileSerializer(data={'resume_contact': {'email': 'alex@example.com'}}, partial=True)
        self.assertFalse(serializer.is_valid())
        serializer = CandidateProfileSerializer(data={'resume_contact': CONTACT}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    @skipUnless(os.environ.get('TEST_GOTENBERG_URL'), 'Set TEST_GOTENBERG_URL for real PDF verification')
    def test_export_contains_only_selected_contact_details(self):
        for enabled in (True, False):
            contact = {**CONTACT, 'include_phone': enabled}
            markdown = apply_resume_contacts(SOURCE, contact, candidate_name='Alex Example')
            with self.settings(GOTENBERG_URL=os.environ['TEST_GOTENBERG_URL']):
                with patch('core.domain.documents._store_artifact', side_effect=lambda **kwargs: kwargs):
                    artifact = render_pdf(owner=None, title='Resume contacts', markdown=markdown, kind='resume')
            self.assertEqual(artifact['mime_type'], 'application/pdf')
            reader = PdfReader(io.BytesIO(artifact['content']))
            text = '\n'.join(page.extract_text() for page in reader.pages)
            self.assertIn(CONTACT['email'], text)
            self.assertIn(CONTACT['linkedin_url'], text)
            self.assertEqual(CONTACT['phone'] in text, enabled)
            self.assertNotIn('old@example.net', text)
            links = [annotation.get_object().get('/A', {}).get('/URI') for page in reader.pages for annotation in page.get('/Annots', [])]
            self.assertIn(CONTACT['linkedin_url'], links)
            self.assertIn('mailto:' + CONTACT['email'], links)


class ResumeContactGenerationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='contact-owner', first_name='Alex', last_name='Example')
        self.profile = CandidateProfile.objects.create(owner=self.user, resume_contact=CONTACT)
        self.job = JobPosting.objects.create(owner=self.user, title='Engineer', description_text='Python engineer', content_hash='contact-job')
        self.source = Resume.objects.create(owner=self.user, kind='canonical', title='Source', content_markdown=SOURCE)

    @patch('core.ai.generate_json', return_value=None)
    def test_fallback_persists_visible_contact_snapshot_without_changing_source(self, generate):
        resume = create_tailored_resume(self.user, job=self.job)
        self.assertIn(CONTACT['email'], resume.content_markdown)
        self.assertNotIn('old@example.net', resume.content_markdown)
        self.assertEqual(resume.content_json['resume_contact']['phone'], CONTACT['phone'])
        self.source.refresh_from_db()
        self.assertEqual(self.source.content_markdown, SOURCE)
        self.profile.resume_contact = {**CONTACT, 'include_phone': False}
        self.profile.save()
        self.user.refresh_from_db()
        newer = create_tailored_resume(self.user, job=self.job)
        self.assertNotIn(CONTACT['phone'], newer.content_markdown)
        self.assertEqual(newer.content_json['resume_contact']['phone'], '')
        resume.refresh_from_db()
        self.assertIn(CONTACT['phone'], resume.content_markdown)

    @patch('core.services.tailor_resume')
    def test_ai_output_gets_same_contact_policy_as_fallback(self, tailor):
        tailor.return_value.data = {'content_markdown': SOURCE, 'title': 'Generated'}
        tailor.return_value.source = 'openai'
        resume = create_tailored_resume(self.user, job=self.job)
        self.assertIn(CONTACT['phone'], resume.content_markdown)
        self.assertNotIn('old@example.net', resume.content_markdown)
        self.assertNotIn('old@example.net', tailor.call_args.kwargs['canonical_markdown'])


class ResumeContactApiTests(APITestCase):
    @patch('core.views.enqueue_profile_search_refresh')
    @patch('core.views.publish_user_event')
    def test_settings_are_owner_scoped_and_round_trip(self, publish, enqueue):
        owner = get_user_model().objects.create_user(username='contact-api-owner')
        other = get_user_model().objects.create_user(username='contact-api-other')
        CandidateProfile.objects.create(owner=owner)
        other_profile = CandidateProfile.objects.create(owner=other, resume_contact={**CONTACT, 'email': 'other@example.com'})
        self.client.force_authenticate(owner)
        response = self.client.patch('/api/profile/', {'resume_contact': CONTACT}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.client.get('/api/profile/').data['resume_contact'], CONTACT)
        other_profile.refresh_from_db()
        self.assertEqual(other_profile.resume_contact['email'], 'other@example.com')
