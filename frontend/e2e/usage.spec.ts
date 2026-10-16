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
    if (new URL(route.request().url()).pathname === '/api/account/settings/') return route.fulfill({json: {name: 'Candidate', email: 'candidate@example.com', text_model: 'gpt-4.1-mini', default_text_model: 'gpt-4.1-mini', embedding_model: 'text-embedding-3-large', has_openai_key: false, use_personal_ai: false, reasoning_effort: '', generation_instructions: ''}});
    return route.fulfill({ json: { count: 0, results: [] } });
  });
  await page.goto('/pipeline');
  if (await page.getByRole('button', { name: 'Toggle navigation' }).isVisible()) {
    await page.getByRole('button', { name: 'Toggle navigation' }).click();
  }
  const link = page.getByRole('link', { name: 'API costs' });
  await expect(link).toContainText('$0.1006');
  await link.click();
  await expect(page).toHaveURL(/settings#api-costs$/);
  const monitor = page.getByRole('region', { name: 'API cost breakdown' });
  await expect(monitor).toBeInViewport();
  await expect(monitor.locator('.grand-total')).toHaveText('$0.1006');
  await expect(monitor.locator('.cost-item strong')).toHaveText(['$0.0006', '$0.10', '$0.01']);
  await expect(monitor).toContainText('2 requests have pending or unknown costs');
  unavailable = true;
  await expect(monitor).toContainText('Costs unavailable', { timeout: 20000 });
  await expect(monitor.locator('.grand-total')).toHaveText('—');
  expect(errors).toEqual([]);
});
