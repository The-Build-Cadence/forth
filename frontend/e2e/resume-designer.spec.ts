import { expect, test } from '@playwright/test';

test('existing resumes can preview saved instructions and save a new design without regeneration', async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem('forth_access', 'design-test'); sessionStorage.setItem('forth_onboarding_dismissed','1'); });
  let design = {template:'modern', layout:'single', font:'sans', density:'balanced', page_size:'Letter', accent:'#177d69', max_pages:0,rationale:''};
  let resume = {id:8,kind:'tailored',title:'Marketing leader',target_job:7,target_job_title:'Marketing director',content_markdown:'# Candidate\n## Experience\nLed a marketing team.',content_json:{design},validation:{},claims:[],approved:true};
  const submitted: any[] = [];
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/resumes/8/design/') {
      const payload = route.request().method() === 'POST' ? route.request().postDataJSON() : {};
      submitted.push(payload);
      let preview = {...design,...payload.design};
      if(payload.use_saved_instructions) preview = {...preview,template:'minimal',layout:'two_column',font:'humanist',accent:'#17324D',max_pages:2};
      if(payload.save) { design = preview; resume = {...resume,content_json:{design},approved:false}; }
      return route.fulfill({json:{design:preview,resume,html:`<!doctype html><html><body><h1>Candidate</h1><main style="column-count:${preview.layout === 'two_column' ? 2 : 1};color:${preview.accent}"><h2>Experience</h2><p>Led a marketing team.</p></main></body></html>`}});
    }
    if(path === '/api/resumes/') return route.fulfill({json:{count:1,results:new URL(route.request().url()).searchParams.get('kind') === 'canonical' ? [] : [resume]}});
    if(path === '/api/usage/') return route.fulfill({status:503,json:{}});
    return route.fulfill({json:{count:0,results:[],resume_contact:{},generation_instructions:''}});
  });
  await page.goto('/resume-lab');
  await expect(page.getByRole('heading',{name:'Resume designer'})).toBeVisible();
  await expect(page.frameLocator('iframe[title="Designed resume preview"]').getByRole('heading',{name:'Candidate'})).toBeVisible();
  await page.getByRole('button',{name:'Apply saved style instructions'}).click();
  await expect(page.getByRole('combobox',{name:'Layout',exact:true})).toHaveValue('two_column');
  await expect(page.getByLabel('Accent color')).toHaveValue('#17324d');
  await expect(page.getByRole('combobox',{name:'Page limit',exact:true})).toHaveValue('2: 2');
  await expect(page.getByRole('button',{name:'Download PDF'})).toBeDisabled();
  await page.getByRole('combobox',{name:'Font',exact:true}).selectOption('serif');
  await page.getByRole('button',{name:'Save design',exact:true}).click();
  await expect(page.getByRole('button',{name:'Download PDF'})).toBeEnabled();
  expect(submitted.find(payload => payload.save).design).toMatchObject({layout:'two_column',font:'serif',accent:'#17324D',max_pages:2});
  expect(resume.content_markdown).toBe('# Candidate\n## Experience\nLed a marketing team.');
  expect(resume.approved).toBe(false);
});
