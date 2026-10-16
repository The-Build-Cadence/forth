"""Document semantics, evidence preservation, and optional real-renderer coverage."""
import io
import os
from unittest import skipUnless
from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, override_settings
from pypdf import PdfReader

from core.ai import tailor_resume
from core.domain.documents import document_html, render_pdf


SAMPLE = '''# Alex Example

Email: [alex@example.com](mailto:alex@example.com)
Portfolio: [Example projects](https://example.com/projects?a=1&b=2)

## Qualifications Summary

- Python delivery: built a Python reporting service at Example Labs.

## Skills

Python, SQL

## Experience

### Software Engineer

Employer: Example Labs
Dates: Jan 2021 - Dec 2024
Location: Toronto, Canada

- Built a Python reporting service that reduced weekly processing by 30%.

## Education

### Bachelor of Science

Example University, 2020
'''


class DocumentAccessibilityTests(SimpleTestCase):
    def test_semantic_reading_order_and_visible_links(self):
        rendered = document_html('Alex & Resume', SAMPLE, kind='resume')
        self.assertIn('<html lang="en-us">', rendered)
        self.assertIn('<title>Alex &amp; Resume</title>', rendered)
        self.assertIn('<main><header><h1>Alex Example</h1>', rendered)
        self.assertIn('<h2>Qualifications Summary</h2>', rendered)
        self.assertIn('<h3>Software Engineer</h3>', rendered)
        self.assertIn('<ul>\n<li>Python delivery:', rendered)
        self.assertIn('<a href="mailto:alex@example.com">alex@example.com</a>', rendered)
        self.assertIn('<a href="https://example.com/projects?a=1&amp;b=2">Example projects</a>', rendered)
        self.assertLess(rendered.index('Qualifications Summary'), rendered.index('<h2>Experience'))
        self.assertLess(rendered.index('Employer: Example Labs'), rendered.index('Dates: Jan 2021'))

    def test_html_and_unsafe_links_cannot_create_hidden_or_executable_content(self):
        rendered = document_html('Resume', '<span style="display:none">secret</span>\n[x](javascript:alert(1))', kind='resume')
        self.assertNotIn('<span', rendered)
        self.assertNotIn('href="javascript:', rendered)
        self.assertIn('&lt;span', rendered)

    def test_adjacent_links_and_parenthesized_urls_keep_separate_targets(self):
        rendered = document_html('Links', '[One](https://example.com/a_(b)),[Two](https://example.com/two)', kind='resume')
        self.assertIn('<a href="https://example.com/a_(b)">One</a>,<a href="https://example.com/two">Two</a>', rendered)

    @override_settings(GOTENBERG_URL='http://renderer')
    @patch('core.domain.documents._store_artifact', side_effect=lambda **kwargs: kwargs)
    @patch('core.domain.documents.requests.post')
    def test_pdf_export_requests_structure_and_outline(self, post, store):
        from io import BytesIO
        from pypdf import PdfWriter
        writer = PdfWriter(); writer.add_blank_page(width=612, height=792)
        buffer = BytesIO(); writer.write(buffer)
        post.return_value = Mock(content=buffer.getvalue())
        artifact = render_pdf(owner=None, title='Example', markdown=SAMPLE, kind='cover_letter')
        self.assertEqual(post.call_args.kwargs['data']['generateTaggedPdf'], 'true')
        self.assertEqual(post.call_args.kwargs['data']['generateDocumentOutline'], 'true')
        self.assertEqual(artifact['kind'], 'cover_letter_pdf')
        self.assertEqual(artifact['mime_type'], 'application/pdf')

    @override_settings(GOTENBERG_URL='http://renderer')
    @patch('core.domain.documents._store_artifact', side_effect=lambda **kwargs: kwargs)
    @patch('core.domain.documents.requests.post', side_effect=requests.ConnectionError('offline'))
    def test_html_fallback_preserves_semantics(self, post, store):
        artifact = render_pdf(owner=None, title='Example', markdown=SAMPLE, kind='resume')
        self.assertEqual(artifact['kind'], 'resume_html')
        self.assertIn(b'<main><header><h1>Alex Example</h1>', artifact['content'])
        self.assertIn(b'Employer: Example Labs', artifact['content'])

    @patch('core.ai.generate_json', return_value=None)
    def test_fallback_uses_supported_summary_without_inventing_history(self, generate):
        result = tailor_resume(
            canonical_markdown='# Alex Example\n\n## Experience\n\nEngineer at Example Labs, 2021',
            job_title='Python Engineer', job_text='Python and Kubernetes',
            facts=[{'title': 'Reporting service', 'statement': 'Built a Python reporting service at Example Labs.'}],
        )
        content = result.data['content_markdown']
        self.assertIn('## Qualifications Summary', content)
        self.assertIn('Built a Python reporting service at Example Labs.', content)
        self.assertIn('## Skills\n\nPython', content)
        self.assertNotIn('Kubernetes', content)
        self.assertIn('Engineer at Example Labs, 2021', content)

    @skipUnless(os.environ.get('TEST_GOTENBERG_URL'), 'Set TEST_GOTENBERG_URL for real PDF verification')
    def test_real_pdf_has_extractable_ordered_text_and_accessibility_structure(self):
        for template in ('modern', 'classic', 'minimal'):
            with self.subTest(template=template), self.settings(GOTENBERG_URL=os.environ['TEST_GOTENBERG_URL']):
                with patch('core.domain.documents._store_artifact', side_effect=lambda **kwargs: kwargs):
                    artifact = render_pdf(owner=None, title='Alex Example Resume', markdown=SAMPLE, kind='resume', design={'template': template})
                self.assertEqual(artifact['mime_type'], 'application/pdf')
                reader = PdfReader(io.BytesIO(artifact['content']))
                text = '\n'.join(page.extract_text() for page in reader.pages)
                for expected in ('Alex Example', 'alex@example.com', 'Example Labs', 'Jan 2021 - Dec 2024', '30%', 'Example University'):
                    self.assertIn(expected, text)
                self.assertLess(text.index('Python delivery:'), text.index('Employer:'))
                self.assertLess(text.index('Dates:'), text.index('Example University'))
                root = reader.trailer['/Root']
                self.assertTrue(root['/MarkInfo']['/Marked'])
                self.assertIn('/StructTreeRoot', root)
                self.assertEqual(root['/Lang'], 'en-us')
                self.assertTrue(reader.outline)
                self.assertEqual(reader.metadata.title, 'Alex Example Resume')
                links = [annotation.get_object().get('/A', {}).get('/URI') for page in reader.pages for annotation in page.get('/Annots', [])]
                self.assertIn('https://example.com/projects?a=1&b=2', links)
