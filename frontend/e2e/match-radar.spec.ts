import { expect, test } from '@playwright/test';

const dimensions = [
  ['skills', 'Required and preferred capabilities', 90, 20, 'Nine of ten required capabilities are supported.'],
  ['evidence', 'Experience evidence', 65, 15, 'Four verified facts support this role.'],
  ['semantic', 'Whole-profile semantic fit', 80, 35, 'Your profile is closely aligned with the posting.'],
  ['direction', 'Role direction', 100, 15, 'This role matches your stated target roles.'],
  ['domain', 'Domain relevance', 25, 5, 'Limited evidence in this industry.'],
  ['logistics', 'Logistics', 0, 10, 'The location does not match your preferences.'],
];
const signals = dimensions.map(([kind, label, score, weight, explanation], index) => ({ id: index + 1, kind, label, score, weight, explanation, evidence: [] }));
const job = (id: number, title: string, matchSignals: unknown) => ({
  id, title, company: 'Example Labs', location: 'Toronto', remote_policy: 'remote',
  discovered_at: '2026-10-13T12:00:00Z', application: null,
  match: { score: 72, normalized_score: 85, confidence: 'medium', signals: matchSignals, explanation_json: { summary: 'Strong technical fit with a logistics gap.' }, supporting_facts: [], missing_requirements: [], hard_filter_status: 'uncertain' },
});

test('spider chart shows actual scores, axis details, updates, and missing data', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    localStorage.setItem('forth_access', 'radar-ui-test');
    sessionStorage.setItem('forth_onboarding_dismissed', '1');
  });
  const jobs = [job(1, 'Platform Engineer', [...signals].reverse()), job(2, 'Data Engineer', signals.map(signal => ({ ...signal, score: 50 }))), job(3, 'Unscored Engineer', []), job(4, 'Partial Engineer', signals.slice(0, 4).map((signal, i) => ({ ...signal, score: i === 0 ? null : signal.score })))];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const detail = path.match(/\/jobs\/(\d+)\/$/);
    return route.fulfill({ json: detail ? jobs.find(item => item.id === Number(detail[1])) : { count: jobs.length, results: jobs } });
  });
  await page.goto('/matches');
  const chart = page.locator('app-match-radar');
  await expect(chart.getByRole('group')).toHaveAccessibleName('Match dimension spider chart for Platform Engineer');
  await expect(chart.locator('.radar-axis')).toHaveCount(6);
  await expect(chart.locator('.radar-axis').first()).toHaveAccessibleName(/Required and preferred capabilities: 90 out of 100/);
  const firstShape = await chart.locator('.radar-area').getAttribute('points');
  const coordinates = firstShape!.split(' ').map(point => point.split(',').map(Number));
  expect(coordinates[0][0]).toBeCloseTo(180);
  expect(coordinates[0][1]).toBeCloseTo(156 - 88 * .9);
  expect(coordinates[5]).toEqual([180, 156]); // Zero is a real score, not missing data.
  const domainAxis = chart.getByRole('button', { name: 'Domain relevance: 25 out of 100, 5% weight' });
  await domainAxis.focus();
  await domainAxis.press('Enter');
  await expect(chart.locator('.radar-detail')).toContainText('Limited evidence in this industry.');
  await expect(domainAxis).toHaveAttribute('aria-pressed', 'true');
  await chart.getByRole('button', { name: 'Experience evidence: 65 out of 100, 15% weight' }).click();
  await expect(chart.locator('.radar-detail')).toContainText('Four verified facts');
  await chart.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('match-radar.png'), fullPage: true });
  const widths = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport + 1);
  await page.getByRole('button', { name: /Data Engineer Example Labs/ }).click();
  await expect(chart.getByRole('group')).toHaveAccessibleName('Match dimension spider chart for Data Engineer');
  await expect(chart.locator('.radar-area')).not.toHaveAttribute('points', firstShape!);
  await expect(chart.locator('.radar-detail')).toContainText('50/100');
  await page.getByRole('button', { name: /Partial Engineer Example Labs/ }).click();
  await expect(chart.locator('.radar-axis')).toHaveCount(3);
  await expect(chart.locator('.radar-missing')).toContainText('3 unavailable dimensions are omitted');
  await page.getByRole('button', { name: /Unscored Engineer Example Labs/ }).click();
  await expect(chart.locator('svg')).toHaveCount(0);
  await expect(chart).toContainText('At least three scored dimensions are needed');
});
