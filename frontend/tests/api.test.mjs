import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

// Executa o módulo real com fetch controlado, sem navegador ou servidor.
const source = readFileSync(new URL('../src/api.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source.replace('import.meta.env', '({})'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function loadApi(fetch, locks) {
  const exports = {};
  vm.runInNewContext(compiled, { exports, fetch, FormData, navigator: { locks } });
  return exports;
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

test('requisições simultâneas com access expirado compartilham uma renovação', async () => {
  const refreshStarted = deferred();
  const releaseRefresh = deferred();
  let refreshes = 0;
  let expiredCalls = 0;
  let logouts = 0;
  const auth = loadApi(async (url, init) => {
    if (url.endsWith('/login/')) return json({ access: 'old' });
    if (url.endsWith('/login/refresh/')) {
      refreshes++;
      refreshStarted.resolve();
      await releaseRefresh.promise;
      return refreshes === 1 ? json({ access: 'new' }) : json({}, 401);
    }
    if (init.headers.Authorization === 'Bearer old') {
      expiredCalls++;
      return json({}, 401);
    }
    assert.equal(init.headers.Authorization, 'Bearer new');
    return json({ ok: true });
  });
  await auth.login('user', 'password');
  const api = auth.apiFactory(() => { logouts++; });
  const requests = Promise.all([api('/leads/'), api('/companies/'), api('/me/')]);
  await refreshStarted.promise;
  assert.equal(expiredCalls, 3);
  releaseRefresh.resolve();
  assert.deepEqual(await requests, [{ ok: true }, { ok: true }, { ok: true }]);
  assert.equal(refreshes, 1);
  assert.equal(logouts, 0);
});

test('401 atrasado reutiliza o access já renovado', async () => {
  const releaseLateResponse = deferred();
  let refreshes = 0;
  const auth = loadApi(async (url, init) => {
    if (url.endsWith('/login/')) return json({ access: 'old' });
    if (url.endsWith('/login/refresh/')) {
      refreshes++;
      return json({ access: 'new' });
    }
    if (init.headers.Authorization === 'Bearer old') {
      if (url.endsWith('/late/')) await releaseLateResponse.promise;
      return json({}, 401);
    }
    assert.equal(init.headers.Authorization, 'Bearer new');
    return json({ ok: true });
  });
  await auth.login('user', 'password');
  const api = auth.apiFactory(() => assert.fail('logout inesperado'));
  const late = api('/late/');
  await api('/fast/');
  releaseLateResponse.resolve();
  await late;
  assert.equal(refreshes, 1);
});

test('login silencioso simultâneo compartilha a renovação e permite futuras renovações', async () => {
  const releaseRefresh = deferred();
  let refreshes = 0;
  const auth = loadApi(async () => {
    refreshes++;
    await releaseRefresh.promise;
    return json({ access: 'new' });
  });
  const first = auth.trySilentLogin();
  const second = auth.trySilentLogin();
  assert.equal(refreshes, 1);
  releaseRefresh.resolve();
  assert.deepEqual(await Promise.all([first, second]), [true, true]);
  assert.equal(await auth.trySilentLogin(), true);
  assert.equal(refreshes, 2);
});

test('abas com Web Locks renovam em sequência usando o cookie atualizado', async () => {
  let queue = Promise.resolve();
  const locks = {
    request(name, callback) {
      assert.equal(name, 'conecta-crm-session-refresh');
      const result = queue.then(callback);
      queue = result.catch(() => {});
      return result;
    },
  };
  const releaseFirstRefresh = deferred();
  const firstRefreshStarted = deferred();
  let cookie = 0;
  let refreshes = 0;
  const fetch = async () => {
    refreshes++;
    const usedCookie = cookie;
    if (refreshes === 1) {
      firstRefreshStarted.resolve();
      await releaseFirstRefresh.promise;
    }
    if (usedCookie !== cookie) return json({}, 401);
    cookie++;
    return json({ access: `access-${cookie}` });
  };
  const first = loadApi(fetch, locks).trySilentLogin();
  const second = loadApi(fetch, locks).trySilentLogin();
  await firstRefreshStarted.promise;
  assert.equal(refreshes, 1);
  releaseFirstRefresh.resolve();
  assert.deepEqual(await Promise.all([first, second]), [true, true]);
  assert.equal(refreshes, 2);
  assert.equal(cookie, 2);
});

test('refresh rejeitado continua encerrando uma sessão expirada', async () => {
  let logouts = 0;
  const auth = loadApi(async () => json({}, 401));
  const api = auth.apiFactory(() => { logouts++; });
  await assert.rejects(api('/me/'), /Sessão expirada/);
  assert.equal(logouts, 1);
  assert.equal(await auth.trySilentLogin(), false);
});
