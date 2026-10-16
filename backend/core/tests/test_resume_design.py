from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch, Mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient
from pypdf import PdfWriter

from core.domain.documents import document_html, render_pdf
from core.domain.material_preferences import instruction_design
from core.models import CandidateProfile, JobPosting, Resume
from core.services import create_tailored_resume

INSTRUCTIONS = ('Create a polished, modern resume that positions me as a marketing leader. '
    'Use a clean, minimal design with a modern sans-serif font such as Aptos, Calibri, or Helvetica. '
    'Keep it to a maximum of two pages, using a balanced two-column layout if helpful. '
    'Use Letter-size paper, clear headings, consistent formatting, and a dark navy accent (#17324D). '
    'Prioritize readability and highlight strategic leadership, digital marketing expertise, '
    'team management, and measurable results.')

class DesignRenderingTests(SimpleTestCase):
    def test_real_user_instructions_resolve_all_visual_choices(self):
        design = instruction_design({'accent': '#123456', 'template': 'classic'}, INSTRUCTIONS)
        self.assertEqual({k: design[k] for k in ('accent', 'template', 'layout', 'font', 'max_pages', 'page_size')},
                         dict(accent='#17324D', template='minimal', layout='two_column', font='humanist', max_pages=2, page_size='Letter'))
        rendered = document_html('Test', '# Candidate\n\n## Skills\n- Leadership\n\n## Experience\nBuilt teams.', kind='resume', design=design)
        self.assertIn('column-count: 2', rendered)
        self.assertIn('size: Letter', rendered)
        self.assertIn('color: #17324D', rendered)
        self.assertIn('data:font/ttf;base64,', rendered)
        self.assertIn('<h2>Skills</h2>', rendered)
        self.assertNotIn('column-count: 2', document_html('Letter', '# Letter', kind='cover_letter', design=design))

    @override_settings(GOTENBERG_URL='http://renderer')
    @patch('core.domain.documents._store_artifact')
    @patch('core.domain.documents.requests.post')
    def test_page_limit_is_checked_without_truncating_content(self, post, store):
        def response(pages):
            writer = PdfWriter()
            for _ in range(pages): writer.add_blank_page(width=612, height=792)
            buffer = BytesIO(); writer.write(buffer)
            return Mock(content=buffer.getvalue())
        post.side_effect = [response(3), response(2)]
        render_pdf(owner=None, title='Resume', markdown='# Test', kind='resume', design={'max_pages': 2})
        self.assertEqual(post.call_count, 2)
        self.assertEqual(store.call_args.kwargs['metadata']['page_count'], 2)
        self.assertEqual(store.call_args.kwargs['metadata']['design']['density'], 'compact')
        post.side_effect = [response(3), response(3)]
        store.reset_mock()
        with self.assertRaisesMessage(ValueError, 'No content was cut off'):
            render_pdf(owner=None, title='Resume', markdown='# Test', kind='resume', design={'max_pages': 2})
        store.assert_not_called()

@override_settings(OPENAI_API_KEY='')
class ResumeDesignApiTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='designer')
        CandidateProfile.objects.create(owner=self.owner, generation_instructions=INSTRUCTIONS)
        self.job = JobPosting.objects.create(owner=self.owner, title='Marketing leader', content_hash='design-job')
        self.resume = Resume.objects.create(owner=self.owner, kind='tailored', title='Resume', target_job=self.job,
            content_markdown='# Candidate\n## Experience\nLed a marketing team.', approved=True, content_json={'other': 'preserved'})
        self.client = APIClient(); self.client.force_authenticate(self.owner)
        self.url = f'/api/resumes/{self.resume.id}/design/'

    def test_preview_is_read_only_and_save_changes_only_design(self):
        response = self.client.post(self.url, {'use_saved_instructions': True}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['design']['accent'], '#17324D')
        self.resume.refresh_from_db(); self.assertTrue(self.resume.approved)
        self.assertNotIn('design', self.resume.content_json)
        response = self.client.post(self.url, {'design': response.data['design'], 'save': True}, format='json')
        self.assertEqual(response.status_code, 200)
        self.resume.refresh_from_db()
        self.assertFalse(self.resume.approved)
        self.assertEqual(self.resume.content_json['other'], 'preserved')
        self.assertEqual(self.resume.content_markdown, '# Candidate\n## Experience\nLed a marketing team.')
        self.assertEqual(self.resume.content_json['design']['layout'], 'two_column')

    def test_override_validation_and_account_isolation(self):
        self.job.generation_instructions = 'Single column, classic design, #224466, A4.'; self.job.save()
        response = self.client.post(self.url, {'use_saved_instructions': True}, format='json')
        self.assertEqual(response.data['design']['layout'], 'single')
        self.assertEqual(response.data['design']['accent'], '#224466')
        for design in [{'accent': 'red;display:none'}, {'font': '<script>'}, {'max_pages': -1}, {'layout': 'bad'}]:
            self.assertEqual(self.client.post(self.url, {'design': design}, format='json').status_code, 400)
        self.client.force_authenticate(get_user_model().objects.create_user(username='stranger-designer'))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    @patch('core.services.tailor_resume')
    def test_explicit_instructions_override_ai_defaults_too(self, tailor):
        tailor.return_value = SimpleNamespace(source='openai', data={'title': 'Marketing', 'content_markdown': '# Candidate',
            'design': {'template':'classic', 'accent':'#177d69', 'layout':'single', 'font':'serif', 'page_size':'A4', 'max_pages':0}})
        generated = create_tailored_resume(self.owner, job=self.job)
        self.assertEqual(generated.content_json['design']['accent'], '#17324D')
        self.assertEqual(generated.content_json['design']['layout'], 'two_column')
        self.assertEqual(generated.content_json['design']['max_pages'], 2)

    def test_save_design_with_nullable_parent_and_job_on_postgres(self):
        self.resume.parent_resume = None
        self.resume.target_job = None
        self.resume.save()
        result = self.client.post(self.url, {'design': {'accent': '#552244'}, 'save': True}, format='json')
        self.assertEqual(result.status_code, 200)
        self.resume.refresh_from_db()
        self.assertEqual(self.resume.content_json['design']['accent'], '#552244')

    def test_preview_and_source_export_remove_legacy_notes_and_mangled_duplicate_contact(self):
        self.resume.content_markdown = '# Alex Candidate\nalex.candidate@gmail.com\nAlex Candidate@Gmail Com\n## Experience\nDesign: Led brand strategy.\nDesign: Modern template with balanced two-column layout, sans-serif font (Calibri), letter-sized pages, accent color #17324D, max two pages.'
        self.resume.content_json = {'resume_contact': {'email':'alex.candidate@gmail.com'}}
        self.resume.save()
        response = self.client.get(self.url)
        rendered = response.data['html']
        self.assertNotIn('Modern template with', rendered)
        self.assertNotIn('Alex Candidate@Gmail Com', rendered)
        self.assertIn('Design: Led brand strategy.', rendered)
        self.assertIn('mailto:alex.candidate@gmail.com', rendered)
        self.assertEqual(rendered.count('Email:'), 1)
        markdown = self.client.get(f'/api/resumes/{self.resume.id}/export_markdown/').content.decode()
        self.assertNotIn('Modern template with', markdown)
        self.assertNotIn('Alex Candidate@Gmail Com', markdown)
