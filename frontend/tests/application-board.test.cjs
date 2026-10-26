const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const exportsForTest = {};
vm.runInNewContext(ts.transpileModule(fs.readFileSync('src/app/services/application-board.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS },
}).outputText, { exports: exportsForTest });
const { applicationBoardStatuses, applicationsInStatus } = exportsForTest;

test('every backend application status has exactly one visible board column', () => {
  const model = fs.readFileSync('../backend/core/models.py', 'utf8').split('class Application(OwnedModel):')[1].split('job = models.ForeignKey')[0];
  const keys = [...model.matchAll(/\('([^']+)', '[^']+'\)/g)].map(match => match[1]);
  const columns = Array.from(applicationBoardStatuses, column => column.key);
  assert.equal(new Set(columns).size, columns.length);
  assert.deepEqual(columns.sort(), keys.sort());
  const records = keys.map((status, id) => ({id, status}));
  const placed = applicationBoardStatuses.flatMap(column => applicationsInStatus(records, column.key));
  assert.equal(placed.length, records.length);
  assert.equal(new Set(placed.map(record => record.id)).size, records.length);
});

test('rejections and each interview stage remain distinct instead of becoming Closed or Interviewing', () => {
  const records = ['rejected', 'archived', 'recruiter_screen', 'technical_screen', 'onsite_final'].map(status => ({status}));
  for (const record of records) {
    const result = applicationsInStatus(records, record.status);
    assert.equal(result.length, 1);
    assert.equal(result[0], record);
  }
});

const { applicationAge } = exportsForTest;
const now = Date.parse('2026-10-26T12:00:00Z');
const aged = (status, days, extra = {}) => applicationAge({status, status_entered_at: new Date(now - days * 86400000).toISOString(), ...extra}, now);
test('stage ages and suggested next actions use elapsed stage time', () => {
  assert.equal(aged('saved', 2.9).action, '');
  assert.equal(aged('saved', 3).action, 'Review next step');
  assert.equal(aged('materials_ready', 2).action, 'Review and apply');
  assert.equal(aged('applied', 7).action, 'Consider follow-up');
  assert.equal(aged('technical_screen', 7).action, 'Check next steps');
  assert.equal(aged('applied', 10).label, '10d in stage');
  assert.equal(aged('saved', -1).label, 'Just entered');
  assert.equal(applicationAge({status: 'saved'}, now).label, 'Age unavailable');
  assert.match(aged('saved', 3, {status_age_estimated: true}).label, /^~/);
});
test('scheduled reminders take priority and closed stages stay neutral', () => {
  assert.equal(aged('applied', 10, {follow_up_at: '2026-11-01T00:00:00Z'}).action, '');
  assert.equal(aged('saved', 1, {follow_up_at: '2026-10-25T00:00:00Z'}).action, 'Follow-up due');
  for (const status of ['rejected', 'archived']) assert.equal(aged(status, 50, {follow_up_at: '2026-10-25T00:00:00Z'}).action, '');
});
