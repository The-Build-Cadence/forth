from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.domain.documents import prepare_application_materials
from core.domain.material_preferences import document_design
from core.models import AccountSettings, CandidateProfile, CoverLetter, JobPosting, Resume

DESIGN = dict(template='minimal', layout='two_column', font='humanist', density='compact',
              accent='#224466', page_size='A4', max_pages=2)


@override_settings(OPENAI_API_KEY='')
class DocumentDefaultsTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='document-owner')
        self.other = get_user_model().objects.create_user(username='document-other')
        CandidateProfile.objects.create(owner=self.owner, generation_instructions='Classic design #112233')
        self.job = JobPosting.objects.create(owner=self.owner, title='Engineer', content_hash='defaults-job',
                                            generation_instructions='Modern design #abcdef')
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.url = '/api/account/settings/'

    def test_save_reload_and_owner_isolation(self):
        response = self.client.patch(self.url, {'document_design': DESIGN}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(self.url).data['document_design']['font'], 'humanist')
        self.assertEqual(document_design(self.owner, self.job)['accent'], '#224466')
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(self.url).data['document_design']['accent'], '#177d69')
        self.assertEqual(AccountSettings.objects.get(owner=self.owner).document_design, DESIGN)

    def test_invalid_values_do_not_overwrite_saved_defaults(self):
        self.client.patch(self.url, {'document_design': DESIGN}, format='json')
        for update in [dict(accent='red; display:none'), dict(font='bad'), dict(max_pages=4), dict(layout='bad')]:
            with self.subTest(update=update):
                response = self.client.patch(self.url, {'document_design': {**DESIGN, **update}}, format='json')
                self.assertEqual(response.status_code, 400)
        self.assertEqual(AccountSettings.objects.get(owner=self.owner).document_design, DESIGN)

    def test_unsaved_legacy_defaults_follow_instructions_and_preview_does_not_save(self):
        self.assertEqual(self.client.get(self.url).data['document_design']['accent'], '#112233')
        result = self.client.post('/api/account/document-design/preview/', DESIGN, format='json')
        self.assertEqual(result.status_code, 200)
        self.assertIn('column-count: 2', result.data['html'])
        self.assertIn('size: A4', result.data['html'])
        self.assertEqual(AccountSettings.objects.get(owner=self.owner).document_design, {})
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post('/api/account/document-design/preview/', DESIGN, format='json').status_code, 401)

    @patch('core.domain.documents._cover_letter_result')
    @patch('core.services.tailor_resume')
    def test_future_materials_inherit_saved_defaults_and_existing_versions_stay_unchanged(self, tailor, letter):
        tailor.return_value = SimpleNamespace(source='openai', data={'title':'Resume', 'content_markdown':'# Candidate',
            'design': {'font':'serif', 'accent':'#ffffff'}})
        letter.return_value = {'content_markdown':'# Candidate\nDear team,\nI would like to apply.'}
        existing = Resume.objects.create(owner=self.owner, title='Existing', content_json={'design': {'accent':'#991122'}})
        self.client.patch(self.url, {'document_design': DESIGN}, format='json')
        result = prepare_application_materials(self.owner, self.job)
        for item in [result['resume'], result['cover_letter']]:
            for key, value in DESIGN.items():
                self.assertEqual(item.content_json['design'][key], value)
        existing.refresh_from_db()
        self.assertEqual(existing.content_json['design']['accent'], '#991122')
        preview = self.client.get(f"/api/cover-letters/{result['cover_letter'].id}/design/")
        self.assertEqual(preview.status_code, 200)
        self.assertIn('color: #224466', preview.data['html'])
        self.assertNotIn('column-count: 2', preview.data['html'])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/cover-letters/{result['cover_letter'].id}/design/").status_code, 404)
