// In-process DOM-to-HTTP integration check; does not control a browser.
const { JSDOM } = require('jsdom');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.SCU_TEST_BASE_URL || 'http://127.0.0.1:8000';
async function until(check, timeout = 18000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { if (check()) return; await new Promise((r) => setTimeout(r, 100)); }
  throw new Error('Query timed out');
}
async function main() {
  const response = await fetch(base + '/'); assert.equal(response.status, 200);
  const dom = new JSDOM(await response.text(), { url: base + '/', runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window, d = w.document, calls = [];
  w.HTMLElement.prototype.scrollIntoView = function () {};
  w.fetch = (url, options) => { calls.push(String(url)); return fetch(new URL(url, base), options); };
  const submit = (text) => {
    d.getElementById('question').value = text;
    d.getElementById('search-form').dispatchEvent(new w.Event('submit', { bubbles: true, cancelable: true }));
  };
  const done = () => d.getElementById('waiting').hidden;
  try {
    w.eval(await (await fetch(base + '/assets/theme.js')).text());
    w.eval(await (await fetch(base + '/assets/app.js')).text());
    assert.equal(calls.length, 0); assert.equal(d.querySelectorAll('.message').length, 0);
    console.log('SCU chat opens without automatic requests: OK');
    d.getElementById('question').value = '給分最甜的課是哪堂';
    d.getElementById('question').dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    await until(done);
    assert.equal(d.querySelector('.message.error'), null, d.getElementById('messages').textContent);
    assert.match(d.querySelector('.answer-text').textContent, /92\.8/);
    assert.equal(d.querySelectorAll('.source-card').length, 1);
    const badge = d.querySelector('.validation-badge');
    assert.ok(['Sources checked', 'Computed from data'].includes(badge.textContent));
    if (badge.textContent === 'Sources checked') assert.match(badge.title, /qwen3-vl:4b-instruct/);
    else assert.match(badge.title, /not generated or reviewed by an LLM/);
    d.querySelector('.citation').click(); assert.equal(d.querySelector('.sources').open, true);
    assert.equal(d.querySelectorAll('.history-item').length, 1);
    console.log('Enter → one-course checked answer → sources and saved conversation: OK (' + badge.textContent + ')');
    d.getElementById('new-chat').click(); assert.equal(d.querySelectorAll('.message').length, 0);
    d.querySelector('.history-item').click(); assert.equal(d.querySelectorAll('.message').length, 2); assert.equal(calls.length, 1);
    console.log('New chat and restoring history without another request: OK');
    if (process.argv.includes('--llm')) {
      d.getElementById('new-chat').click(); submit('哪位老師擅長數位學習或電腦輔助教學？'); await until(done);
      assert.equal(d.querySelector('.message.error'), null, d.getElementById('messages').textContent);
      assert.match(d.querySelector('.answer-text').textContent, /金凱儀/); console.log('Faculty query via local service: OK (' + d.querySelector('.validation-badge').textContent + ')');
    }
    const result = { answer: d.querySelector('.answer-text').textContent, responseLabel: d.querySelector('.validation-badge').textContent, requests: calls, historyCount: d.querySelectorAll('.history-item').length };
    const logs = path.resolve(__dirname, '../logs'); fs.mkdirSync(logs, { recursive: true });
    fs.writeFileSync(path.join(logs, 'frontend_smoke.json'), JSON.stringify(result, null, 2));
    assert.ok(calls.every((url) => url === '/chat')); console.log('PASS: SCU chat and left conversation history');
  } finally { w.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
