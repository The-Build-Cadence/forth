import { expect, test } from '@playwright/test';

// These journeys use their own account, never the operator's workspace.
let tokens: {access: string; refresh: string};
const password = 'Forth-test-account-2026-secure';
test.beforeAll(async ({request}, info) => {
  const email = `browser.${info.project.name}.${Date.now()}@example.com`;
  const created = await request.post('/api/auth/signup/', {data: {email, password}});
  expect(created.status()).toBe(201);
  tokens = await created.json();
  const setup = await request.post('/api/start/', {headers: {Authorization:`Bearer ${tokens.access}`}, data: {intent:'apply', target_roles:['Platform Engineer'], location:'Toronto, Canada', work_modes:['remote'], authorized_countries:['Canada'], daily:false}});
  expect(setup.ok()).toBeTruthy();
});
test.beforeEach(async ({page}) => {
  await page.addInitScript(tokens => {localStorage.setItem('forth_access', tokens.access); localStorage.setItem('forth_refresh', tokens.refresh);}, tokens);
});
test.afterAll(async ({request}) => {
  if (tokens) {
    const removed = await request.post('/api/account/delete/', {headers: {Authorization:`Bearer ${tokens.access}`}, data:{password, confirmation:'DELETE'}});
    expect(removed.status()).toBe(204);
  }
});

test('all workspace screens render with no errors or horizontal overflow', async ({page}, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  for (const path of ['/dashboard','/start','/matches','/pipeline','/resume-lab','/profile','/sources','/settings','/concierge']) {
    await page.goto(path);
    await expect(page.locator('main.app-main h1').first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth), path).toBeLessThanOrEqual(1);
    await page.screenshot({path: info.outputPath(`${path.slice(1)}.png`), fullPage:true});
  }
  expect(errors).toEqual([]);
});

test('mobile navigation closes after selecting a destination', async ({page}, info) => {
  test.skip(info.project.name === 'desktop', 'Mobile and tablet navigation only.');
  await page.goto('/dashboard');
  await page.getByRole('button',{name:'Toggle navigation'}).click();
  await page.getByRole('link',{name:/Jobs$/}).click();
  await expect(page).toHaveURL(/\/matches$/);
  await expect(page.locator('.side-nav')).not.toHaveClass(/open/);
});

test('saved setup resumes across reload without starting a search', async ({page}) => {
  await page.goto('/start');
  await page.getByLabel('Target roles').fill('Senior Platform Engineer');
  await page.getByRole('button',{name:'Save & finish later'}).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto('/start');
  await expect(page.getByLabel('Target roles')).toHaveValue('Senior Platform Engineer');
});

test('real job import creates a match and an application owned by the test user', async ({page}, info) => {
  test.skip(info.project.name !== 'desktop', 'Provider-backed import is verified once.');
  test.setTimeout(180000);
  await page.goto('/matches?tab=import');
  await page.getByLabel('Job description').fill('Platform Engineer\nExample QA Company\nToronto, Canada. Remote. Build Python and Django services with PostgreSQL. Full-time role. Applicants must be authorized to work in Canada.');
  await page.getByRole('button',{name:'Check this job’s fit'}).click();
  await expect(page.getByRole('link',{name:'Open job workspace →'})).toBeVisible({timeout:90000});
  await page.getByRole('link',{name:'Open job workspace →'}).click();
  await page.getByRole('button',{name:'Save job',exact:true}).click();
  await page.getByRole('button',{name:'Prepare documents',exact:true}).first().click();
  await expect(page.getByRole('status')).toContainText('Add your resume or career experience');
  await page.getByRole('link',{name:'My applications',exact:true}).click();
  await expect(page).toHaveURL(/\/pipeline$/);
  await expect(page.locator('.application-card').first()).toBeVisible();
});
