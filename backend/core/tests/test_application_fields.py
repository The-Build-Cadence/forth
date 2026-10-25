from types import SimpleNamespace as NS
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError

from core.domain.application_fields import html_fields, merge_fields, prepare_answers, register_fields, discover_fields
from core.models import Application, CandidateProfile, JobPosting, ProfileFact


class ApplicationFieldTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='field-user', email='candidate@example.com', first_name='Alex')
        self.other = get_user_model().objects.create_user(username='field-other')
        CandidateProfile.objects.create(owner=self.user, resume_contact={'phone': '+1 555 111 2222'})
        self.job = JobPosting.objects.create(owner=self.user, title='Engineer', company='Example', description_text='Build Python software.', content_hash='fields')
        self.app = Application.objects.create(owner=self.user, job=self.job)
        self.fact = ProfileFact.objects.create(owner=self.user, fact_type='skill', title='Python', statement='Builds Python software.', verified_by_user=True, lifecycle='verified')

    def test_html_field_extraction_retains_labels_choices_and_limits(self):
        result = html_fields('''<form><input name="csrf" type="hidden"><label for="why">Why this company?</label><textarea id="why" name="why" required maxlength="500"></textarea><label for="mode">Work mode</label><select id="mode" name="mode"><option value="">Choose</option><option value="r">Remote</option></select><input name="password" type="password"></form>''')
        self.assertEqual([f['id'] for f in result], ['why', 'mode'])
        self.assertEqual(result[0]['label'], 'Why this company?')
        self.assertEqual(result[0]['max_length'], 500)
        self.assertTrue(result[0]['required'])
        self.assertEqual(result[1]['options'], ['Remote'])

    def test_brave_discovered_fields_are_prepared_with_contact_information(self):
        self.job.extracted_json = {'application_fields': [{'id': 'email', 'label': 'Email', 'type': 'email'}]}
        self.job.save()
        result = prepare_answers(self.app)
        self.assertEqual(result[0]['answer'], 'candidate@example.com')
        self.assertEqual(result[0]['status'], 'draft')

    @patch('core.domain.application_fields.generate_json')
    def test_dynamic_drafts_preserve_user_answers_and_leave_sensitive_fields(self, generate):
        register_fields(self.app, [{'id': 'why', 'label': 'Why this company?', 'max_length': 100},
                                  {'id': 'my-answer', 'label': 'Why this role?', 'answer': 'My own answer.'},
                                  {'id': 'consent', 'label': 'I agree to these terms', 'type': 'checkbox'}])
        generate.return_value = NS(data={'answers': [{'id': 'why', 'answer': 'My Python work fits this engineering role.', 'needs_input': False, 'note': '', 'evidence_ids': [self.fact.id]}]})
        result = {f['id']: f for f in prepare_answers(self.app)}
        self.assertEqual(result['why']['status'], 'draft')
        self.assertEqual(result['my-answer']['answer'], 'My own answer.')
        self.assertEqual(result['consent']['status'], 'needs_input')
        self.assertEqual(result['consent']['answer'], '')
        self.assertNotIn('I agree', generate.call_args.args[1])

    @patch('core.domain.application_fields.generate_json')
    def test_invalid_generated_choices_and_limits_do_not_become_answers(self, generate):
        register_fields(self.app, [{'id': 'q', 'label': 'Pick', 'type': 'select', 'options': ['One'], 'max_length': 3}])
        generate.return_value = NS(data={'answers': [{'id': 'q', 'answer': 'Invented', 'needs_input': False, 'evidence_ids': []}]})
        self.assertEqual(prepare_answers(self.app)[0]['answer'], '')

    def test_duplicate_fields_and_invalid_user_options_are_rejected(self):
        with self.assertRaises(ValidationError):
            merge_fields([], [{'id': 'same', 'label': 'A'}, {'id': 'same', 'label': 'B'}])
        with self.assertRaises(ValidationError):
            merge_fields([], [{'id': 'q', 'label': 'Pick', 'type': 'select', 'options': ['One'], 'answer': 'Two'}])

    @patch('core.domain.application_fields._public_page')
    def test_greenhouse_question_discovery(self, fetch):
        self.app.application_form_url = 'https://job-boards.greenhouse.io/example/jobs/123'
        fetch.return_value = '{"questions":[{"label":"Why us?","required":true,"fields":[{"name":"q_1","type":"textarea"}]}]}'
        fields = discover_fields(self.app)
        self.assertEqual(fields[0]['id'], 'q_1')
        self.assertTrue(fields[0]['required'])
        self.assertIn('?questions=true', fetch.call_args.args[0])

    def test_api_and_mcp_enforce_ownership(self):
        api = APIClient()
        api.force_authenticate(self.other)
        self.assertEqual(api.post(f'/api/applications/{self.app.id}/prepare_answers/', {}, format='json').status_code, 404)
        from mcp_server import authenticated_owner, prepare_application_answers, ToolError
        with authenticated_owner(self.other), self.assertRaises(ToolError):
            prepare_application_answers({'application_id': self.app.id})
        with authenticated_owner(self.user):
            result = prepare_application_answers({'application_id': self.app.id, 'fields': [{'id': 'contact', 'label': 'Email'}]})
        self.assertEqual(result['fields'][0]['answer'], 'candidate@example.com')

    @patch('core.domain.application_fields.generate_json')
    def test_concurrent_edit_is_preserved(self, generate):
        register_fields(self.app, [{'id': 'why', 'label': 'Why us?'}])
        def edit_during_generation(*args):
            Application.objects.filter(pk=self.app.pk).update(form_fields=[{'id': 'new', 'label': 'New question'}])
            return None
        generate.side_effect = edit_during_generation
        with self.assertRaises(ValidationError):
            prepare_answers(self.app)
        self.app.refresh_from_db()
        self.assertEqual(self.app.form_fields[0]['id'], 'new')

    def test_non_application_forms_are_ignored(self):
        result = html_fields('<form id="newsletter"><label>Email<input name="email"></label><button>Subscribe</button></form>')
        self.assertEqual(result, [])

    @patch('core.public_http.public_get')
    @patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 80))])
    def test_private_application_url_is_not_fetched(self, dns, get):
        from core.domain.application_fields import _public_page
        with self.assertRaises(ValueError):
            _public_page('http://internal.example/application')
        get.assert_not_called()

    def test_typed_answers_are_validated(self):
        from core.domain.application_fields import valid_answer
        self.assertFalse(valid_answer({'type': 'email'}, 'not-an-email'))
        self.assertFalse(valid_answer({'type': 'number'}, 'NaN'))
        self.assertTrue(valid_answer({'type': 'date'}, '2026-10-16'))
        self.assertFalse(valid_answer({'type': 'multiselect', 'options': ['A', 'B']}, 'A\nC'))
