const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const { Subject } = require('rxjs');

function fixture() {
  const values = new Map([['forth_access', 'alice-access'], ['forth_refresh', 'alice-refresh']]);
  const storage = { getItem: key => values.get(key) || null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
  const pending = [];
  const http = { post: () => { const result = new Subject(); pending.push(result); return result; } };
  let storageListener;
  let reloads = 0;
  const exports = {};
  const source = ts.transpileModule(fs.readFileSync('src/app/services/auth.service.ts', 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, experimentalDecorators: true },
  }).outputText;
  vm.runInNewContext(source, {
    exports, localStorage: storage, sessionStorage: storage,
    window: { addEventListener: (_, fn) => storageListener = fn, location: { reload: () => reloads++ } },
    require: name => {
      if (name === '@angular/core') return { Injectable: () => cls => cls };
      if (name === '@angular/common/http') return {};
      if (name.includes('environments/environment')) return { environment: { apiBaseUrl: '/api' } };
      return require(name);
    },
  });
  return { auth: new exports.AuthService(http), storage, pending, storageEvent: event => storageListener(event), reloads: () => reloads };
}

test('a late refresh cannot restore an account after logout', () => {
  const f = fixture();
  let error;
  f.auth.refresh().subscribe({ error: value => error = value });
  f.auth.logout();
  f.pending[0].next({ access: 'late-alice-token' });
  assert.match(error.message, /Session changed/);
  assert.equal(f.auth.getAccessToken(), '');
  assert.equal(f.auth.hasSession(), false);
});

test('an old refresh cannot replace a newly signed-in account', () => {
  const f = fixture();
  let error;
  f.auth.refresh().subscribe({ error: value => error = value });
  f.auth.logout();
  f.auth.login('bob@example.com', 'password').subscribe();
  f.pending[1].next({ access: 'bob-access', refresh: 'bob-refresh' });
  f.pending[0].next({ access: 'late-alice-token' });
  assert.match(error.message, /Session changed/);
  assert.equal(f.auth.getAccessToken(), 'bob-access');
  assert.equal(f.auth.getRefreshToken(), 'bob-refresh');
});

test('switching the account in another tab clears this tab by reloading', () => {
  const f = fixture();
  f.storageEvent({ key: 'forth_access' });
  assert.equal(f.reloads(), 0);
  f.storageEvent({ key: 'forth_refresh' });
  assert.equal(f.reloads(), 1);
});
