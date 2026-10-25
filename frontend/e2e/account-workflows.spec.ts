import { expect, test, Page } from '@playwright/test';

async function session(page: Page) {
  await page.addInitScript(() => { localStorage.setItem('forth_access', 'workflow-test'); sessionStorage.setItem('forth_onboarding_dismissed', '1'); });
}
const initialConfig = {name: 'Candidate', email: 'candidate@example.com', has_openai_key: false, use_personal_ai: false, text_model: 'gpt-4.1-mini', default_text_model: 'gpt-4.1-mini', embedding_model: 'text-embedding-3-large', reasoning_effort: '', generation_instructions: ''};
const totals = {requests: 2, month_requests: 2, cost_usd: '0.01', month_cost_usd: '0.01', unknown_cost_requests: 0, background_requests: 1};

test('settings saves personal AI choices without retaining the entered key and serves the brand icon', async ({ page }) => {
  await session(page);
  let config = {...initialConfig};
  const changes: any[] = [];
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/account/settings/') {
      if (route.request().method() === 'PATCH') {
        const change = route.request().postDataJSON(); changes.push(change);
        config = {...config, use_personal_ai: !!change.use_personal_ai, text_model: change.text_model || config.text_model, reasoning_effort: change.reasoning_effort || ''};
        config.has_openai_key = change.remove_key ? false : !!change.openai_api_key;
      }
      return route.fulfill({json: config});
    }
    if (path === '/api/usage/') return route.fulfill({json: {currency:'USD', first_request_at:null, providers:{openai:totals, brave:totals}}});
    return route.fulfill({json: {count:0, results:[]}});
  });
  await page.goto('/settings');
  await expect(page.getByRole('heading', {name:'Settings', exact:true})).toBeVisible();
  await page.getByText('Advanced · use your own AI account', {exact:true}).click();
  await page.getByLabel('Use my OpenAI account').check();
  await page.getByLabel('OpenAI API key').fill('sk-example-test-only');
  await page.getByLabel('Text model', {exact:false}).fill('gpt-4.1');
  await page.getByLabel('Reasoning effort').selectOption('');
  await page.getByRole('button', {name:'Save settings', exact:true}).click();
  await expect(page.getByLabel('OpenAI API key')).toHaveValue('');
  expect(changes[0].openai_api_key).toBe('sk-example-test-only');
  expect(changes[0].text_model).toBe('gpt-4.1');
  await page.getByRole('button', {name:'Remove saved key'}).click();
  await expect(page.getByLabel('Use my OpenAI account')).not.toBeChecked();
  await expect(page.getByRole('region', {name:'API cost breakdown'})).toBeVisible();
  const favicon = await page.request.get('/favicon.svg');
  expect(favicon.ok()).toBeTruthy();
  expect(await favicon.text()).toContain('<svg');
});

test('discovery keeps text and stage markers without animation', async ({ page }) => {
  await session(page);
  const run = {id:1, source:1, source_name:'Brave', status:'succeeded', discovered_count:5, imported_count:2, updated_count:1, created_at:'2026-10-16T12:00:00Z', log:[{level:'search',message:'Searched for engineers'},{level:'evaluate',count:3,message:'Shortlisted three roles'},{level:'import',message:'Saved two new opportunities'}]};
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/usage/') return route.fulfill({status:503,json:{}});
    return route.fulfill({json:{count:1, results:path === '/api/source-runs/' ? [run] : []}});
  });
  await page.goto('/sources');
  await expect(page.getByRole('list', {name:'Discovery stages'}).locator('li')).toHaveText(['Search','Check fit','Save','Finished']);
  await expect(page.getByText('Saved two new opportunities')).toBeVisible();
  await expect(page.getByRole('button', {name:'Replay animation'})).toHaveCount(0);
  await expect(page.locator('.discovery-flow, canvas')).toHaveCount(0);
});

test('application questions can be added, drafted and edited', async ({ page }) => {
  await session(page);
  const app: any = {id:1, job:7, status:'saved', application_form_url:'https://example.com/job', form_fields:[], notes:'', job_detail:{id:7,title:'Engineer',company:'Example',match:{score:80}}, resume:null, resume_title:'', resume_detail:null, cover_letters:[], artifacts:[], events:[], updated_at:'2026-10-16T12:00:00Z'};
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/usage/') return route.fulfill({status:503,json:{}});
    if (path === '/api/applications/1/') {
      if (route.request().method() === 'PATCH') Object.assign(app, route.request().postDataJSON());
      return route.fulfill({json:app});
    }
    if (path === '/api/applications/1/prepare_answers/') {
      app.form_fields = app.form_fields.map((field:any) => ({...field,answer:'My Python experience fits this team.',status:'draft',note:'Review before submitting.'}));
      return route.fulfill({json:app});
    }
    return route.fulfill({json:{count:1,results:path === '/api/applications/' ? [app] : []}});
  });
  await page.goto('/pipeline');
  await page.locator('.application-card').click();
  await page.getByLabel('New application question').fill('Why this company?');
  await page.getByRole('button', {name:'Add question', exact:true}).click();
  await page.getByRole('button', {name:'Find fields & draft missing answers'}).click();
  const answer = page.getByRole('textbox', {name:/^Why this company/});
  await expect(answer).toHaveValue('My Python experience fits this team.');
  await answer.fill('My own carefully reviewed answer.');
  await page.getByRole('button', {name:'Save', exact:true}).click();
  await expect(page.getByText('Application saved.', {exact:true})).toBeVisible();
  expect(app.form_fields[0].answer).toBe('My own carefully reviewed answer.');
});
