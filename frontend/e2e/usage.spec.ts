import { expect, test } from '@playwright/test';

test('account costs show concise totals and unavailable state', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(() => {
    localStorage.setItem('forth_access', 'usage-test');
    sessionStorage.setItem('forth_onboarding_dismissed', '1');
  });
  let unavailable = false;
  await page.route('**/api/**', route => {
    if (new URL(route.request().url()).pathname === '/api/usage/') {
      if (unavailable) return route.fulfill({ status: 503, json: {} });
      const totals = { requests: 20, month_requests: 10, month_cost_usd: '0.005', background_requests: 4, unknown_cost_requests: 0 };
      return route.fulfill({ json: { currency: 'USD', first_request_at: '2026-10-16T12:00:00Z', providers: {
        openai: { ...totals, cost_usd: '0.0006', unknown_cost_requests: 2 },
        brave: { ...totals, cost_usd: '0.1' },
      } } });
    }
    return route.fulfill({ json: { count: 0, results: [] } });
  });
  await page.goto('/pipeline');
  if (await page.getByRole('button', { name: 'Toggle navigation' }).isVisible()) {
    await page.getByRole('button', { name: 'Toggle navigation' }).click();
  }
  const monitor = page.getByRole('region', { name: 'Your API costs' });
  await expect(monitor).toContainText('$0.0006');
  await expect(monitor).toContainText('$0.10');
  await expect(monitor.locator('details')).toHaveCount(0);
  await expect(monitor.locator('.usage-row')).toHaveText(['AI$0.0006', 'Search$0.10']);
  unavailable = true;
  await expect(monitor).toHaveAttribute('title', 'Costs unavailable. Retrying automatically.', { timeout: 20000 });
  await expect(monitor.locator('strong')).toHaveText(['—', '—']);
  expect(errors).toEqual([]);
});
