import { expect, test, Page } from '@playwright/test';

async function setup(page: Page, failSave = false) {
  const app: any = { id: 1, job: 7, status: 'saved', job_detail: { id: 7, title: 'Platform Engineer', company: 'Example', location: 'Toronto', match: { score: 80 } }, resume: null, resume_title: '', artifact_count: 0, updated_at: '2026-10-16T12:00:00Z', cover_letters: [], artifacts: [], events: [] };
  const changes: string[] = [];
  await page.addInitScript(() => { localStorage.setItem('forth_access', 'drag-test'); sessionStorage.setItem('forth_onboarding_dismissed', '1'); });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/jobs/7/') return route.fulfill({json: {...app.job_detail, application: {id: 1, status: app.status}, document_status: 'not_created'}});
    if (path === '/api/usage/') return route.fulfill({ status: 503, json: {} });
    if (path === '/api/applications/1/') {
      if (route.request().method() === 'PATCH') {
        const status = route.request().postDataJSON().status;
        changes.push(status);
        if (failSave) return route.fulfill({ status: 500, json: { detail: 'Could not save. Try again.' } });
        app.status = status;
      }
      return route.fulfill({ json: app });
    }
    return route.fulfill({ json: { count: 1, results: path === '/api/applications/' ? [app] : [] } });
  });
  await page.goto('/pipeline');
  await expect(page.locator('.application-card')).toBeVisible();
  return changes;
}

async function moveCard(page: Page, target: string) {
  const card = page.locator('.application-card');
  const destination = page.locator('.pipeline-col').filter({ has: page.getByRole('heading', { name: target, exact: true }) });
  await card.dragTo(destination);
}

test('moving an application persists status and leaves the board usable', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const changes = await setup(page);
  await moveCard(page, 'Preparing');
  await expect(page.getByRole('status')).toContainText('moved to Preparing');
  expect(changes).toEqual(['preparing']);
  await moveCard(page, 'Saved');
  await expect(page.getByRole('status')).toContainText('moved to Saved');
  expect(changes).toEqual(['preparing', 'saved']);
  await page.locator('.application-card').click();
  await expect(page).toHaveURL(/\/jobs\/7/);
  expect(errors).toEqual([]);
});

async function beginDrag(page: Page) {
  const card = page.locator('.application-card');
  await card.scrollIntoViewIfNeeded();
  const box = (await card.boundingBox())!;
  const x = box.x + 50, y = box.y + 30;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + 15, y + 15, { steps: 5 });
  await expect(page.locator('.application-drag-preview')).toBeVisible();
}

test('Escape, focus loss, and pointer cancellation release the drag without saving', async ({ page }) => {
  const changes = await setup(page);
  for (const cancel of ['escape', 'blur', 'pointercancel']) {
    await beginDrag(page);
    if (cancel === 'escape') await page.keyboard.press('Escape');
    if (cancel === 'blur') await page.evaluate(() => window.dispatchEvent(new Event('blur')));
    if (cancel === 'pointercancel') await page.locator('.application-card').dispatchEvent('pointercancel');
    await expect(page.locator('.application-drag-preview')).toHaveCount(0);
    await page.mouse.up();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.locator('.pipeline-col.drop-target')).toHaveCount(0);
    await page.locator('.application-card').click();
    await expect(page).toHaveURL(/\/jobs\/7/);
    await page.goto('/pipeline');
  }
  expect(changes).toEqual([]);
});

test('dropping outside the board cancels, and failed saves restore the card', async ({ page }) => {
  const changes = await setup(page, true);
  await beginDrag(page);
  await page.mouse.move(500, 140, { steps: 8 });
  await page.mouse.up();
  await expect(page.locator('.application-drag-preview')).toHaveCount(0);
  expect(changes).toEqual([]);
  await moveCard(page, 'Preparing');
  await expect(page.getByRole('status')).toContainText('Could not save');
  const saved = page.locator('.pipeline-col').filter({ has: page.getByRole('heading', { name: 'Saved', exact: true }) });
  await expect(saved.locator('.application-card')).toBeEnabled();
  await moveCard(page, 'Preparing');
  await expect(page.getByRole('status')).toContainText('Could not save');
  expect(changes).toEqual(['preparing', 'preparing']);
  await page.locator('.application-card').click();
  await expect(page).toHaveURL(/\/jobs\/7/);
});

test('dragging near the viewport edge scrolls to lower stages', async ({ page }) => {
  await page.setViewportSize({width: 820, height: 600});
  await setup(page);
  await beginDrag(page);
  const before = await page.evaluate(() => window.scrollY);
  await page.mouse.move(600, page.viewportSize()!.height - 10, { steps: 8 });
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(before + 100);
  await page.keyboard.press('Escape');
  await page.mouse.up();
  await expect(page.locator('.application-drag-preview')).toHaveCount(0);
});

test('touch dragging uses the handle and saves the destination', async ({ page, isMobile }) => {
  test.skip(!isMobile, 'Touch interaction is tested with mobile emulation.');
  const changes = await setup(page);
  const source = page.locator('.application-card');
  await source.scrollIntoViewIfNeeded();
  const sourceBox = (await source.boundingBox())!;
  await page.evaluate(top => window.scrollBy({ top, behavior: 'instant' }), sourceBox.y - 180);
  const handle = (await source.locator('.card-drag-handle').boundingBox())!;
  const target = (await page.locator('.pipeline-col').filter({ has: page.getByRole('heading', { name: 'Preparing', exact: true }) }).boundingBox())!;
  const client = await page.context().newCDPSession(page);
  const start = { x: handle.x + handle.width / 2, y: handle.y + handle.height / 2 };
  const end = { x: target.x + 60, y: target.y + 50 };
  await client.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [start] });
  for (let i = 1; i <= 10; i++) {
    await client.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: start.x + (end.x - start.x) * i / 10, y: start.y + (end.y - start.y) * i / 10 }] });
  }
  await expect(page.locator('.application-drag-preview')).toBeVisible();
  await client.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await expect(page.getByRole('status')).toContainText('moved to Preparing');
  expect(changes).toEqual(['preparing']);
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('a stalled save times out and unlocks the board', async ({ page }) => {
  await setup(page);
  await page.clock.install();
  await page.route('**/api/applications/1/', async route => {
    if (route.request().method() !== 'PATCH') await route.fallback();
    // Leave PATCH pending to exercise an unresponsive server.
  });
  await moveCard(page, 'Preparing');
  await expect(page.locator('.application-card')).toBeDisabled();
  await page.clock.fastForward(15001);
  await expect(page.getByRole('status')).toContainText('Saving took too long');
  await expect(page.locator('.application-card')).toBeEnabled();
  await page.locator('.application-card').click();
  await expect(page).toHaveURL(/\/jobs\/7/);
});
