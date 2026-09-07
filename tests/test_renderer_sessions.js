'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const html = fs.readFileSync(path.join(__dirname, '../desktop/electron/renderer.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
// Compile the entire shipped inline script; exercise its functions with only browser/provider edges mocked.
new vm.Script(script);
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }
function harness() {
  const elements = new Map();
  const node = () => ({ listeners: {}, value: '', disabled: false, textContent: '', style: {}, classList: { toggle() {}, add() {}, remove() {} }, replaceChildren() {}, append() {}, prepend() {}, addEventListener(type, fn) { this.listeners[type] = fn; }, querySelector() { return null; }, pause() {}, play() { return Promise.resolve(); }, focus() {} });
  const document = { getElementById(id) { if (!elements.has(id)) elements.set(id, node()); return elements.get(id); }, createElement: node, querySelector() { return elements.get('submit'); }, addEventListener() {} };
  const timers = new Map(); let timerId = 0;
  const window = { listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; }, close() {}, fluentAI: {}, setTimeout(fn) { timers.set(++timerId, fn); return timerId; }, clearTimeout(id) { timers.delete(id); }, setInterval() {}, clearInterval() {}, prompt() { return 'DELETE ALL MEMORY'; } };
  const context = vm.createContext({ window, document, crypto: { randomUUID }, console, Date, setTimeout, clearTimeout, Uint8ClampedArray, navigator: {} });
  const body = script.slice(0, script.lastIndexOf('    updateVideoPreview();\n    syncAgentLogPanel();'));
  vm.runInContext(body + `\n globalThis.api = { state, els, setMode, endRealtimeCall, submitQuiz, deleteAllMemory, analyzeVisionInBackground, analyzeCurrentCameraFrame, cameraFrameChanged, resetVisionCapture, queueCallCheckpoint, queueLessonCheckpoint, startRealtimeCall, startLesson, startConversation, capturedCallPayload };\nrenderCallMedia = renderChat = appendLogs = showError = () => {};\nrenderProfile = p => { state.profile = p; };\nloadHomeSummary = initOnboarding = refreshStatus = async () => {};\nupdateLanguageCopy = () => {};\nrenderQuizResults = () => {};\nlessonAnswers = () => ['hola'];`, context);
  const api = context.api;
  api.state.profile = { language: 'Spanish', memory_generation: 'epoch-1' };
  api.els.languageSelect.value = 'Spanish';
  elements.set('submit', node());
  return { ...api, context, bridge: window.fluentAI, timers, elements, window };
}
function live(h) {
  h.state.mode = 'conversation'; h.state.callActive = true;
  h.state.realtimeIdentity = Object.freeze({ session_id: 'call-1', language: 'Spanish', memory_generation: 'epoch-1' });
  h.state.realtimeTurns = [{ learner_text: 'hola', tutor_text: 'hi' }];
  h.state.realtimeTopic = { topic: 'greetings' };
}
async function run() {
  {
    const h = harness(); live(h); const pending = deferred(); const calls = [];
    h.bridge.callCheckpoint = async p => { calls.push(['checkpoint', p]); return { ok: true }; };
    h.bridge.endConversation = p => { calls.push(['end', p]); return pending.promise; };
    h.bridge.discardCallCheckpoint = async p => { calls.push(['discard', p]); return { ok: true }; };
    h.els.languageSelect.value = 'French';
    const navigation = h.setMode('home');
    await Promise.resolve();
    const secondEnd = h.endRealtimeCall();
    assert.equal(h.state.mode, 'conversation');
    assert.equal(h.state.callActive, false, 'transport closes before persistence');
    assert.equal(h.state.realtimeTurns.length, 1);
    pending.resolve({ ok: true });
    assert.equal(await navigation, true); assert.equal(await secondEnd, true);
    assert.equal(h.state.mode, 'home');
    assert.equal(calls.filter(c => c[0] === 'end').length, 1, 'concurrent exits share one commit');
    for (const [, p] of calls) { assert.equal(p.language, 'Spanish'); assert.equal(p.session_id, 'call-1'); assert.equal(p.memory_generation, 'epoch-1'); }
    assert.equal(h.state.realtimeTurns.length, 0);
  }
  {
    const h = harness(); live(h); let discards = 0; let attempts = 0;
    h.bridge.callCheckpoint = async () => ({ ok: true });
    h.bridge.endConversation = async () => (++attempts === 1 ? { ok: false, error: 'offline' } : { ok: true });
    h.bridge.discardCallCheckpoint = async () => { discards++; };
    assert.equal(await h.setMode('lesson'), false);
    assert.equal(h.state.mode, 'conversation'); assert.equal(h.state.realtimeTurns.length, 1); assert.equal(discards, 0);
    assert.equal(await h.setMode('lesson'), true); assert.equal(discards, 1);
  }
  {
    const h = harness(); const pending = deferred(); let submissions = 0;
    h.state.lessonSession = { lesson: { language: 'Spanish', session_id: 'lesson-1', memory_generation: 'epoch-1' }, quiz: [] };
    h.bridge.submitLesson = p => { submissions++; assert.equal(p.lesson.session_id, 'lesson-1'); return pending.promise; };
    const first = h.submitQuiz({ preventDefault() {} });
    await h.submitQuiz({ preventDefault() {} });
    assert.equal(submissions, 1); assert.equal(h.elements.get('submit').disabled, true);
    pending.resolve({ ok: true, profile: h.state.profile, results: [], summary: { score: 1 } }); await first;
    await h.submitQuiz({ preventDefault() {} }); assert.equal(submissions, 1); assert.equal(h.state.lessonSession.completed, true); assert.equal(h.elements.get('submit').disabled, true);
  }
  {
    const h = harness(); let count = 0;
    h.state.lessonSession = { lesson: { language: 'Spanish' }, quiz: [] };
    h.bridge.submitLesson = async () => { count++; return { ok: false }; };
    await h.submitQuiz({ preventDefault() {} }); await h.submitQuiz({ preventDefault() {} });
    assert.equal(count, 2, 'failed submissions remain retryable'); assert.equal(h.elements.get('submit').disabled, false);
  }
  {
    const h = harness(); live(h); const pending = deferred();
    h.state.lessonSession = { lesson: {}, quiz: [] };
    h.queueCallCheckpoint(); h.queueLessonCheckpoint(); assert.equal(h.timers.size, 2);
    h.bridge.callCheckpoint = async () => ({ ok: true });
    h.bridge.endConversation = () => pending.promise;
    const ending = h.endRealtimeCall(); await Promise.resolve();
    h.bridge.memoryDeleteAll = async () => ({ ok: true, profile: { memory_generation: 'epoch-2' } });
    await h.deleteAllMemory(); assert.equal(h.timers.size, 0);
    pending.resolve({ ok: true, profile: { memory_generation: 'epoch-1' }, post_call_summary: { private: 'old' } });
    await ending; assert.equal(h.state.profile.memory_generation, 'epoch-2'); assert.equal(h.state.postCallSummary, null); assert.equal(h.state.realtimeIdentity, null); assert.equal(h.state.lessonSession, null);
  }
  {
    const h = harness(); const pending = deferred();
    h.state.lessonSession = { lesson: {}, quiz: [] };
    h.bridge.submitLesson = () => pending.promise;
    const grading = h.submitQuiz({ preventDefault() {} });
    h.bridge.memoryDeleteAll = async () => ({ ok: true, profile: { memory_generation: 'epoch-2' } });
    await h.deleteAllMemory();
    pending.resolve({ ok: true, profile: { memory_generation: 'epoch-1' }, summary: { score: 1 } });
    await grading; assert.equal(h.state.profile.memory_generation, 'epoch-2'); assert.equal(h.state.lessonSession, null);
  }
  {
    const h = harness(); let analyses = 0;
    const frame = { image: 'mock-jpeg', sample: new Uint8ClampedArray(32 * 24 * 4).fill(100) };
    h.context.frame = frame;
    vm.runInContext('captureCameraFrame = async () => frame;', h.context);
    h.state.localMediaStream = { getVideoTracks: () => [{}] };
    h.bridge.analyzeCameraFrame = async () => { analyses++; return { ok: true, summary: 'apple' }; };
    await h.analyzeVisionInBackground('connected');
    await h.analyzeVisionInBackground('loop'); await h.analyzeVisionInBackground('loop');
    assert.equal(analyses, 1, 'stationary frames are skipped before inference');
    frame.sample = new Uint8ClampedArray(frame.sample).fill(150);
    await h.analyzeVisionInBackground('loop'); assert.equal(analyses, 2, 'changed frame invokes inference');
    await h.analyzeVisionInBackground('capture'); assert.equal(analyses, 3, 'explicit capture overrides cache');
    h.state.lastVisionAt = Date.now() - 31000;
    await h.analyzeVisionInBackground('loop'); assert.equal(analyses, 4, 'bounded age forces refresh');
    h.resetVisionCapture(); await h.analyzeVisionInBackground('loop'); assert.equal(analyses, 5, 'new camera resets cache');
  }
  {
    const h = harness(); const old = deferred(); const latest = deferred(); let calls = 0;
    h.context.frame = { image: 'mock', sample: new Uint8ClampedArray(8) };
    vm.runInContext('captureCameraFrame = async () => frame;', h.context);
    h.state.localMediaStream = { getVideoTracks: () => [{}] };
    h.bridge.analyzeCameraFrame = () => { calls++; return calls === 1 ? old.promise : latest.promise; };
    const first = h.analyzeVisionInBackground('loop'); await Promise.resolve(); await Promise.resolve();
    h.resetVisionCapture();
    const second = h.analyzeVisionInBackground('loop'); await Promise.resolve(); await Promise.resolve();
    old.resolve({ ok: true, summary: 'old scene' }); await first;
    assert.equal(h.state.visionInFlight, true, 'old completion must not unlock the new request');
    assert.equal(h.state.lastVisionFrameHash, null, 'old completion must not populate the new cache');
    latest.resolve({ ok: true, summary: 'new scene' }); await second;
    assert.equal(calls, 2); assert.equal(h.state.visionInFlight, false);
  }
  {
    const h = harness(); live(h); const pending = deferred(); let payload;
    h.bridge.callCheckpoint = async () => ({ ok: true });
    h.bridge.endConversation = p => { payload = p; return pending.promise; };
    h.els.languageSelect.value = 'French';
    const changing = h.els.languageSelect.listeners.change();
    await Promise.resolve();
    assert.equal(h.els.languageSelect.value, 'Spanish', 'language remains captured until commit');
    pending.resolve({ ok: true }); await changing;
    assert.equal(payload.language, 'Spanish'); assert.equal(h.els.languageSelect.value, 'French');
  }
  {
    const h = harness(); live(h);
    h.bridge.callCheckpoint = async () => ({ ok: true });
    h.bridge.endConversation = async () => ({ ok: false, error: 'offline' });
    h.els.languageSelect.value = 'French';
    await h.els.languageSelect.listeners.change();
    assert.equal(h.els.languageSelect.value, 'Spanish'); assert.equal(h.state.realtimeTurns.length, 1);
    let closed = false; let prevented = false;
    h.window.close = () => { closed = true; };
    h.window.listeners.beforeunload({ preventDefault() { prevented = true; } });
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    assert.equal(prevented, true); assert.equal(closed, false, 'failed close-time save retains the window');
  }
  {
    const h = harness(); let calls = 0;
    h.context.frame = { image: 'mock', sample: new Uint8ClampedArray(32 * 24 * 4).fill(100) };
    vm.runInContext('captureCameraFrame = async () => frame;', h.context);
    h.state.localMediaStream = { getVideoTracks: () => [{}] };
    h.bridge.analyzeCameraFrame = async () => { calls++; return calls === 1 ? { ok: false } : { ok: true, summary: 'scene' }; };
    await h.analyzeVisionInBackground('loop'); await h.analyzeVisionInBackground('loop');
    assert.equal(calls, 2, 'failed inference is not cached');
    const original = new Uint8ClampedArray(32 * 24 * 4).fill(100);
    const noise = new Uint8ClampedArray(original).fill(102);
    assert.equal(h.cameraFrameChanged(original, noise), false);
    const localized = new Uint8ClampedArray(original);
    localized.fill(220, 0, 4 * 24);
    assert.equal(h.cameraFrameChanged(original, localized), true, 'localized object changes trigger analysis');
  }
  console.log('Renderer session/privacy/camera regressions passed (11 scenarios).');
}
run().catch(error => { console.error(error); process.exitCode = 1; });
