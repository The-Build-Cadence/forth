import { expect, Page, test } from '@playwright/test';

const routes = [
  ['/dashboard', 'Good morning.'],
  ['/concierge', 'Your job search has a chief of staff.'],
  ['/matches', 'Decide where your effort belongs.'],
  ['/pipeline', 'Every stage should create the next useful action.'],
  ['/resume-lab', 'Resume Studio'],
  ['/profile', 'The system should know the whole story.'],
  ['/sources', 'A quiet, reliable discovery engine.'],
  ['/strategy', 'Strategy'],
  ['/settings', 'Settings'],
] as const;

async function login(page: Page): Promise<void> {
  await page.goto('/login');
  await expect(page).toHaveTitle(/Forth/);
  await expect(page.locator('.auth-brand:visible, .mobile-auth-brand:visible')).toContainText('Forth');
  await page.getByLabel('Email or username').fill('admin');
  await page.getByLabel('Password').fill('adminpass');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', { name: /Good morning/ })).toBeVisible();
  const onboarding = page.locator('.onboarding-modal');
  if (await onboarding.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await page.getByRole('button', { name: 'Finish onboarding later' }).click();
    await expect(onboarding).toBeHidden();
  }
  await expect(page.locator('.brand:visible, .mobile-brand:visible').first()).toContainText('Forth');
}

async function assertHealthyLayout(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    document: document.documentElement.scrollWidth,
  }));
  expect(overflow.document, `document overflowed: ${JSON.stringify(overflow)}`).toBeLessThanOrEqual(overflow.viewport + 1);
  await expect(page.locator('main.app-main')).toBeVisible();
}

test.beforeEach(async ({ page }) => {
  const failures: string[] = [];
  page.on('pageerror', (error) => failures.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error' && !message.text().includes('favicon.ico')) failures.push(`console: ${message.text()}`);
  });
  await login(page);
  (page as any).__qaFailures = failures;
});

test.afterEach(async ({ page }) => {
  expect((page as any).__qaFailures || []).toEqual([]);
});

test('all primary screens render without viewport overflow', async ({ page }, testInfo) => {
  for (const [route, heading] of routes) {
    await page.goto(route);
    await expect(page.getByRole('heading', { name: heading })).toBeVisible();
    await assertHealthyLayout(page);
    await page.screenshot({ path: testInfo.outputPath(`${route.slice(1)}.png`), fullPage: true });
  }
});

test('mobile navigation is operable and closes after selection', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'desktop', 'Drawer behavior applies below the desktop breakpoint.');
  await page.getByRole('button', { name: 'Toggle navigation' }).click();
  await expect(page.locator('.side-nav')).toHaveClass(/open/);
  await page.getByRole('link', { name: /Candidate Profile/ }).click();
  await expect(page).toHaveURL(/\/profile$/);
  await expect(page.locator('.side-nav')).not.toHaveClass(/open/);
  await assertHealthyLayout(page);
});

test('profile, source, and pipeline controls provide in-flight feedback', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'The complete mutation flow runs once; responsive coverage is separate.');

  await page.goto('/profile');
  const headline = page.getByLabel('Professional headline');
  await headline.fill('Senior platform engineer — QA verified');
  const saveBrief = page.getByRole('button', { name: 'Save search brief' });
  await saveBrief.click();
  await expect(page.getByText('Search brief saved.')).toBeVisible();

  await page.getByRole('tab', { name: /Source material/ }).click();
  await page.getByLabel('Title').fill(`QA evidence ${Date.now()}`);
  await page.getByLabel('Or paste text').fill('Built reliable Python and Django services using PostgreSQL, Redis, and Celery. Improved deployment recovery time by 40 percent.');
  const extract = page.getByRole('button', { name: 'Extract profile facts' });
  await extract.click();
  await expect(page.getByRole('button', { name: /Extracting facts/ })).toBeDisabled();
  await expect(page.locator('.global-work')).toBeVisible();
  await expect(page.getByText(/Profile source ready/)).toBeVisible({ timeout: 60_000 });

  await page.goto('/sources');
  const firstRun = page.getByRole('button', { name: 'Run', exact: true }).first();
  await firstRun.click();
  await expect(page.getByRole('button', { name: /Running/ }).first()).toBeDisabled();
  await expect(page.getByText(/refresh finished/i)).toBeVisible({ timeout: 30_000 });

  await page.goto('/pipeline');
  const firstApplication = page.locator('.application-card').first();
  await expect(firstApplication).toBeVisible();
  await firstApplication.click();
  await page.getByLabel('Notes').fill('QA checked from the browser workflow.');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Application saved.')).toBeVisible();
});

