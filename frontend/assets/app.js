'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const STORE = 'scu.simple-chat.v2';
  const uid = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const state = { sessions: [], current: null, busy: false };
  let sidebarCollapsed = false;
  try { sidebarCollapsed = localStorage.getItem('scu.sidebar.v1') === 'collapsed'; } catch { /* Use the default layout. */ }
  let noticeTimer;
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }
  function notice(text) {
    clearTimeout(noticeTimer); $('notice').textContent = text; $('notice').hidden = false;
    noticeTimer = setTimeout(() => { $('notice').hidden = true; }, 3500);
  }
  function active() { return state.sessions.find((session) => session.id === state.current); }
  function save() {
    try { localStorage.setItem(STORE, JSON.stringify({ sessions: state.sessions.filter((s) => s.messages.length).slice(0, 20) })); }
    catch { notice('This browser cannot save chats. You can still ask questions.'); }
  }
  function load() {
    try {
      const data = JSON.parse(localStorage.getItem(STORE) || localStorage.getItem('scu.study.sessions.v1') || 'null');
      state.sessions = (Array.isArray(data?.sessions) ? data.sessions : []).filter((s) => typeof s.id === 'string' && Array.isArray(s.messages))
        .slice(0, 20).map((s) => ({ id: s.id, title: String(s.title || 'Chat').slice(0, 100),
          messages: s.messages.filter((m) => ['user', 'assistant'].includes(m.role) && typeof m.text === 'string')
            .slice(-30).map((m) => ({ id: String(m.id || uid()), role: m.role, text: m.text.slice(0, 20000), error: Boolean(m.error),
              result: m.result && Array.isArray(m.result.sources) ? { sources: m.result.sources.slice(0, 20), validation: m.result.validation, mode: m.result.mode, fallback: m.result.fallback } : undefined })) }));
    } catch { state.sessions = []; }
  }
  function syncSidebar() {
    const mobile = window.innerWidth <= 760;
    if (!mobile) $('sidebar').classList.remove('open');
    const overlay = mobile && $('sidebar').classList.contains('open');
    const visible = mobile ? overlay : !sidebarCollapsed;
    document.documentElement.classList.toggle('sidebar-collapsed', !mobile && sidebarCollapsed);
    $('sidebar').inert = !visible;
    $('sidebar').setAttribute('aria-hidden', String(!visible));
    $('sidebar-backdrop').hidden = !overlay;
    $('workspace').inert = overlay;
    $('open-sidebar').setAttribute('aria-expanded', String(visible));
    const closeLabel = mobile ? 'Close sidebar' : 'Collapse sidebar';
    $('close-sidebar').setAttribute('aria-label', closeLabel); $('close-sidebar').title = closeLabel;
  }
  function saveSidebar() {
    try { localStorage.setItem('scu.sidebar.v1', sidebarCollapsed ? 'collapsed' : 'expanded'); } catch { /* Current-tab controls still work. */ }
  }
  function closeSidebar() {
    const restoreFocus = window.innerWidth <= 760 && $('sidebar').classList.contains('open');
    $('sidebar').classList.remove('open'); syncSidebar();
    if (restoreFocus) $('open-sidebar').focus();
  }
  function newChat(focus = true) {
    if (state.busy) return notice('Wait for this answer before starting a new chat.');
    state.sessions = state.sessions.filter((s) => s.messages.length);
    const session = { id: uid(), title: 'New chat', messages: [] };
    state.sessions.unshift(session); state.current = session.id;
    $('question').value = ''; $('input-error').hidden = true; $('question').removeAttribute('aria-invalid');
    closeSidebar(); renderHistory(); renderMessages();
    if (focus) $('question').focus();
  }
  function renderHistory() {
    const list = $('history-list'); list.replaceChildren();
    const sessions = state.sessions.filter((s) => s.messages.length);
    if (!sessions.length) list.append(el('p', 'history-empty', 'Your conversations will appear here.'));
    for (const session of sessions) {
      const button = el('button', `history-item${session.id === state.current ? ' selected' : ''}`, session.title);
      button.type = 'button'; button.title = session.title;
      if (session.id === state.current) button.setAttribute('aria-current', 'true');
      button.addEventListener('click', () => {
        if (state.busy) return notice('Wait for this answer before switching chats.');
        state.current = session.id; $('question').value = ''; $('input-error').hidden = true; $('question').removeAttribute('aria-invalid');
        closeSidebar(); renderHistory(); renderMessages();
      });
      list.append(button);
    }
  }
  function revealSource(messageId, number) {
    const card = $(`source-${messageId}-${number}`);
    if (!card) return;
    card.closest('details').open = true;
    card.focus({ preventScroll: true }); card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  function appendSources(node, message) {
    const sources = message.result?.sources || [];
    if (!sources.length) return;
    const details = el('details', 'sources');
    details.append(el('summary', '', `View sources (${sources.length})`));
    for (const source of sources) {
      const meta = source.metadata || {};
      const card = el('article', 'source-card'); card.id = `source-${message.id}-${source.citation}`; card.tabIndex = -1;
      card.append(el('h3', '', `Source ${source.citation}: ${meta.name || 'Reference'}`));
      const labels = meta.source === 'course' ? [meta.semester && `Semester ${meta.semester}`, meta.teacher, meta.course_code] : ['Faculty profile'];
      card.append(el('p', 'source-meta', labels.filter(Boolean).join('・')), el('p', 'source-content', source.content || 'No source excerpt available.'));
      if (meta.profile_url) {
        try {
          const url = new URL(meta.profile_url);
          if (['https:', 'http:'].includes(url.protocol)) {
            const link = el('a', 'source-link', 'Faculty website'); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; card.append(link);
          }
        } catch { /* Unsafe or invalid source links are not shown. */ }
      }
      details.append(card);
    }
    node.append(details);
  }
  function renderMessages() {
    const messages = active()?.messages || [];
    $('welcome').hidden = messages.length > 0; $('messages').replaceChildren();
    for (const message of messages) {
      const article = el('article', `message ${message.role}${message.error ? ' error' : ''}`);
      if (message.error) article.setAttribute('role', 'alert');
      if (message.role === 'user') article.append(el('p', 'user-bubble', message.text));
      else {
        const label = el('div', 'assistant-name'); label.append(el('span', 'assistant-mark', '✳'), document.createTextNode('Course Assistant'));
        if (message.result?.validation?.status) {
          const status = message.result.validation.status;
          const computed = message.result.mode === 'computed_fallback';
          const badgeText = status === 'passed' ? 'Sources checked' : status === 'data_checked' ? (computed ? 'Computed from data' : 'Source excerpts') : status === 'no_evidence' ? 'No matching data' : 'Could not verify';
          const badge = el('span', `validation-badge ${status}`, badgeText);
          const reason = { llm_timeout: 'The local model did not finish within 10 s.', model_warming: 'The local model is warming up.', model_busy: 'The local model is busy.', model_unavailable: 'The local model is unavailable.', retrieval_unavailable: 'Semantic search is unavailable.', verification_failed: 'The model answer did not pass verification.' }[message.result.fallback?.reason] || '';
          badge.title = status === 'passed' ? `Model: ${message.result.validation.model || 'local model'}. ${message.result.validation.llm_calls || 0} local model calls. Course scope, count, semester, citations and numbers checked; evidence reviewed.` : status === 'data_checked' ? `${reason} ${computed ? 'Calculated from local records; course scope, count, semester, citations and numbers checked.' : 'Verbatim excerpts from matching local sources.'} This reply was not generated or reviewed by an LLM.`.trim() : status === 'no_evidence' ? 'No local source matches the requested conditions.' : 'The answer did not pass verification.';
          label.append(badge);
        }
        article.append(label);
        const answer = el('div', 'answer-text');
        const citations = new Set((message.result?.sources || []).map((s) => s.citation));
        for (const part of message.text.split(/(\[\d+\])/g)) {
          const match = /^\[(\d+)\]$/.exec(part); const number = match ? Number(match[1]) : null;
          if (match && citations.has(number)) {
            const button = el('button', 'citation', String(number)); button.type = 'button';
            button.setAttribute('aria-label', `View source ${number}`);
            button.addEventListener('click', () => revealSource(message.id, number)); answer.append(button);
          } else answer.append(document.createTextNode(part));
        }
        article.append(answer); appendSources(article, message);
      }
      $('messages').append(article);
    }
    $('conversation').scrollTop = $('conversation').scrollHeight;
  }
  function setSending(sending) {
    const button = $('search-button');
    button.disabled = sending;
    button.classList.toggle('is-loading', sending);
    const label = sending ? 'Searching' : 'Send message';
    button.setAttribute('aria-label', label); button.title = label;
  }
  function inputError(text) {
    $('input-error').textContent = text; $('input-error').hidden = false;
    $('question').setAttribute('aria-invalid', 'true'); $('question').focus();
  }
  function friendlyError(error) {
    if (error.name === 'AbortError' || error.status === 504) return 'The local service did not respond within 15 s. Please try again.';
    if (/warming up/i.test(error.message)) return 'The local models are warming up. Please try again in a moment.';
    if (/model is busy/i.test(error.message)) return 'The local model is busy. Please try again shortly.';
    if (/Ollama/i.test(error.message)) return 'Open Ollama, then try again.';
    return 'Unable to get an answer. Check that the local service is running, then try again.';
  }
  async function search(event) {
    event.preventDefault(); if (state.busy) return;
    const question = $('question').value.trim();
    if (!question) return inputError('Enter a question first.');
    if (question.length > 2000) return inputError('Keep your question within 2,000 characters.');
    const session = active();
    const history = session.messages.filter((m) => !m.error).slice(-6).map((m) => ({ role: m.role, content: m.text.slice(0, 2000) }));
    session.messages.push({ id: uid(), role: 'user', text: question });
    if (session.messages.filter((m) => m.role === 'user').length === 1) session.title = question.slice(0, 30);
    state.sessions = [session, ...state.sessions.filter((s) => s.id !== session.id)].slice(0, 20);
    state.busy = true; $('question').value = ''; $('input-error').hidden = true; $('question').removeAttribute('aria-invalid');
    setSending(true);
    $('search-form').setAttribute('aria-busy', 'true'); $('waiting').hidden = false; $('waiting-text').textContent = 'Searching for an answer…';
    const waitStarted = performance.now();
    $('waiting-elapsed').textContent = '0 s';
    const elapsedTimer = setInterval(() => {
      $('waiting-elapsed').textContent = `${Math.floor((performance.now() - waitStarted) / 1000)} s`;
    }, 1000);
    renderHistory(); renderMessages(); save();
    const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 15000);
    const slow = setTimeout(() => { $('waiting-text').textContent = 'Checking with the local model. Data answer after 10 s…'; }, 5000);
    try {
      const response = await fetch('/chat', { method: 'POST', cache: 'no-store', signal: controller.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question, history, top_k: 4 }) });
      const result = await response.json();
      if (!response.ok) {
        const error = new Error(typeof result.detail === 'string' ? result.detail : 'service unavailable');
        error.status = response.status; throw error;
      }
      if (typeof result.answer !== 'string' || !Array.isArray(result.sources)) throw new Error('invalid answer');
      session.messages.push({ id: uid(), role: 'assistant', text: result.answer, result });
    } catch (error) {
      session.messages.push({ id: uid(), role: 'assistant', text: friendlyError(error), error: true });
      if (!$('question').value) $('question').value = question;
    } finally {
      clearTimeout(timeout); clearTimeout(slow); clearInterval(elapsedTimer); state.busy = false;
      session.messages = session.messages.slice(-30); $('waiting').hidden = true;
      setSending(false); $('search-form').removeAttribute('aria-busy');
      renderMessages(); renderHistory(); save();
    }
  }
  $('search-form').addEventListener('submit', search);
  for (const button of document.querySelectorAll('[data-example-question]')) {
    button.addEventListener('click', () => {
      if (state.busy) return;
      const input = $('question');
      input.value = button.dataset.exampleQuestion;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    });
  }
  $('question').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
      event.preventDefault(); search(event);
    }
  });
  $('question').addEventListener('input', () => { $('input-error').hidden = true; $('question').removeAttribute('aria-invalid'); });
  $('new-chat').addEventListener('click', () => newChat());
  $('open-sidebar').addEventListener('click', () => {
    if (window.innerWidth <= 760) $('sidebar').classList.add('open');
    else { sidebarCollapsed = false; saveSidebar(); }
    syncSidebar(); $('close-sidebar').focus();
  });
  $('close-sidebar').addEventListener('click', () => {
    if (window.innerWidth > 760) { sidebarCollapsed = true; saveSidebar(); }
    closeSidebar(); $('open-sidebar').focus();
  });
  $('sidebar-backdrop').addEventListener('click', closeSidebar);
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeSidebar(); });
  window.addEventListener('resize', syncSidebar);
  $('theme-toggle').addEventListener('click', () => window.SCUTheme.toggle());
  window.SCUTheme.syncButton();
  load(); newChat(false);
  // New answers are requested only by submitting the form. History selection
  // only opens locally saved messages; startup never calls an API.
})();
