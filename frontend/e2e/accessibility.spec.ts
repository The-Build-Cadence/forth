import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('public entry screens meet automated WCAG AA checks', async ({page}) => {
  for (const path of ['/', '/signup', '/forgot-password', '/privacy']) {
    await page.goto(path);
    await expect(page.locator('h1')).toBeVisible();
    const result = await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
    expect(result.violations, `${path}: ${JSON.stringify(result.violations.map(v => ({id:v.id, nodes:v.nodes.map(n => ({target:n.target, summary:n.failureSummary}))})))}`).toEqual([]);
  }
});

test('setup choices and preferences have accessible labels and contrast', async ({page}) => {
  await page.addInitScript(() => {localStorage.setItem('forth_access','a11y-test'); sessionStorage.setItem('forth_onboarding_dismissed','1');});
  await page.route('**/api/**', route => route.fulfill({json: new URL(route.request().url()).pathname === '/api/start/' ? {profile:{target_roles:[],location:'',authorized_countries:[],work_modes:[],onboarding_state:{}},document:null,discovery_available:true} : {count:0,results:[]}}));
  await page.goto('/start');
  await expect(page.getByRole('heading',{name:'What would you like to do first?'})).toBeVisible();
  for (let step = 1; step <= 3; step++) {
    const result = await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();
    expect(result.violations, `Step ${step}: ${JSON.stringify(result.violations.map(v => ({id:v.id,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))})))}`).toEqual([]);
    if(step === 1) await page.getByRole('button',{name:/Find jobs for me/}).click();
    if(step === 2) await page.getByRole('button',{name:'Start without a resume'}).click();
  }
});