test('concierge chat routes a request and returns a specialist response', async ({ page }, testInfo) => {
  await page.goto('/concierge');
  const created = page.waitForResponse((response) => response.request().method() === 'POST' && /\/api\/conversations\/$/.test(response.url()));
  await page.getByRole('button', { name: /New conversation/ }).click();
  expect((await created).ok()).toBeTruthy();
  const messages = page.locator('.chat-message:not(.thinking)');
  await expect(messages).toHaveCount(0);
  const prompt = 'Give me the top one please';
  await page.getByPlaceholder(/Ask about your profile/).fill(prompt);
  await page.getByRole('button', { name: 'Send →' }).click();
  await expect(page.getByRole('status')).toContainText(/is working/);
  await expect(messages).toHaveCount(2, { timeout: 60_000 });
  await expect(page.getByRole('status')).toBeHidden();
  await expect(page.locator('.chat-message:not(.user-message) .message-copy').last()).toContainText('Top recommendation');
  await expect(page.getByRole('link', { name: /Review full match/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /Prepare application materials/ })).toBeVisible();

  const userMessage = page.locator('.chat-message.user-message').filter({ hasText: prompt }).last();
  const bounds = await userMessage.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.width).toBeGreaterThan(testInfo.project.name === 'mobile' ? 180 : 240);
  if (testInfo.project.name === 'desktop') expect(bounds!.x).toBeGreaterThan(400);
  await assertHealthyLayout(page);
});

test('job import, scoring, approval, tailoring, and final PDF flow works', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'The expensive end-to-end workflow runs once.');
  const marker = Date.now();
  const title = `Senior Reliability Engineer QA ${marker}`;

  await page.goto('/matches');
  await page.getByRole('button', { name: /Import a job/ }).first().click();
  await page.getByLabel('Job URL').fill(`https://example.com/jobs/${marker}`);
  await page.getByLabel('Job description').fill(`${title}\nNorthstar QA\nRemote Canada\nWe need a senior engineer with Python, Django, PostgreSQL, Redis, Celery, Docker, API design, and observability experience. Build reliable asynchronous platform services. Salary CAD 175000.`);
  await page.getByRole('button', { name: 'Extract and rank' }).click();
  await expect(page.getByRole('button', { name: /Extracting and ranking/ })).toBeDisabled();
  await expect(page.getByRole('heading', { name: title })).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('.signal-breakdown > div')).toHaveCount(5);

  await page.getByRole('button', { name: /Approve to prepare/ }).click();
  await expect(page.getByText(/Approval requested/)).toBeVisible({ timeout: 30_000 });
  await page.goto('/concierge');
  const approval = page.locator('.approval-card').filter({ hasText: title }).first();
  await expect(approval).toBeVisible({ timeout: 30_000 });
  await approval.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(approval.getByRole('button', { name: /Preparing materials/ })).toBeDisabled();
  await expect(approval).toBeHidden({ timeout: 90_000 });

  await page.goto('/resume-lab');
  const draftResume = page.locator('.job-row').filter({ hasText: title }).filter({ hasText: 'Tailored Resume' }).first();
  await expect(draftResume).toBeVisible({ timeout: 30_000 });
  await draftResume.click();
  await expect(page.getByText('AI designed', { exact: false })).toBeVisible();
  await expect(page.locator('.resume-paper')).toBeVisible();
  await expect(page.locator('.resume-paper h1')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('ai-designed-resume.png'), fullPage: true });
  const directPdf = page.waitForEvent('download');
  await page.getByRole('button', { name: /Download PDF/ }).click();
  expect((await directPdf).suggestedFilename()).toMatch(/\.pdf$/);
  const approveResume = page.getByRole('button', { name: /Approve draft/ });
  await expect(approveResume).toBeVisible();
  const resumeRisk = page.getByLabel(/I reviewed the unsupported claims/).first();
  if (await resumeRisk.isVisible()) await resumeRisk.check();
  await approveResume.click();
  await expect(approveResume).toBeHidden();

  const coverSection = page.locator('.job-row').filter({ hasText: 'Cover Letter' }).filter({ hasText: title }).first();
  await expect(coverSection).toBeVisible();
  await coverSection.click();
  const approveLetter = page.getByRole('button', { name: /Approve cover letter/ });
  await expect(approveLetter).toBeVisible();
  const letterRisk = page.getByLabel(/I reviewed the unsupported claims/).first();
  if (await letterRisk.isVisible()) await letterRisk.check();
  await approveLetter.click();
  await expect(approveLetter).toBeHidden();

  await page.goto('/pipeline');
  await page.locator('.application-card').filter({ hasText: title }).click();
  await page.getByRole('button', { name: 'Render PDF bundle' }).click();
  await expect(page.getByText(/approval is waiting/i)).toBeVisible();
  await page.goto('/concierge');
  const renderApproval = page.locator('.approval-card').filter({ hasText: 'Render final PDF bundle' }).first();
  await renderApproval.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(renderApproval.getByRole('button', { name: /Rendering PDFs/ })).toBeDisabled();
  await expect(renderApproval).toBeHidden({ timeout: 90_000 });

  await page.goto('/pipeline');
  await page.locator('.application-card').filter({ hasText: title }).click();
  const finalArtifact = page.locator('.material-downloads article').filter({ has: page.getByRole('button', { name: 'Download', exact: true }) }).filter({ hasText: title }).first();
  await expect(finalArtifact).toBeVisible({ timeout: 30_000 });
  const download = page.waitForResponse((response) => /\/api\/artifacts\/\d+\/download\/$/.test(response.url()));
  await finalArtifact.getByRole('button', { name: 'Download', exact: true }).click();
  expect((await download).status()).toBe(200);
});
