import { expect, test } from '@playwright/test';

test('document library preserves review safeguards and contact settings', async ({ page }, testInfo) => {
  const job = { id: 7, title: 'Platform Engineer', company: 'Example', generation_instructions: 'Classic layout, #123456.' };
  const resume = { id: 8, kind: 'tailored', title: 'Platform resume', target_job: 7, target_job_title: 'Platform Engineer', content_markdown: '# Alex\n\n## Experience\n\n- Built services.', content_json: {}, validation: { unsupported_claims: ['Built services.'] }, approved: false };
  await page.addInitScript(() => { localStorage.setItem('forth_access', 'ui-test'); sessionStorage.setItem('forth_onboarding_dismissed', '1'); });
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/profile/') return route.fulfill({ json: { resume_contact: { email: 'alex@example.com', include_email: true }, generation_instructions: 'Use minimal.' } });
    if (url.pathname === '/api/jobs/7/') return route.fulfill({ json: job });
    if (url.pathname === '/api/jobs/') return route.fulfill({ json: { count: 1, results: [job] } });
    if (url.pathname === '/api/resumes/') return route.fulfill({ json: { count: 1, results: url.searchParams.get('kind') === 'canonical' ? [] : [resume] } });
    return route.fulfill({ json: { count: 0, results: [] } });
  });
  await page.goto('/resume-lab?job=7');
  await expect(page.getByRole('tab', { name: 'Review & download' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('button', { name: 'Mark resume as reviewed' })).toBeDisabled();
  await page.getByText('Review unsupported claims (1)').click();
  await expect(page.locator('.generation-notes')).toContainText('Built services.');
  await page.getByRole('tab', { name: 'Contact details' }).click();
  await expect(page.getByLabel('Email address', { exact: true })).toHaveValue('alex@example.com');
  await expect(page.getByRole('link', { name: 'Choose a job to prepare' })).toHaveAttribute('href', '/matches');
  const widths = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport + 1);
  await page.screenshot({ path: testInfo.outputPath('resume-studio-generation.png'), fullPage: true });
});
