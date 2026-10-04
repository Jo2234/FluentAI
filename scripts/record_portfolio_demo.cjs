#!/usr/bin/env node
// Playwright drives the real renderer; only the separate Python harness mocks AI.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, execFileSync } = require('node:child_process');
const { chromium } = require('playwright');

(async () => {
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, 'cache', 'offline-recording');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'fluentai-video-'));
  const port = process.env.DEMO_PORT || '7862';
  const url = `http://127.0.0.1:${port}`;
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith('OPENAI_')));
  const server = spawn(process.env.PYTHON_EXECUTABLE || 'python', ['scripts/portfolio_demo.py', '--port', port], { cwd: root, env, stdio: ['ignore', 'pipe', 'inherit'] });
  let browser;
  try {
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Demo server did not start')), 15000);
      server.once('exit', code => { clearTimeout(timeout); reject(new Error(`Demo server exited: ${code}`)); });
      server.stdout.once('data', () => { clearTimeout(timeout); resolve(); });
    });
    browser = await chromium.launch({ headless: true, ...(process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : {}) });
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, recordVideo: { dir: temp, size: { width: 1440, height: 1000 } } });
    // Fonts and media must not contact external services during the recording.
    await context.route('**/*', route => route.request().url().startsWith(url) ? route.continue() : route.abort());
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', async response => {
      if (response.url().includes('/api/bridge/')) {
        try { const data = await response.json(); if (data.ok === false) errors.push(`${response.url()}: ${data.error}`); } catch {}
      }
    });
    const start = Date.now();
    const at = async second => { const remaining = second * 1000 - (Date.now() - start); if (remaining > 0) await page.waitForTimeout(remaining); };
    const chapter = text => page.locator('#recordingChapter').evaluate((node, value) => { node.textContent = value; }, text);
    await page.goto(url);
    await page.getByRole('button', { name: "Start today's lesson", exact: true }).waitFor();
    await chapter('1 / 5 · Start from local learner memory');
    await at(6);
    await page.getByRole('button', { name: "Start today's lesson", exact: true }).click();
    await page.locator('#quizForm').waitFor();
    await chapter('2 / 5 · Adaptive lesson + a visible selection reason');
    await at(11);
    fs.mkdirSync(output, { recursive: true });
    await page.screenshot({ path: path.join(output, 'current-lesson.png') });
    await at(14);
    await page.locator('input[name="q0"][value="yesterday"]').check();
    await page.locator('input[name="q1"]').pressSequentially('manana', { delay: 90 });
    await page.locator('input[name="q2"]').pressSequentially('Ayer fui al mercado.', { delay: 70 });
    await page.locator('input[name="q3"][value="Comi con mi familia."]').check();
    await page.locator('input[name="q4"]').pressSequentially('I went', { delay: 90 });
    await page.locator('input[name="q5"]').pressSequentially('Ayer fui al mercado.', { delay: 70 });
    await at(26);
    await chapter('3 / 5 · One deliberate mistake → feedback + spaced review');
    const submitted = page.waitForResponse(response => response.url().endsWith('/lesson_submit'));
    await page.locator('.submit-quiz').click();
    const result = await (await submitted).json();
    assert.equal(result.ok, true);
    assert(result.profile.xp > 0);
    assert(result.profile.review_count > 0);
    assert.equal(result.summary.score, '5/6');
    await page.locator('.question[data-index="1"]').scrollIntoViewIfNeeded();
    await at(34);
    await page.locator('#headerHomeBtn').click();
    await page.waitForTimeout(800);
    await at(41);
    await chapter('4 / 5 · Text practice uses the same learner memory');
    await page.locator('#headerConversationBtn').click();
    await page.locator('#startTextFallbackBtn').click();
    await page.locator('#chatInput').waitFor({ state: 'visible' });
    await page.locator('#chatInput').fill('Ayer fui al mercado.');
    await at(47);
    await page.locator('#sendBtn').click();
    await page.waitForTimeout(1200);
    await page.locator('#chatInput').fill('Comi con mi familia.');
    await at(53);
    await page.locator('#sendBtn').click();
    await at(61);
    await page.locator('#headerHomeBtn').click();
    await page.waitForTimeout(800);
    await chapter('5 / 5 · Inspect the saved evidence and review queue');
    await page.locator('#memoryInspectorPanel summary').click();
    await page.locator('#memoryInspectorContent').waitFor({ state: 'visible' });
    await page.locator('#memoryInspectorPanel').scrollIntoViewIfNeeded();
    await at(69);
    await page.reload();
    await page.locator('#homePane').waitFor({ state: 'visible' });
    await chapter('Reloaded · Progress persists · Voice/model quality not shown');
    const token = await page.locator('meta[name="fluentai-api-token"]').getAttribute('content');
    const saved = await page.request.post(`${url}/api/bridge/status`, { data: {}, headers: { 'X-FluentAI-Token': token } });
    const status = await saved.json();
    assert(status.profile.xp >= result.profile.xp);
    assert(status.profile.review_count > 0);
    await at(79);
    assert.deepEqual(errors, []);
    const video = page.video();
    await context.close();
    const raw = await video.path();
    execFileSync('ffmpeg', ['-y', '-i', raw, '-an', '-r', '20', '-c:v', 'libx264', '-preset', 'slow', '-crf', '27', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', path.join(output, 'workflow-demo.mp4')], { stdio: 'ignore' });
    const metadata = JSON.parse(execFileSync('ffprobe', ['-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', path.join(output, 'workflow-demo.mp4')], { encoding: 'utf8' }));
    assert(Number(metadata.format.duration) >= 60 && Number(metadata.format.duration) <= 90);
    fs.writeFileSync(path.join(output, 'recording.json'), JSON.stringify({
      source_commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
      duration_seconds: Number(metadata.format.duration),
      size_bytes: Number(metadata.format.size),
      viewport: '1440x1000',
      model_boundary: 'Mocked Python provider; actual renderer, bridge, grading, state persistence, and review scheduling',
      external_browser_requests: 'Blocked',
      checks: ['Lesson awarded XP', 'Review queue populated', 'XP and review queue survive page reload', 'No browser errors or failed bridge responses'],
      excluded: ['Live model quality', 'Realtime voice', 'Camera', 'Signed desktop distribution']
    }, null, 2) + '\n');
    console.log(JSON.stringify({ ok: true, duration: metadata.format.duration, bytes: metadata.format.size }));
  } finally {
    if (browser) await browser.close();
    server.kill('SIGINT');
    fs.rmSync(temp, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
