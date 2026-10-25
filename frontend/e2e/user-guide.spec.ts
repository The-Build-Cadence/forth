import { expect, test } from '@playwright/test';

test('standalone user guide is complete, responsive, and navigable', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/forth-user-guide.html');
  await expect(page).toHaveTitle('Forth — User Guide');
  await expect(page.locator('.brand')).toContainText('Forth');
  await expect(page.getByRole('heading', { name: /A calmer path/ })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Guide contents' })).toBeVisible();
  await expect(page.locator('.journey .step')).toHaveCount(9);
  await expect(page.locator('#quick-start')).toContainText('Save & finish later');
  await expect(page.locator('#sourcing')).toContainText('Find jobs for me');

  await page.getByRole('link', { name: 'Progress & statuses' }).click();
  await expect(page.locator('#progress')).toBeInViewport();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('user-guide.png'), fullPage: true });
});
