import { expect, test } from '@playwright/test';

test('gaps can be dragged or selected, removed, and sent for review', async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem('forth_access', 'gap-test'); sessionStorage.setItem('forth_onboarding_dismissed', '1'); });
  const job = {id:7,title:'Platform engineer',company:'Example',remote_policy:'remote',generation_instructions:null,match:{score:70, normalized_score:70,hard_filter_status:'pass',missing_requirements:['REST APIs'],explanation_json:{covered_skills:['Django']},supporting_facts:[{fact_id:12,title:'Platform delivery',statement:'Built services using Django.'}],signals:[]}};
  let submitted: any;
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/profile_improvements/')) {
      submitted = route.request().postDataJSON();
      return route.fulfill({json:{id:4,job:7,job_title:job.title,suggestions:[{id:'suggestion',fact_id:12,fact_title:'Platform delivery',current_statement:'Built services using Django.',proposed_statement:'Built services using Django. Additional experience: REST APIs.',target_requirements:['REST APIs']}],status:'pending'}});
    }
    if(path === '/api/jobs/7/') return route.fulfill({json:job});
    if(path === '/api/jobs/') return route.fulfill({json:{count:1,results:[job]}});
    if(path === '/api/usage/') return route.fulfill({status:503,json:{}});
    return route.fulfill({json:{count:0,results:[]}});
  });
  await page.goto('/matches?job=7');
  const gap = page.getByRole('button',{name:'REST APIs',exact:true});
  const evidence = page.locator('[data-gap-fact="12"]');
  await gap.scrollIntoViewIfNeeded();
  // Desktop uses the real pointer path; narrow screens use the equivalent tap flow.
  if (test.info().project.name === 'desktop') {
    await evidence.scrollIntoViewIfNeeded();
    const from = await gap.boundingBox(); const to = await evidence.boundingBox();
    expect(from).toBeTruthy(); expect(to).toBeTruthy();
    await page.mouse.move(from!.x + 15, from!.y + 10);
    await page.mouse.down();
    await page.mouse.move(to!.x + 40, to!.y + 25, {steps:12});
    await page.mouse.up();
  } else {
    await gap.click();
    await page.getByRole('button',{name:'Link selected gap to Platform delivery'}).click();
  }
  const remove = page.getByRole('button',{name:'Remove REST APIs from Platform delivery'});
  await expect(remove).toBeVisible();
  await remove.click();
  await expect(remove).toHaveCount(0);
  await gap.focus(); await page.keyboard.press('Enter');
  await page.getByRole('button',{name:'Link selected gap to Platform delivery'}).click();
  await page.getByRole('button',{name:'Strengthen profile'}).click();
  await expect(page.getByRole('heading',{name:'Review suggested changes'})).toBeVisible();
  expect(submitted.gap_links).toEqual([{fact_id:12,gap:'REST APIs'}]);
  await expect(page.getByText('Built services using Django. Additional experience: REST APIs.',{exact:true})).toBeVisible();
});
