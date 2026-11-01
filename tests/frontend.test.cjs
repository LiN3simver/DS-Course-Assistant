const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8');
const script = fs.readFileSync(path.join(root, 'frontend/assets/app.js'), 'utf8');
const source = { citation: 1, content: '研究領域：數位學習', metadata: { source: 'professor', name: '金凱儀', profile_url: 'https://bigdata.scu.edu.tw/team/' } };
const answer = { answer: '金凱儀擅長數位學習。 [1]', sources: [source] };
async function until(check) {
  for (let i = 0; i < 100; i++) { if (check()) return; await new Promise((r) => setTimeout(r, 5)); }
  throw new Error('DOM update timed out');
}
function setup(t, handler = async () => ({ body: answer }), saved, preferences = {}) {
  const dom = new JSDOM(html, { url: 'http://localhost/', runScripts: 'outside-only', pretendToBeVisual: true });
  t.after(() => dom.window.close());
  const w = dom.window, d = w.document, calls = [];
  w.HTMLElement.prototype.scrollIntoView = function () {};
  if (saved) w.localStorage.setItem('scu.simple-chat.v2', saved);
  w.fetch = async (url, options) => {
    calls.push({ url, options }); const result = await handler(url, options);
    return { ok: (result.status || 200) < 400, json: async () => result.body };
  };
  if (preferences.theme) w.localStorage.setItem('scu.theme.v1', preferences.theme);
  if (preferences.sidebar) w.localStorage.setItem('scu.sidebar.v1', preferences.sidebar);
  if (preferences.width) Object.defineProperty(w, 'innerWidth', { value: preferences.width, writable: true });
  let mediaChange;
  w.matchMedia = () => ({ matches: Boolean(preferences.darkSystem), addEventListener: (_event, handler) => { mediaChange = handler; } });
  w.eval(fs.readFileSync(path.join(root, 'frontend/assets/theme.js'), 'utf8'));
  w.eval(script);
  const submit = (text) => {
    d.getElementById('question').value = text;
    d.getElementById('search-form').dispatchEvent(new w.Event('submit', { bubbles: true, cancelable: true }));
  };
  const completed = () => d.getElementById('waiting').hidden;
  return { w, d, calls, submit, completed, changeSystem: (dark) => mediaChange({ matches: dark }) };
}
test('SCU branding, left history and a single query flow without automatic requests', async (t) => {
  const { d, calls } = setup(t); await new Promise((r) => setTimeout(r, 10));
  assert.equal(calls.length, 0);
  assert.equal(d.getElementById('messages').textContent, '');
  assert.equal(d.querySelectorAll('select, dialog, [data-question], #nav-ranking').length, 0);
  assert.equal(d.getElementById('search-button').textContent.trim(), '');
  assert.equal(d.getElementById('search-button').getAttribute('aria-label'), 'Send message');
  assert.equal(d.querySelector('.brand').textContent, 'SCU Data Science');
  assert.equal(d.querySelector('.history-heading').textContent, 'Chat history');
  assert.equal(d.documentElement.lang, 'en');
  assert.equal(d.querySelector('.topbar h1').textContent, 'Course Assistant');
  assert.doesNotMatch(html, /東吳|知課/);
});
test('Enter sends, while Shift+Enter and IME selection do not submit', async (t) => {
  const { w, d, calls, completed } = setup(t); const input = d.getElementById('question'); input.value = '查課程';
  input.dispatchEvent(new w.Event('input', { bubbles: true }));
  input.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true }));
  input.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true }));
  input.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', keyCode: 229, bubbles: true }));
  assert.equal(calls.length, 0);
  input.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  await until(completed); assert.equal(calls.length, 1);
});
test('chat and input use 16px text with readable sidebar controls', async (t) => {
  const { w, d, submit, completed } = setup(t);
  const style = d.createElement('style'); style.textContent = fs.readFileSync(path.join(root, 'frontend/assets/styles.css'), 'utf8').replace(/^@charset[^;]*;/, ''); d.head.append(style);
  submit('老師'); await until(completed);
  assert.equal(w.getComputedStyle(d.getElementById('question')).fontSize, '16px');
  assert.equal(w.getComputedStyle(d.querySelector('.answer-text')).fontSize, '16px');
  assert.ok(parseFloat(w.getComputedStyle(d.querySelector('.history-item')).fontSize) >= 14);
  assert.ok(parseFloat(w.getComputedStyle(d.getElementById('search-button')).minHeight) >= 42);
});
test('empty queries explain the next step and focus input', (t) => {
  const { d, calls, submit } = setup(t); submit('   ');
  assert.equal(calls.length, 0); assert.equal(d.getElementById('input-error').hidden, false);
  assert.equal(d.activeElement.id, 'question');
});
test('explicit query renders user and assistant messages and creates history', async (t) => {
  const { d, calls, submit, completed } = setup(t); submit('哪位老師擅長數位學習？'); await until(completed);
  assert.equal(calls.length, 1); assert.equal(calls[0].url, '/chat');
  assert.deepEqual(JSON.parse(calls[0].options.body), { question: '哪位老師擅長數位學習？', history: [], top_k: 4 });
  assert.equal(d.querySelectorAll('.message.user').length, 1); assert.equal(d.querySelectorAll('.message.assistant').length, 1);
  assert.match(d.querySelector('.answer-text').textContent, /金凱儀/);
  assert.equal(d.querySelectorAll('.history-item').length, 1); assert.equal(d.getElementById('welcome').hidden, true);
});
test('citations open their own source inline in the corresponding answer', async (t) => {
  const { d, submit, completed } = setup(t); submit('老師'); await until(completed);
  assert.equal(d.querySelector('.sources').open, false); d.querySelector('.citation').click();
  assert.equal(d.querySelector('.sources').open, true);
  assert.match(d.activeElement.textContent, /數位學習/); assert.equal(d.querySelector('.source-link').rel, 'noopener noreferrer');
});
test('follow-up queries preserve completed turns as context', async (t) => {
  const { d, calls, submit, completed } = setup(t); submit('金凱儀的專長？'); await until(completed);
  submit('他的背景呢？'); await until(completed);
  const payload = JSON.parse(calls[1].options.body);
  assert.equal(payload.history.length, 2); assert.equal(payload.history[0].content, '金凱儀的專長？');
  assert.equal(payload.history[1].role, 'assistant'); assert.equal(d.querySelectorAll('.message').length, 4);
});
test('new chat clears messages and draft; clicking history restores without a request', async (t) => {
  const { d, calls, submit, completed } = setup(t); submit('老師專長'); await until(completed);
  d.getElementById('question').value = '草稿'; d.getElementById('new-chat').click();
  assert.equal(d.querySelectorAll('.message').length, 0); assert.equal(d.getElementById('question').value, '');
  assert.equal(d.getElementById('welcome').hidden, false);
  d.querySelector('.history-item').click(); assert.equal(d.querySelectorAll('.message').length, 2); assert.equal(calls.length, 1);
});
test('reload lists saved conversations but only opens one when explicitly selected', async (t) => {
  const first = setup(t); first.submit('已儲存的問題'); await until(first.completed);
  const second = setup(t, undefined, first.w.localStorage.getItem('scu.simple-chat.v2'));
  assert.equal(second.d.querySelectorAll('.history-item').length, 1); assert.equal(second.d.querySelectorAll('.message').length, 0);
  second.d.querySelector('.history-item').click(); assert.match(second.d.getElementById('messages').textContent, /金凱儀/);
  assert.equal(second.calls.length, 0);
});
test('busy state prevents duplicate sends and switching conversations', async (t) => {
  let release; const pending = new Promise((r) => { release = r; });
  const { d, calls, submit, completed } = setup(t, async () => { await pending; return { body: answer }; });
  submit('第一題'); submit('重複送出'); d.getElementById('new-chat').click();
  assert.equal(calls.length, 1); assert.equal(d.getElementById('search-button').disabled, true);
  release(); await until(completed); assert.equal(d.querySelectorAll('.message').length, 2);
});
test('errors keep the question ready for retry using the same query button', async (t) => {
  let count = 0; const { d, submit, completed } = setup(t, async () => ++count === 1
    ? { status: 503, body: { detail: '無法連線至 Ollama' } } : { body: answer });
  submit('老師'); await until(completed); assert.match(d.querySelector('.message.error').textContent, /Open Ollama/);
  assert.equal(d.getElementById('question').value, '老師'); assert.equal(d.getElementById('search-button').textContent.trim(), '');
  assert.equal(d.getElementById('search-button').getAttribute('aria-label'), 'Send message');
  submit('老師'); await until(completed); assert.equal(d.querySelectorAll('.citation').length, 1);
});
test('untrusted text or source URLs cannot create executable HTML', async (t) => {
  const hostile = { answer: '<img src=x onerror=alert(1)> [1]', sources: [{ ...source, content: '<script>alert(1)</script>', metadata: { ...source.metadata, profile_url: 'javascript:alert(1)' } }] };
  const { d, submit, completed } = setup(t, async () => ({ body: hostile })); submit('<img src=x>'); await until(completed);
  assert.equal(d.querySelectorAll('#messages img, #messages script').length, 0); assert.match(d.querySelector('.answer-text').textContent, /<img/);
  assert.equal(d.querySelector('.source-link'), null);
});
test('mobile history can open, close and release the chat surface', (t) => {
  const { w, d } = setup(t, undefined, undefined, { width: 600 }); d.getElementById('open-sidebar').click();
  assert.equal(d.getElementById('sidebar').classList.contains('open'), true); assert.equal(d.getElementById('workspace').inert, true);
  d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(d.getElementById('sidebar-backdrop').hidden, true); assert.equal(d.getElementById('workspace').inert, false);
  assert.equal(d.activeElement.id, 'open-sidebar');
});
test('desktop sidebar collapses and reopens without clearing the draft or making requests', (t) => {
  const { w, d, calls } = setup(t);
  d.getElementById('question').value = 'Draft question';
  d.getElementById('close-sidebar').click();
  assert.equal(d.documentElement.classList.contains('sidebar-collapsed'), true);
  assert.equal(d.getElementById('sidebar').inert, true);
  assert.equal(d.getElementById('workspace').inert, false);
  assert.equal(d.getElementById('open-sidebar').getAttribute('aria-expanded'), 'false');
  assert.equal(w.localStorage.getItem('scu.sidebar.v1'), 'collapsed');
  d.getElementById('open-sidebar').click();
  assert.equal(d.documentElement.classList.contains('sidebar-collapsed'), false);
  assert.equal(d.getElementById('sidebar').inert, false);
  assert.equal(d.getElementById('open-sidebar').getAttribute('aria-expanded'), 'true');
  assert.equal(d.getElementById('question').value, 'Draft question');
  assert.equal(calls.length, 0);
});
test('collapsed preference survives reload and mobile resizing does not block the workspace', (t) => {
  const { w, d } = setup(t, undefined, undefined, { sidebar: 'collapsed' });
  assert.equal(d.documentElement.classList.contains('sidebar-collapsed'), true);
  w.innerWidth = 600; w.dispatchEvent(new w.Event('resize'));
  d.getElementById('open-sidebar').click();
  assert.equal(d.getElementById('workspace').inert, true);
  w.innerWidth = 1200; w.dispatchEvent(new w.Event('resize'));
  assert.equal(d.getElementById('workspace').inert, false);
  assert.equal(d.getElementById('sidebar-backdrop').hidden, true);
  assert.equal(d.documentElement.classList.contains('sidebar-collapsed'), true);
});
test('theme toggle remembers the choice and keeps the query button icon-only', (t) => {
  const { d, w, calls } = setup(t);
  assert.equal(d.documentElement.dataset.theme, 'light');
  d.getElementById('theme-toggle').click();
  assert.equal(d.documentElement.dataset.theme, 'dark');
  assert.equal(w.localStorage.getItem('scu.theme.v1'), 'dark');
  assert.equal(d.getElementById('theme-toggle').getAttribute('aria-label'), 'Switch to light theme');
  assert.equal(d.querySelector('meta[name="theme-color"]').content, '#212121');
  d.getElementById('theme-toggle').click();
  assert.equal(d.documentElement.dataset.theme, 'light');
  assert.equal(d.getElementById('search-button').textContent.trim(), '');
  assert.ok(d.getElementById('search-button').querySelector('svg'));
  assert.equal(calls.length, 0);
});
test('theme initially follows the system, but an explicit saved choice takes priority', (t) => {
  const system = setup(t, undefined, undefined, { darkSystem: true });
  assert.equal(system.d.documentElement.dataset.theme, 'dark');
  system.changeSystem(false);
  assert.equal(system.d.documentElement.dataset.theme, 'light');
  const saved = setup(t, undefined, undefined, { darkSystem: false, theme: 'dark' });
  assert.equal(saved.d.documentElement.dataset.theme, 'dark');
  saved.changeSystem(false);
  assert.equal(saved.d.documentElement.dataset.theme, 'dark');
});
test('dark theme changes the page, sidebar and composer palettes', (t) => {
  const { d, w } = setup(t);
  const style = d.createElement('style');
  style.textContent = fs.readFileSync(path.join(root, 'frontend/assets/styles.css'), 'utf8').replace(/^@charset[^;]*;/, '');
  d.head.append(style);
  const color = (name) => w.getComputedStyle(d.documentElement).getPropertyValue(name).trim();
  assert.equal(color('--bg'), '#ffffff');
  d.getElementById('theme-toggle').click();
  assert.equal(color('--bg'), '#212121');
  assert.equal(color('--sidebar'), '#171717');
  assert.equal(color('--composer'), '#2f2f2f');
  assert.equal(color('--text'), '#ececec');
  assert.equal(w.getComputedStyle(d.getElementById('search-button')).width, '42px');
  assert.equal(w.getComputedStyle(d.getElementById('search-button')).minWidth, '42px');
});
test('loading state preserves the send icon instead of replacing it with text', async (t) => {
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  const { d, submit, completed } = setup(t, async () => { await pending; return { body: answer }; });
  submit('test');
  const button = d.getElementById('search-button');
  assert.equal(button.classList.contains('is-loading'), true);
  assert.equal(button.getAttribute('aria-label'), 'Searching');
  assert.equal(button.textContent.trim(), '');
  assert.ok(button.querySelector('svg'));
  release(); await until(completed);
  assert.equal(button.classList.contains('is-loading'), false);
  assert.equal(button.getAttribute('aria-label'), 'Send message');
});
test('verification status and actual local model calls are visible with the answer', async (t) => {
  const verified = { ...answer, validation: { status: 'passed', model: 'qwen3-vl:4b-instruct', llm_calls: 3 } };
  const { d, submit, completed } = setup(t, async () => ({ body: verified }));
  submit('which course?'); await until(completed);
  const badge = d.querySelector('.validation-badge');
  assert.equal(badge.textContent, 'Sources checked');
  assert.match(badge.title, /qwen3-vl:4b-instruct/);
  assert.match(badge.title, /3 local model calls/);
});

