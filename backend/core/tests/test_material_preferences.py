from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from core.domain.documents import prepare_application_materials, document_html
from core.domain.material_preferences import material_instructions
from core.domain.resume_contacts import import_resume_contacts
from core.models import Application, CandidateProfile, JobPosting, ProfileDocument
from core.tasks import regenerate_application_materials_task
from mcp_server import authenticated_owner, get_opportunity, get_application, list_applications, set_material_instructions, update_application, ToolError


@override_settings(OPENAI_API_KEY='', CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class MaterialPreferencesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='materials-user')
        self.profile = CandidateProfile.objects.create(owner=self.user, generation_instructions='Use classic, compact, A4 and #123abc.')
        self.job = JobPosting.objects.create(owner=self.user, title='Engineer', content_hash='instructions-job')
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def test_instruction_inheritance_override_and_explicit_empty(self):
        self.assertEqual(material_instructions(self.user, self.job), self.profile.generation_instructions)
        self.job.generation_instructions = 'minimal'
        self.assertEqual(material_instructions(self.user, self.job), 'minimal')
        self.job.generation_instructions = ''
        self.assertEqual(material_instructions(self.user, self.job), '')
        self.job.generation_instructions = None
        self.assertEqual(material_instructions(self.user, self.job), self.profile.generation_instructions)

    def test_both_materials_receive_instructions_and_design_reaches_export(self):
        with patch('core.ai.generate_json', return_value=None) as resume_ai, patch('core.domain.documents.generate_json', return_value=None) as letter_ai:
            result = prepare_application_materials(self.user, self.job)
        for call in (resume_ai, letter_ai):
            self.assertIn(self.profile.generation_instructions, call.call_args.args[1])
        for material in result.values():
            self.assertEqual(material.content_json['generation_instructions'], self.profile.generation_instructions)
            design = material.content_json['design']
            self.assertEqual(design['accent'], '#123abc')
            self.assertEqual(design['template'], 'classic')
            self.assertEqual(design['page_size'], 'A4')
            self.assertIn('#123abc', document_html(material.title, material.content_markdown, kind='resume', design=design))

    def test_contact_import_does_not_overwrite_user_choices(self):
        text = '# Alex\nToronto | alex@example.com | (416) 555-0123\nlinkedin.com/in/alex\n2020 - 2024'
        contact = import_resume_contacts(self.user, text)
        self.assertEqual(contact['email'], 'alex@example.com')
        self.assertEqual(contact['phone'], '(416) 555-0123')
        self.assertEqual(contact['linkedin_url'], 'https://linkedin.com/in/alex')
        self.profile.refresh_from_db()
        self.profile.resume_contact = {**contact, 'include_email': False}
        self.profile.save()
        import_resume_contacts(self.user, 'new@example.com +1 212 555 9999')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.resume_contact['email'], 'alex@example.com')
        self.assertFalse(self.profile.resume_contact['include_email'])

    def test_no_contacts_does_not_lock_in_empty_settings(self):
        self.assertEqual(import_resume_contacts(self.user, 'Experience 2020 - 2024\nBudget 100000-150000'), {})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.resume_contact, {})

    def test_canonical_creation_extracts_contacts(self):
        response = self.api.post('/api/resumes/', {'kind': 'canonical', 'title': 'Source', 'content_markdown': '# Alex\nalex@example.com'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.resume_contact['email'], 'alex@example.com')

    def test_manual_applied_without_resume_and_status_preserved_on_regeneration(self):
        app = Application.objects.create(owner=self.user, job=self.job)
        response = self.api.patch(f'/api/applications/{app.id}/', {'status': 'applied'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data['applied_at'])
        applied_at = response.data['applied_at']
        regenerate_application_materials_task(self.job.id)
        app.refresh_from_db()
        self.assertEqual(app.status, 'applied')
        self.assertEqual(app.events.filter(event_type='status_changed').count(), 1)
        response = self.api.patch(f'/api/applications/{app.id}/', {'notes': 'Follow up next week'}, format='json')
        self.assertEqual(response.data['applied_at'], applied_at)

    def test_regeneration_failure_preserves_status(self):
        app = Application.objects.create(owner=self.user, job=self.job, status='offer')
        with patch('core.domain.documents.prepare_application_materials', side_effect=ValueError('failed')):
            with self.assertRaises(ValueError):
                regenerate_application_materials_task(self.job.id)
        app.refresh_from_db(); self.job.refresh_from_db()
        self.assertEqual(app.status, 'offer')
        self.assertEqual(self.job.materials_status, 'failed')

    def test_generation_endpoint_deduplicates_pending_request(self):
        ProfileDocument.objects.create(owner=self.user, kind="resume", status="ready", raw_text="Platform engineering experience")
        with patch('core.views.regenerate_application_materials_task.delay') as task:
            task.return_value.id = 'test-task'
            for _ in range(2):
                response = self.api.post(f'/api/jobs/{self.job.id}/regenerate_materials/', {}, format='json')
                self.assertEqual(response.status_code, 202)
            self.assertEqual(task.call_count, 1)
        response = self.api.get(f'/api/jobs/{self.job.id}/')
        self.assertEqual(response.data['materials_status'], 'queued')
        self.assertFalse(response.data['has_materials'])

    def test_mcp_owner_scope_validation_and_tracking(self):
        stranger = get_user_model().objects.create_user(username='stranger')
        foreign = JobPosting.objects.create(owner=stranger, title='Private', content_hash='foreign')
        app = Application.objects.create(owner=self.user, job=self.job)
        foreign_app = Application.objects.create(owner=stranger, job=foreign)
        with authenticated_owner(self.user):
            self.assertEqual(list_applications({})['count'], 1)
            self.assertEqual(get_opportunity({'job_id': self.job.id})['effective_generation_instructions'], self.profile.generation_instructions)
            set_material_instructions({'job_id': self.job.id, 'instructions': ''})
            self.assertEqual(get_opportunity({'job_id': self.job.id})['effective_generation_instructions'], '')
            set_material_instructions({'job_id': self.job.id, 'instructions': None})
            self.assertEqual(get_opportunity({'job_id': self.job.id})['instruction_source'], 'account')
            result = update_application({'application_id': app.id, 'changes': {'status': 'applied', 'notes': 'Submitted externally'}})
            self.assertIsNotNone(result['applied_at'])
            self.assertEqual(get_application({'application_id': app.id})['notes'], 'Submitted externally')
            for action, args in [(get_application, {'application_id': foreign_app.id}), (get_opportunity, {'job_id': foreign.id}), (set_material_instructions, {'job_id': foreign.id, 'instructions': 'foo'}), (update_application, {'application_id': foreign_app.id, 'changes': {'status': 'applied'}})]:
                with self.assertRaises(ToolError): action(args)
            for changes in [{'status': 'bogus'}, {'follow_up_at': 'yesterday'}, {'owner': stranger.id}]:
                with self.assertRaises(ToolError): update_application({'application_id': app.id, 'changes': changes})
            with self.assertRaises(ToolError): set_material_instructions({'instructions': 'x' * 6001})

    def test_uploaded_resume_ingestion_seeds_contact_settings(self):
        from core.services import ingest_profile_document
        document = ProfileDocument.objects.create(owner=self.user, kind='resume', title='First resume',
            raw_text='# Alex\nalex@example.com | +1 416 555 0123\nhttps://linkedin.com/in/alex\nBuilt Python services.')
        ingest_profile_document(document)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.resume_contact['email'], 'alex@example.com')
        self.assertEqual(self.profile.resume_contact['linkedin_url'], 'https://linkedin.com/in/alex')

    def test_contacts_in_html_and_pdf_link_destinations(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from reportlab.pdfgen import canvas
        from core.services import extract_text_from_upload
        with TemporaryDirectory() as directory:
            html = Path(directory) / 'resume.html'
            html.write_text('<h1>Alex</h1><a href="mailto:alex@example.com">Email</a><a href="https://linkedin.com/in/alex">LinkedIn</a>')
            text = extract_text_from_upload(str(html))
            self.assertIn('alex@example.com', text)
            self.assertIn('https://linkedin.com/in/alex', text)
            pdf = Path(directory) / 'resume.pdf'
            drawing = canvas.Canvas(str(pdf))
            drawing.drawString(72, 720, 'Alex - LinkedIn')
            drawing.linkURL('https://linkedin.com/in/alex', (72, 715, 170, 735))
            drawing.save()
            self.assertIn('https://linkedin.com/in/alex', extract_text_from_upload(str(pdf)))

    def test_failed_initial_generation_returns_to_saved(self):
        with patch('core.domain.documents.prepare_application_materials', side_effect=ValueError('failed')):
            with self.assertRaises(ValueError):
                regenerate_application_materials_task(self.job.id)
        self.assertEqual(Application.objects.get(job=self.job).status, 'saved')
