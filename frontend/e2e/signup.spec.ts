import { expect, test } from '@playwright/test';

test('signup is responsive and clearly leads into profile onboarding', async ({ page }, testInfo) => {
  await page.goto('/signup');
  await expect(page).toHaveTitle(/Forth/);
  await expect(page.getByRole('heading', { name: 'Let’s get your search moving' })).toBeVisible();
  await expect(page.getByText(/add your resume and confirm a few search preferences/i)).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.screenshot({ path: testInfo.outputPath('signup.png'), fullPage: true });
});

test('new account is authenticated and handed directly to short setup', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Account creation is covered once; responsive signup rendering runs on every project.');
  const email = `candidate.${Date.now()}@example.com`;
  const password = 'Move-Forth-Securely-2026';

  await page.goto('/signup');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByLabel('Confirm password').fill(password);
  const registration = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith('/api/auth/signup/'));
  await page.getByRole('button', { name: /Create workspace/ }).click();
  expect((await registration).status()).toBe(201);

  await expect(page).toHaveURL(/\/start$/);
  await expect(page.getByRole('heading', { name: 'What would you like to do first?' })).toBeVisible();
  expect(await page.evaluate(() => Boolean(localStorage.getItem('forth_access') && localStorage.getItem('forth_refresh')))).toBeTruthy();
});

test('signup prevents mismatched passwords before sending a request', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'Client validation is device-independent.');
  await page.goto('/signup');
  await page.getByLabel('Email address').fill('mismatch@example.com');
  await page.getByLabel('Password', { exact: true }).fill('Move-Forth-Securely-2026');
  await page.getByLabel('Confirm password').fill('Different-password-2026');
  await expect(page.getByRole('button', { name: /Create workspace/ })).toBeDisabled();
  await expect(page.getByText('Passwords match')).not.toHaveClass(/met/);
});
