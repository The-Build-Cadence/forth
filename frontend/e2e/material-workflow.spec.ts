import { expect, test } from '@playwright/test';

test('opportunity instructions, clear actions, and manual application tracking', async ({ page }, testInfo) => {
  const job: any = { id: 7, title: 'Platform Engineer', company: 'Example Labs', location: 'Toronto', remote_policy: 'remote', discovered_at: '2026-10-16T12:00:00Z', has_materials: false, materials_status: '', generation_instructions: null, application: null,
    match: { score: 39, normalized_score: 62, hard_filter_status: 'fail', confidence: 'high', explanation_json: { summary: 'Possible fit, eligibility fail.', eligibility_failures: ['This role requires onsite work; your profile requires remote work.'] }, missing_requirements: [], signals: [], supporting_facts: [] } };
  let generations = 0;
  await page.addInitScript(() => { localStorage.setItem('forth_access', 'ui-test'); sessionStorage.setItem('forth_onboarding_dismissed', '1'); });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/jobs/7/') {
      if (route.request().method() === 'PATCH') job.generation_instructions = route.request().postDataJSON().generation_instructions;
      return route.fulfill({ json: job });
    }
    if (path === '/api/jobs/7/create_application/') { job.application = { id: 3, status: 'saved' }; return route.fulfill({ json: job.application }); }
    if (path === '/api/jobs/7/regenerate_materials/') { generations++; job.materials_status = 'queued'; job.materials_started_at = new Date().toISOString(); return route.fulfill({ json: { mode: 'async' } }); }
    if (path === '/api/applications/3/') { job.application.status = route.request().postDataJSON().status; return route.fulfill({ json: job.application }); }
    return route.fulfill({ json: { count: 1, results: [job] } });
  });
  await page.goto('/matches');
  await expect(page.getByText('Required condition mismatch').first()).toBeVisible();
  await expect(page.getByText('This role requires onsite work; your profile requires remote work.')).toBeVisible();
  await expect(page.getByText('Possible fit, required condition mismatch.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Settings', exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Strategy', exact: true })).toHaveCount(0);
  await page.getByRole('checkbox', { name: 'Replace my account defaults' }).check();
  await page.getByRole('textbox', { name: 'Opportunity material instructions' }).fill('Minimal, compact, #123456.');
  await expect(page.getByRole('button', { name: 'Generate resume & cover letter' })).toBeDisabled();
  await page.getByRole('button', { name: 'Save instructions' }).click();
  await expect(page.getByRole('button', { name: 'Generate resume & cover letter' })).toBeEnabled();
  expect(job.generation_instructions).toBe('Minimal, compact, #123456.');
  await page.getByRole('button', { name: 'Save to pipeline', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Saved in pipeline' })).toBeDisabled();
  expect(generations).toBe(0);
  await page.getByRole('button', { name: 'Mark as Applied', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Marked Applied' })).toBeDisabled();
  await page.getByRole('button', { name: 'Generate resume & cover letter' }).click();
  await expect(page.getByRole('button', { name: 'Generating materials…' })).toBeDisabled();
  expect(generations).toBe(1);
  await page.reload();
  await expect(page.getByRole('button', { name: 'Generating materials…' })).toBeDisabled();
  const widths = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport + 1);
  await page.screenshot({ path: testInfo.outputPath('opportunity-actions.png'), fullPage: true });
});

test('studio separates source, contacts, generation, and review', async ({ page }, testInfo) => {
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
  await expect(page.getByRole('tab', { name: '4 · Review & download' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByRole('button', { name: 'Approve draft' })).toBeDisabled();
  await page.getByText('Review unsupported claims (1)').click();
  await expect(page.locator('.generation-notes')).toContainText('Built services.');
  await page.getByRole('tab', { name: '2 · Contact details' }).click();
  await expect(page.getByLabel('Email address', { exact: true })).toHaveValue('alex@example.com');
  await page.getByRole('tab', { name: '3 · Generate', exact: true }).click();
  await expect(page.locator('.studio-instruction-preview')).toContainText('Classic layout, #123456.');
  const widths = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport + 1);
  await page.screenshot({ path: testInfo.outputPath('resume-studio-generation.png'), fullPage: true });
});
