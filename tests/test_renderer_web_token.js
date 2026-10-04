'use strict';
// Browser-mode bridges must send the per-launch token; Electron IPC must not use HTTP.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const root = path.join(__dirname, '..');
const renderer = fs.readFileSync(path.join(root, 'desktop/electron/renderer.html'), 'utf8');
const rendererScript = renderer.match(/<script>([\s\S]*?)<\/script>/)[1];
const bridgeSetup = rendererScript.slice(0, rendererScript.indexOf('    const state = {'));
const webSource = fs.readFileSync(path.join(root, 'fluent_ai/web.py'), 'utf8');
const fallbackScript = webSource.match(/HTML = """[\s\S]*?<script>([\s\S]*?)<\/script>/)[1];
const TOKEN = 'launch-token-abc_123';

assert(!/<meta[^>]+fluentai-api-token/.test(renderer), 'static renderer must not embed a token');

function browserContext(fluentAI, token = TOKEN) {
  const requests = [];
  const node = () => ({ value: '', textContent: '', addEventListener() {}, append() {} });
  const document = {
    querySelector(selector) {
      return selector === 'meta[name="fluentai-api-token"]' && token !== null ? { content: token } : null;
    },
    getElementById: node,
    createElement: () => ({ click() {} }),
  };
  const fetch = async (url, options = {}) => {
    requests.push({ url, options });
    return { ok: true, json: async () => ({ ok: true, status: 'ready' }) };
  };
  const window = { fluentAI, setTimeout, clearTimeout };
  const context = vm.createContext({ window, document, fetch, AbortController, console, JSON, Number });
  return { context, requests, window };
}

async function run() {
  {
    const { context, requests, window } = browserContext(undefined);
    vm.runInContext(bridgeSetup, context);
    const skipped = new Set(['requestMediaAccess', 'mediaDiagnostics', 'memoryExport']);
    const names = Object.keys(window.fluentAI).filter((name) => !skipped.has(name));
    assert(names.length >= 20);
    for (const name of names) await window.fluentAI[name]({ language: 'Spanish' });
    assert.equal(requests.length, names.length);
    for (const { url, options } of requests) {
      assert.match(url, /^\/api\/bridge\/[a-z_]+$/);
      assert.equal(options.method, 'POST');
      assert.equal(options.headers['X-FluentAI-Token'], TOKEN, url);
      assert.equal(options.headers['Content-Type'], 'application/json');
      assert.equal(typeof options.body, 'string');
    }
  }
  {
    // Electron preload already defines window.fluentAI: no HTTP bridge, no token needed.
    const ipc = { status: async () => ({ ok: true, source: 'ipc' }) };
    const { context, requests, window } = browserContext(ipc, null);
    vm.runInContext(bridgeSetup, context);
    assert.equal(window.fluentAI, ipc);
    assert.equal((await window.fluentAI.status({})).source, 'ipc');
    assert.equal(requests.length, 0);
  }
  {
    const { context, requests } = browserContext(undefined);
    const listeners = {};
    context.document.getElementById = (id) => ({
      id, value: id === 'turns' ? '2' : '', textContent: '', append() {},
      addEventListener(type, fn) { listeners[id] = fn; },
    });
    context.document.createElement = () => ({ append() {}, textContent: '' });
    vm.runInContext(fallbackScript, context);
    await listeners.lessonBtn();
    await listeners.conversationBtn();
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(requests.map((request) => request.url).sort(), ['/api/conversation', '/api/lesson', '/api/status']);
    for (const { options } of requests) assert.equal(options.headers['X-FluentAI-Token'], TOKEN);
  }
  console.log('renderer web token tests passed');
}

run().catch((error) => { console.error(error); process.exit(1); });