test('fallback labels identify computed answers and source excerpts, including restored history', async (t) => {
  for (const [mode, label] of [['computed_fallback', 'Computed from data'], ['structured_fallback', 'Source excerpts']]) {
    const data = { ...answer, mode, model: null, validation: { status: 'data_checked', llm_reviewed: false }, fallback: { reason: 'llm_timeout' } };
    const { w, d, submit, completed } = setup(t, async () => ({ body: data }));
    submit('which course?'); await until(completed);
    assert.equal(d.querySelector('.validation-badge').textContent, label);
    assert.match(d.querySelector('.validation-badge').title, /within 10 s/);
    assert.match(d.querySelector('.validation-badge').title, /not generated or reviewed by an LLM/);
    const saved = w.localStorage.getItem('scu.simple-chat.v2');
    const restored = setup(t, undefined, saved);
    restored.d.querySelector('.history-item').click();
    assert.equal(restored.d.querySelector('.validation-badge').textContent, label);
    assert.equal(restored.calls.length, 0);
  }
});

test('missing local evidence is shown as no matching data', async (t) => {
  const { d, submit, completed } = setup(t, async () => ({ body: { answer: 'No source found.', sources: [], validation: { status: 'no_evidence' } } }));
  submit('unknown course'); await until(completed);
  assert.equal(d.querySelector('.validation-badge').textContent, 'No matching data');
});
test('each of the three examples fills an editable draft without submitting or saving a chat', (t) => {
  const { d, calls } = setup(t);
  const examples = d.querySelectorAll('[data-example-question]');
  assert.equal(examples.length, 3);
  for (const example of examples) {
    example.click();
    const input = d.getElementById('question');
    assert.equal(input.value, example.dataset.exampleQuestion);
    assert.equal(d.activeElement, input);
    assert.equal(input.selectionStart, input.value.length);
    assert.equal(calls.length, 0);
    assert.equal(d.querySelectorAll('.message, .history-item').length, 0);
    assert.equal(d.getElementById('waiting').hidden, true);
  }
});
test('an example can be edited before Enter sends the modified question', async (t) => {
  const { d, w, calls, completed } = setup(t);
  d.getElementById('search-form').dispatchEvent(new w.Event('submit', { bubbles: true, cancelable: true }));
  assert.equal(d.getElementById('input-error').hidden, false);
  d.querySelector('[data-example-question]').click();
  assert.equal(d.getElementById('input-error').hidden, true);
  assert.equal(d.getElementById('question').hasAttribute('aria-invalid'), false);
  assert.equal(calls.length, 0);
  d.getElementById('question').value = '114-1 給分最甜的課是哪堂？';
  d.getElementById('question').dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  await until(completed);
  assert.equal(calls.length, 1);
  assert.equal(JSON.parse(calls[0].options.body).question, '114-1 給分最甜的課是哪堂？');
  d.getElementById('new-chat').click();
  assert.equal(d.getElementById('welcome').hidden, false);
  assert.equal(d.querySelectorAll('[data-example-question]').length, 3);
});
test('wait timer uses s, resets each query and stops on success or failure', async (t) => {
  let finish;
  const { w, d, submit, completed } = setup(t, () => new Promise((resolve) => { finish = resolve; }));
  let now = 0, tick, cleared = 0;
  Object.defineProperty(w.performance, 'now', { value: () => now, configurable: true });
  w.setInterval = (callback, interval) => { assert.equal(interval, 1000); tick = callback; return 123; };
  w.clearInterval = (id) => { assert.equal(id, 123); cleared++; };
  submit('first question');
  assert.equal(d.getElementById('waiting-elapsed').textContent, '0 s');
  now = 2500; tick();
  assert.equal(d.getElementById('waiting-elapsed').textContent, '2 s');
  finish({ body: answer }); await until(completed);
  assert.equal(cleared, 1);
  submit('second question');
  assert.equal(d.getElementById('waiting-elapsed').textContent, '0 s');
  now = 6100; tick();
  assert.equal(d.getElementById('waiting-elapsed').textContent, '3 s');
  finish({ status: 503, body: { detail: 'Ollama offline' } }); await until(completed);
  assert.equal(cleared, 2);
  assert.equal(d.getElementById('waiting').hidden, true);
});
test('the frontend stops waiting at 15 seconds and does not invent a completed answer', async (t) => {
  const { w, d, submit, completed } = setup(t, (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => { const error = new Error('timeout'); error.name = 'AbortError'; reject(error); });
  }));
  const originalTimeout = w.setTimeout.bind(w);
  let expire;
  w.setTimeout = (callback, ms) => {
    if (ms === 15000) { expire = callback; return 987654; }
    return originalTimeout(callback, ms);
  };
  submit('a long question');
  assert.equal(typeof expire, 'function');
  expire(); await until(completed);
  assert.match(d.querySelector('.message.error').textContent, /15 s/);
  assert.equal(d.querySelector('.validation-badge'), null);
  assert.equal(d.querySelector('.source-card'), null);
  assert.equal(d.getElementById('search-button').disabled, false);
});
