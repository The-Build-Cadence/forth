import { expect, Page, test } from '@playwright/test';

async function workspace(page: Page) {
  const job: any = {id: 7, title: 'Platform Engineer', company: 'Example Labs', location: 'Toronto', remote_policy: 'remote', description_text: 'Build reliable services with Python.', document_status: 'not_created', has_materials: false, materials_status: '', application: null, generation_instructions: null, application_url: 'https://employer.example/apply', source_url: '', requirements: [], versions: [], match: {score: 70, normalized_score: 80, hard_filter_status: 'pass', meets_profile_threshold: true, explanation_json: {}, signals: [], supporting_facts: [], missing_requirements: []}};
  const resume: any = {id: 8, kind: 'tailored', target_job: 7, target_job_title: job.title, title: 'Platform resume', content_markdown: '# Alex\n\nExperienced engineer.', content_json: {}, validation: {}, approved: false};
  const letter: any = {id: 9, target_job: 7, target_job_title: job.title, title: 'Platform cover letter', content_markdown: 'Dear team, I build reliable services.', content_json: {}, validation: {}, version: 1, approved: false};
  let application: any;
  let generations = 0;
  const save = () => {
    application ||= {id: 3, job: 7, status: 'saved', resume: null, resume_detail: null, cover_letters: [], form_fields: [], application_form_url: job.application_url, applied_at: null, follow_up_at: null, outcome: '', notes: '', contact_name: '', contact_email: '', events: [], artifacts: [], updated_at: new Date().toISOString()};
    job.application = {id: 3, status: application.status, updated_at: application.updated_at};
    return {...application, job_detail: {...job}};
  };
  await page.addInitScript(() => { if (window !== window.top) return; localStorage.setItem('forth_access', 'ui-test'); sessionStorage.setItem('forth_onboarding_dismissed', '1'); });
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === '/api/jobs/7/') {
      if (route.request().method() === 'PATCH') Object.assign(job, route.request().postDataJSON());
      return route.fulfill({json: job});
    }
    if (path === '/api/jobs/7/create_application/') return route.fulfill({json: save()});
    if (path === '/api/jobs/7/regenerate_materials/') {
      generations++; save(); job.document_status = 'generating'; job.materials_status = 'queued'; job.materials_started_at = new Date().toISOString();
      if (!application.applied_at) application.status = 'preparing';
      save(); return route.fulfill({json: {mode: 'async'}});
    }
    if (path === '/api/applications/3/') {
      if (route.request().method() === 'PATCH') Object.assign(application, route.request().postDataJSON());
      return route.fulfill({json: save()});
    }
    if (path === '/api/applications/') return route.fulfill({json: {count: application ? 1 : 0, results: application ? [save()] : []}});
    if (path === '/api/resumes/8/approve/' || path === '/api/cover-letters/9/approve/') {
      const document = path.includes('/resumes/') ? resume : letter;
      document.approved = true; job.document_status = resume.approved && letter.approved ? 'reviewed' : 'needs_review';
      return route.fulfill({json: document});
    }
    if (path === '/api/resumes/8/design/') return route.fulfill({json: {design: {template: 'modern', density: 'balanced', accent: '#123456', page_size: 'Letter', layout: 'single', font: 'sans', max_pages: 0}, html: '<h1>Alex</h1><p>Experienced engineer.</p>', resume}});
    if (path === '/api/resumes/') return route.fulfill({json: {count: job.has_materials ? 1 : 0, results: job.has_materials && url.searchParams.get('kind') !== 'canonical' ? [resume] : []}});
    if (path === '/api/cover-letters/') return route.fulfill({json: {count: job.has_materials ? 1 : 0, results: job.has_materials ? [letter] : []}});
    if (path === '/api/profile/') return route.fulfill({json: {resume_contact: {}, target_roles: ['Platform Engineer'], onboarding_completed_at: new Date().toISOString()}});
    return route.fulfill({json: {count: 1, results: [job]}});
  });
  return {job, save, generations: () => generations, application: () => application};
}

