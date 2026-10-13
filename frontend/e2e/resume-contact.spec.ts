import { expect, test } from '@playwright/test';

test('resume contact settings save, reload, and expose individual inclusion choices', async ({ page }, testInfo) => {
  let contact: Record<string, unknown> = {};
  let rejectSave = false;
  await page.addInitScript(() => {
    localStorage.setItem('forth_access', 'contact-ui-test');
    sessionStorage.setItem('forth_onboarding_dismissed', '1');
  });
  await page.route('**/api/**', async route => {
    if (new URL(route.request().url()).pathname === '/api/profile/') {
      if (route.request().method() === 'PATCH') {
        if (rejectSave) return route.fulfill({ status: 400, json: { resume_contact: { linkedin_url: ['Enter an HTTPS LinkedIn profile URL.'] } } });
        contact = route.request().postDataJSON().resume_contact;
      }
      return route.fulfill({ json: { resume_contact: contact } });
    }
    return route.fulfill({ json: { count: 0, results: [] } });
  });
  await page.goto('/resume-lab');
  await page.getByRole('tab', { name: 'Contact details' }).click();
  await page.getByLabel('Phone number', { exact: true }).fill('+1 (416) 555-0123');
  await page.getByLabel('Email address', { exact: true }).fill('alex@example.com');
  await page.getByLabel('LinkedIn profile URL', { exact: true }).fill('https://www.linkedin.com/in/alex-example/');
  await page.getByLabel('Include phone on new resumes').uncheck();
  await page.getByRole('button', { name: 'Save contact settings' }).click();
  await expect(page.getByRole('status')).toContainText('Contact settings saved');
  expect(contact).toEqual({ phone: '+1 (416) 555-0123', email: 'alex@example.com', linkedin_url: 'https://www.linkedin.com/in/alex-example/', include_phone: false, include_email: true, include_linkedin: true });
  await page.reload();
  await page.getByRole('tab', { name: 'Contact details' }).click();
  await expect(page.getByLabel('Phone number', { exact: true })).toHaveValue('+1 (416) 555-0123');
  await expect(page.getByLabel('Include phone on new resumes')).not.toBeChecked();
  await expect(page.getByLabel('Include email on new resumes')).toBeChecked();
  const widths = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport + 1);
  await page.screenshot({ path: testInfo.outputPath('resume-contact.png'), fullPage: true });
  rejectSave = true;
  await page.getByLabel('LinkedIn profile URL', { exact: true }).fill('https://example.com');
  await page.getByRole('button', { name: 'Save contact settings' }).click();
  await expect(page.getByRole('alert')).toContainText('Enter an HTTPS LinkedIn profile URL.');
  await expect(page.getByRole('button', { name: 'Save contact settings' })).toBeEnabled();
});
