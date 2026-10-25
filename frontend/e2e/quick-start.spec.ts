import { expect, test } from '@playwright/test';

const profile = {target_roles: [], location: '', authorized_countries: [], work_modes: [], onboarding_state: {}, onboarding_completed_at: null};
async function setup(page: any, available = true) {
  let saved: any = {...profile}; let searches = 0;
  await page.addInitScript(() => {localStorage.setItem('forth_access', 'setup-test'); sessionStorage.setItem('forth_onboarding_dismissed', '1');});
  await page.route('**/api/**', async (route: any) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/start/') {
      if (route.request().method() === 'POST') { const body = route.request().postDataJSON(); saved = {...body, onboarding_state: {intent: body.intent, daily: body.daily}, onboarding_completed_at: '2026-10-19T00:00:00Z'}; }
      return route.fulfill({json: {profile: saved, document: null, discovery_available: available}});
    }
    if (path === '/api/start/discover/') { searches++; return route.fulfill({status: 202, json: {id: 3, status: 'queued'}}); }
    if (path === '/api/today/') return route.fulfill({json: {next_action: {title: 'Finding jobs for you', detail: 'Your search is running.', label: 'View search progress', path: '/sources'}, setup_complete: true, profile_health:{completeness: 10}, review_queue:[]}});
    return route.fulfill({json: {count: 0, results: []}});
  });
  return {saved: () => saved, searches: () => searches};
}
async function preferences(page: any) {
  await page.getByRole('button', {name: 'Start without a resume'}).click();
  await expect(page.getByRole('button', {name: /Find my first matches|Continue to my job|Save & add a job/})).toBeDisabled();
  await page.getByLabel('Target roles').fill('Platform Engineer');
  await page.getByLabel('Where would you like to work?').fill('Toronto, Canada');
  await page.getByLabel('Remote', {exact: true}).check();
}
async function layout(page: any) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
}

test('welcome, recovery and privacy pages are responsive', async ({page}, info) => {
  for (const route of ['/', '/forgot-password', '/privacy']) {
    await page.goto(route); await expect(page.locator('h1')).toBeVisible(); await layout(page);
    await page.screenshot({path: info.outputPath(`public-${route.replaceAll('/', '') || 'welcome'}.png`), fullPage: true});
  }
});

test('find jobs path saves minimal preferences and starts discovery once', async ({page}, info) => {
  const state = await setup(page);
  await page.goto('/start');
  await page.getByRole('button', {name: /Find jobs for me/}).click();
  await preferences(page); await layout(page);
  await page.screenshot({path: info.outputPath('setup-preferences.png'), fullPage:true});
  await page.getByRole('button', {name: 'Find my first matches'}).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', {name: 'Finding jobs for you'})).toBeVisible();
  expect(state.searches()).toBe(1); expect(state.saved().daily).toBe(false);
  expect(state.saved().authorized_countries).toEqual([]);
  await page.goto('/start');
  await expect(page.getByLabel('Target roles')).toHaveValue('Platform Engineer');
});

test('existing job path goes directly to import without a discovery request', async ({page}) => {
  const state = await setup(page);
  await page.goto('/start'); await page.getByRole('button', {name: /Help me apply to a job/}).click();
  await preferences(page); await page.getByRole('button', {name:'Continue to my job'}).click();
  await expect(page).toHaveURL(/matches\?tab=import/);
  await expect(page.getByLabel('Job description')).toBeVisible();
  expect(state.searches()).toBe(0); await layout(page);
});

test('unavailable discovery provides a useful alternative', async ({page}) => {
  const state = await setup(page, false);
  await page.goto('/start'); await page.getByRole('button', {name: /Find jobs for me/}).click();
  await preferences(page);
  await expect(page.getByText(/Automatic search is temporarily unavailable/)).toBeVisible();
  await page.getByRole('button', {name: 'Save & add a job'}).click();
  await expect(page.getByLabel('Job description')).toBeVisible(); expect(state.searches()).toBe(0);
});

test('setup load failure can be retried and search failure keeps preferences', async ({page}) => {
  await setup(page);
  await page.route('**/api/start/', route => route.fulfill({status:503,json:{}}), {times:1});
  await page.goto('/start'); await expect(page.getByRole('alert')).toBeVisible();
  await page.getByRole('button',{name:'Try again',exact:true}).click();
  await page.getByRole('button', {name:/Find jobs for me/}).click(); await preferences(page);
  await page.route('**/api/start/discover/', route => route.fulfill({status:503,json:{detail:'Search could not start. Try again.'}}));
  await page.getByRole('button', {name:'Find my first matches'}).click();
  await expect(page.getByRole('alert')).toContainText('Search could not start');
  await expect(page.getByLabel('Target roles')).toHaveValue('Platform Engineer');
  await expect(page.getByRole('button',{name:'Find my first matches'})).toBeEnabled();
});