test('save, prepare, review and record submission in one workspace', async ({page}, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const state = await workspace(page);
  await page.goto('/jobs/7');
  await page.getByRole('button', {name: 'Save job', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Prepare documents', exact: true}).first()).toBeVisible();
  expect(state.generations()).toBe(0);
  expect(state.application().applied_at).toBeNull();
  await page.getByRole('button', {name: 'Prepare documents', exact: true}).first().click();
  await expect(page.getByRole('button', {name: 'Preparing documents…', exact: true})).toBeDisabled();
  await page.reload();
  await expect(page.getByRole('button', {name: 'Preparing documents…', exact: true})).toBeDisabled();
  state.job.has_materials = true; state.job.document_status = 'needs_review'; state.job.materials_status = 'ready';
  await expect(page.getByRole('button', {name: 'Review documents', exact: true})).toBeVisible({timeout: 10000});
  await expect(page.frameLocator('iframe[title="Designed resume preview"]').getByRole('heading', {name: 'Alex'})).toBeVisible();
  await page.screenshot({path: info.outputPath('document-review.png'), fullPage: true});
  await page.getByRole('button', {name: 'Mark resume as reviewed'}).click();
  await expect(page.getByText('Documents: Needs review', {exact: true})).toBeVisible();
  await page.getByRole('button', {name: /Platform cover letter/}).click();
  await page.getByRole('button', {name: 'Mark cover letter as reviewed'}).click();
  const apply = page.getByRole('link', {name: 'Apply on employer site ↗', exact: true});
  await expect(apply).toBeVisible();
  await expect(apply).toHaveAttribute('target', '_blank');
  const popupPromise = page.waitForEvent('popup'); await apply.click();
  const popup = await popupPromise; await popup.close();
  expect(state.application().applied_at).toBeNull();
  await page.getByRole('button', {name: 'Mark as applied', exact: true}).first().click();
  await page.getByRole('button', {name: 'Confirm submission'}).click();
  await expect(page.getByRole('button', {name: 'Update progress', exact: true})).toBeVisible();
  expect(state.application().status).toBe('applied');
  await page.getByLabel('Notes', {exact: true}).fill('Follow up next week.');
  await page.getByRole('button', {name: 'Save progress'}).click();
  await expect(page.getByText('Changes saved.', {exact: true})).toBeVisible();
  expect(state.application().notes).toBe('Follow up next week.');
  expect(state.generations()).toBe(1);
  expect(errors).toEqual([]);
  await expect(page).toHaveURL(/\/jobs\/7/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  await page.screenshot({path: info.outputPath('job-workspace.png'), fullPage: true});
});

test('already applied skips documents and cancellation changes nothing', async ({page}) => {
  const state = await workspace(page); await page.goto('/jobs/7');
  await page.getByRole('button', {name: 'I already applied'}).click();
  await page.getByRole('button', {name: 'Cancel', exact: true}).click();
  expect(state.application()).toBeUndefined();
  await page.getByRole('button', {name: 'I already applied'}).click();
  await page.getByRole('button', {name: 'Confirm submission'}).click();
  await expect(page.getByRole('button', {name: 'Update progress'})).toBeVisible();
  expect(state.generations()).toBe(0); expect(state.application().applied_at).toBeTruthy();
});

test('legacy links, writing preferences and retry', async ({page}) => {
  const state = await workspace(page); state.save(); state.job.document_status = 'failed';
  await page.goto('/pipeline?application=3'); await expect(page).toHaveURL(/\/jobs\/7/);
  await page.getByRole('button', {name: 'Documents', exact: true}).click();
  await page.getByText('Writing preferences for this job', {exact: true}).click();
  await page.getByLabel('Use custom writing instructions').check();
  await page.getByLabel('Writing instructions', {exact: true}).fill('Keep it concise.');
  await expect(page.getByRole('button', {name: 'Retry document preparation'})).toBeDisabled();
  await page.getByRole('button', {name: 'Save writing preferences'}).click();
  await page.getByRole('button', {name: 'Retry document preparation'}).click();
  expect(state.job.generation_instructions).toBe('Keep it concise.');
  await expect(page.getByRole('button', {name: 'Preparing documents…'})).toBeDisabled();
  await page.goto('/matches?job=7'); await expect(page).toHaveURL(/\/jobs\/7/);
});

test('six stages preserve legacy interviews and show reminders', async ({page}) => {
  const state = await workspace(page); state.save();
  state.application().status = 'technical_screen'; state.application().follow_up_at = '2020-01-01T00:00:00Z';
  await page.goto('/pipeline');
  await expect(page.locator('.pipeline-col')).toHaveCount(6);
  await expect(page.locator('[data-pipeline-status="recruiter_screen"] .application-card')).toContainText('Platform Engineer');
  await expect(page.getByText('Follow-up due', {exact: true})).toBeVisible();
  await page.getByRole('button', {name: /Platform Engineer/}).click(); await expect(page).toHaveURL(/\/jobs\/7/);
});

test('background completion preserves unsaved notes and newer application progress', async ({page}) => {
  const state = await workspace(page); state.save();
  state.job.document_status = 'generating';
  await page.goto('/jobs/7?tab=tracking');
  await page.getByLabel('Notes', {exact: true}).fill('Keep this unsaved note.');
  state.job.document_status = 'needs_review'; state.job.has_materials = true;
  state.application().status = 'materials_ready';
  await expect(page.getByText('Documents: Needs review', {exact: true})).toBeVisible();
  await expect(page.getByLabel('Notes', {exact: true})).toHaveValue('Keep this unsaved note.');
  await page.getByRole('button', {name: 'Save progress'}).click();
  await expect(page.getByText('Changes saved.', {exact: true})).toBeVisible();
  expect(state.application().status).toBe('materials_ready');
  expect(state.application().notes).toBe('Keep this unsaved note.');
});

test('new generation opens the newest draft while retaining older versions', async ({page}) => {
  const state = await workspace(page); state.save();
  state.job.has_materials = true; state.job.document_status = 'needs_review';
  await page.goto('/jobs/7?tab=documents');
  await expect(page.locator('.result-toolbar h2')).toHaveText('Platform resume');
  await page.getByText('More actions', {exact: true}).click();
  await page.getByRole('button', {name: 'Generate new document versions'}).click();
  await expect(page.getByRole('button', {name: 'Preparing documents…'})).toBeDisabled();
  const latest = {id: 18, title: 'Newest draft', kind: 'tailored', target_job: 7, approved: false, content_json: {}, validation: {}};
  const older = {...latest, id: 8, title: 'Platform resume', approved: true};
  await page.route('**/api/resumes/?*', route => route.fulfill({json: {count: 2, results: [latest, older]}}));
  await page.route('**/api/resumes/18/design/', route => route.fulfill({json: {design: {template: 'modern', density: 'balanced', accent: '#123456'}, html: '<h1>Newest draft</h1>', resume: latest}}));
  state.job.document_status = 'needs_review'; state.job.materials_status = 'ready';
  await expect(page.locator('.result-toolbar h2')).toHaveText('Newest draft', {timeout: 10000});
  await expect(page.locator('.material-library').getByRole('button', {name: /Platform resume/})).toBeVisible();
});
