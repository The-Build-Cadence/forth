import path from 'node:path';
import { expect, test } from '@playwright/test';

test('resume evidence drives a dynamic interview into an actionable candidate profile', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'The complete adaptive mutation flow runs once; responsive rendering is covered by the app suite.');
  test.setTimeout(300_000);
  await page.goto('/signup');
  await page.getByLabel('Email address').fill(`onboarding.${Date.now()}@example.com`);
  await page.getByLabel('Password', { exact: true }).fill('Build-My-Career-Profile-2026');
  await page.getByLabel('Confirm password').fill('Build-My-Career-Profile-2026');
  await page.getByRole('button', { name: /Create workspace/ }).click();
  await expect(page).toHaveURL(/\/start$/);

  await page.goto('/profile');
  await page.getByRole('button', {name: 'Review my experience'}).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Meet your Profile Steward' })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('adaptive-onboarding-welcome.png'), fullPage: true });
  await dialog.getByRole('button', { name: /Start with my resume/ }).click();
  await expect(dialog.getByRole('heading', { name: 'Add your current resume' })).toBeVisible();
  await dialog.locator('input[type="file"]').setInputFiles(path.join(process.cwd(), 'e2e', 'fixtures', 'current-resume.html'));
  await expect(dialog.getByText('current-resume.html')).toBeVisible();
  await dialog.getByRole('button', { name: /Analyze my resume/ }).click();
  await expect(dialog.getByText(/Reading evidence, not just keywords/)).toBeVisible({ timeout: 30_000 });
  await expect(dialog.locator('.dynamic-answer')).toBeVisible({ timeout: 120_000 });
  await expect(dialog.getByText(/Next question is replanned after every answer/)).toBeVisible();
  await expect(dialog.locator('.answer-proposal')).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(dialog.locator('.answer-proposal')).toBeVisible();
  const mobileLayout = await page.evaluate(() => ({ viewport: document.documentElement.clientWidth, document: document.documentElement.scrollWidth }));
  expect(mobileLayout.document).toBeLessThanOrEqual(mobileLayout.viewport + 1);
  await page.screenshot({ path: testInfo.outputPath('adaptive-onboarding-proposal-mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });

  const textAnswers: Record<string, string> = {
    target_roles: 'Staff Platform Engineer, Engineering Lead',
    headline: 'Product-minded platform engineer',
    location: 'Toronto, Canada',
    authorized_countries: 'Canada',
    skill: 'Python, platform architecture, technical leadership',
    achievement: 'Led a reliability program across four teams and reduced deployment recovery time by 40 percent.',
    target_industries: 'Developer tools, AI infrastructure',
    minimum_compensation: '150000',
    professional_summary: 'Product-minded platform engineer who builds dependable systems, leads pragmatic technical decisions, and improves delivery outcomes across teams.',
    experience: 'Staff Platform Engineer at Northstar from 2021 to present, leading platform reliability and architecture across four teams.',
    education: 'Bachelor of Software Engineering, Example University, 2014',
    soft_skills: 'Technical leadership, clear communication, cross-functional collaboration',
    hobbies: 'Mentoring, open-source work, distance running',
  };
  const preferredChoices: Record<string, RegExp> = {
    work_modes: /Remote/i,
    employment_types: /Full-time/i,
    preference_ideal: /High ownership/i,
    preference_avoid: /Always-on culture/i,
  };

  const seenTargets: string[] = [];
  for (let turn = 0; turn < 24; turn += 1) {
    if (await dialog.getByRole('heading', { name: 'Your candidate profile is ready' }).isVisible().catch(() => false)) break;
    const card = dialog.locator('.dynamic-answer');
    await expect(card).toBeVisible({ timeout: 120_000 });
    const target = (await card.getAttribute('data-question-target')) || '';
    const questionId = await card.getAttribute('data-question-id');
    seenTargets.push(target);

    const skip = card.getByRole('button', { name: 'Skip for now' });
    if (['target_industries', 'minimum_compensation', 'preference_avoid'].includes(target) && await skip.isVisible().catch(() => false)) {
      await skip.click();
    } else if (await card.locator('.dynamic-choices').isVisible().catch(() => false)) {
      const preferred = preferredChoices[target];
      const preferredOption = preferred ? card.getByRole('button', { name: preferred }).first() : undefined;
      // The interview plans choices dynamically; use a preferred answer only
      // when it was actually offered rather than waiting on a fixed script.
      const option = preferredOption && await preferredOption.count() ? preferredOption : card.locator('.dynamic-choices button').first();
      if (!((await option.getAttribute('class')) || '').includes('selected')) await option.click();
      await card.getByRole('button', { name: /Save & continue/ }).click();
    } else {
      const field = card.locator('textarea, input').first();
      if (target !== 'fact_confirmation') await field.fill(textAnswers[target] || 'Candidate-confirmed answer with enough specific detail to update the profile accurately.');
      await card.getByRole('button', { name: /continue/ }).click();
    }
    await expect(dialog.locator(`.dynamic-answer[data-question-id="${questionId}"]`)).toBeHidden({ timeout: 120_000 });
    if (turn === 0) {
      await page.reload();
      await page.getByRole('button', {name: 'Review my experience'}).click();
      await expect(dialog.locator('.dynamic-answer')).toBeVisible({ timeout: 120_000 });
      await expect(dialog.locator(`.dynamic-answer[data-question-target="${target}"]`)).toHaveCount(0);
    }
  }

  await expect(dialog.getByRole('heading', { name: 'Your candidate profile is ready' })).toBeVisible();
  await expect(dialog.getByText('No unresolved resume ambiguity')).toBeVisible();
  await expect(dialog.locator('.readiness-ring strong')).toHaveText('100%');
  expect(seenTargets).toContain('target_roles');
  expect(seenTargets).toContain('authorized_countries');
  expect(seenTargets).toContain('preference_ideal');
  await page.screenshot({ path: testInfo.outputPath('adaptive-onboarding-ready.png'), fullPage: true });
  await dialog.getByRole('button', { name: /Activate my job search/ }).click();
  await expect(dialog).toBeHidden();

  await page.goto('/profile');
  await expect(page.getByText('100%', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Professional headline')).toHaveValue('Product-minded platform engineer');
});
