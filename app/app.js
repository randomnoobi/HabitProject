/* ============================================
   DESK TALK — 4-object cast + The Desk group room
   ============================================ */

/** Single detailed desk webcam icon (used only on chat list header). */
const DETAILED_CAMERA_SVG = `<svg viewBox="0 0 32 28" width="28" height="28" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <rect x="2" y="7" width="22" height="16" rx="3.5" stroke="currentColor" stroke-width="1.8"/>
  <circle cx="13" cy="15" r="5" stroke="currentColor" stroke-width="1.5"/>
  <circle cx="13" cy="15" r="2.2" fill="currentColor" opacity="0.25"/>
  <path d="M24 10l6-2.5v13L24 18" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
  <rect x="9" y="23" width="8" height="2.2" rx="0.8" fill="currentColor" opacity="0.35"/>
  <circle cx="6" cy="10" r="1" fill="currentColor"/>
  <circle cx="9" cy="10" r="1" fill="currentColor"/>
  <path d="M17 11h3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" opacity="0.5"/>
</svg>`;

// ————— Backend —————
class Backend {
  constructor() {
    this.connected = false;
    this.cameraOk = false;
    this.llmOk = false;
    this.llmLabel = '';
    this.cameraIndices = [];
    this.totalCharacters = 4;
    this.eventSource = null;
    this.baseUrl = window.location.origin;
  }
  async connect() {
    try {
      const res = await fetch(`${this.baseUrl}/api/status`, { signal: AbortSignal.timeout(3000) });
      if (!res.ok) return false;
      const d = await res.json();
      this.connected = true;
      this.cameraOk = d.camera;
      this.llmOk = d.llm;
      this.llmLabel = d.llm_label || '';
      this.cameraIndices = d.camera_indices || [];
      this.totalCharacters = d.total_characters || 4;
      this.startEventStream();
      return true;
    } catch (e) { return false; }
  }
  disconnect() {
    if (this.eventSource) { this.eventSource.close(); this.eventSource = null; }
    this.connected = false;
    this.cameraOk = false;
    this.llmOk = false;
    this.llmLabel = '';
    this.cameraIndices = [];
  }
  startEventStream() {
    this.eventSource = new EventSource(`${this.baseUrl}/api/events`);
    this.eventSource.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data);
        if (d.type === 'group_message' && d.character && d.text) {
          enqueueMessage('group', d.character, d.text, null, d.snapshot || null, d.reply_to || null);
          spawnDanmu(d.character, d.text);
        } else if (d.type === 'habit_reminder' && d.character && d.text) {
          enqueueMessage(d.character, d.character, d.text);
          refreshWidgetFromServer(d.character);
        } else if (d.type === 'scenario_alert' && d.text) {
          const charId = d.character || 'group';
          const chatTarget = charId === 'group' ? 'group' : charId;
          enqueueMessage(chatTarget, charId === 'group' ? 'monty' : charId, d.text);
          if (d.scenario) spawnDanmu(charId === 'group' ? 'monty' : charId, d.text);
        }
      } catch (_) {}
    };
  }
  async sendMessage(chatId, text, widgetData = null) {
    try {
      const body = { chat: chatId, message: text, recent_messages: buildChatHistoryPayload(chatId) };
      if (chatId !== 'group' && widgetData)
        body.widget = widgetData;
      const r = await fetch(`${this.baseUrl}/api/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      return r.ok ? await r.json() : null;
    } catch (e) { return null; }
  }
  async syncAllChatTodos(byChat) {
    try {
      const r = await fetch(`${this.baseUrl}/api/chat_todos_sync`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ by_chat: byChat }),
      });
      return r.ok;
    } catch (e) { return false; }
  }
  async pushChatTodos(chatId, widgetData) {
    try {
      const r = await fetch(`${this.baseUrl}/api/chat_todos`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chat: chatId, widget: widgetData }),
      });
      return r.ok;
    } catch (e) { return false; }
  }
  async getDetections() {
    try {
      const r = await fetch(`${this.baseUrl}/api/detections`);
      return r.ok ? await r.json() : null;
    } catch (e) { return null; }
  }
  snapshotUrl(id) { return `${this.baseUrl}/api/snapshot/${id}`; }
}

/** Last 5 messages in this thread before the current user send (oldest first in payload). */
function buildChatHistoryPayload(chatId) {
  const arr = chatId === 'group' ? state.groupMessages : (state.individualMessages[chatId] || []);
  if (arr.length < 2) return [];
  const prior = arr.slice(0, -1).slice(-5);
  return prior.map((m) => {
    const isUser = m.from === 'user';
    const assistantName = !isUser
      ? (chatId === 'group' ? (CHARACTERS[m.char]?.name || m.char) : CHARACTERS[chatId]?.name)
      : undefined;
    return {
      role: isUser ? 'user' : 'assistant',
      name: assistantName,
      text: (m.text || '').slice(0, 2000),
    };
  });
}

let backend = null;

// ————— Message Queue —————
const messageQueue = [];
let messageQueueRunning = false;

function enqueueMessage(chatId, charId, text, progress = null, snapshot = null, replyTo = null) {
  messageQueue.push({ chatId, charId, text, progress, snapshot, replyTo });
  if (!messageQueueRunning) drainMessageQueue();
}
async function drainMessageQueue() {
  messageQueueRunning = true;
  while (messageQueue.length > 0) {
    const { chatId, charId, text, progress, snapshot, replyTo } = messageQueue.shift();
    const vis = state.currentScreen === 'chat' &&
      (state.currentChat === chatId || (chatId === 'group' && state.currentChat === 'group'));
    if (vis) { showTypingIndicator(charId); await sleep(1500 + Math.random() * 1500); removeTypingIndicator(); }
    else { await sleep(800 + Math.random() * 1200); }
    if (chatId === 'group') addGroupMessage(charId, text, false, snapshot, replyTo);
    else addIndividualMessage(charId, text, progress, snapshot, replyTo);
    if (state.currentScreen === 'chatlist') renderChatList();
    if (messageQueue.length > 0) await sleep(2000 + Math.random() * 2000);
  }
  messageQueueRunning = false;
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ————— Characters (4 objects + group room in UI) —————
const CHARACTERS = {
  monty: {
    id: 'monty', name: 'Monty', icon: '💻', object: 'Laptop',
    bubbleClass: 'bubble-monty', senderClass: 'sender-monty', avatarClass: 'avatar-monty',
    color: '#4a8fe7', status: 'active', statusDetail: 'screen on',
    mission: 'Breaks, posture & screen time — all auto-detected.',
    realLife: 'Half-full mug touching the trackpad while you Slack.',
  },
  glug: {
    id: 'glug', name: 'Glug', icon: '☕', object: 'Cup',
    bubbleClass: 'bubble-glug', senderClass: 'sender-glug', avatarClass: 'avatar-glug',
    color: '#00b894', status: 'idle', statusDetail: 'just sitting here',
    mission: 'Hydration & plant care — sips auto-logged via camera.',
    realLife: 'Cold bottle sweating onto a corner of your notes.',
  },
  munch: {
    id: 'munch', name: 'Munch', icon: '🍕', object: 'Snack',
    bubbleClass: 'bubble-munch', senderClass: 'sender-munch', avatarClass: 'avatar-munch',
    color: '#e17055', status: 'idle', statusDetail: 'on desk — tempting',
    mission: 'Snack log — auto-detects food on desk via camera.',
    realLife: 'Chip bag wide open aimed at the laptop fan vent.',
  },
  sheets: {
    id: 'sheets', name: 'Sheets', icon: '📄', object: 'Paper',
    bubbleClass: 'bubble-sheets', senderClass: 'sender-sheets', avatarClass: 'avatar-sheets',
    color: '#d4a04a', status: 'idle', statusDetail: 'on desk — still',
    mission: 'Focus, organization & to-do list — keeps you on track.',
    realLife: 'Printed rubric under an open highlighter with the cap off.',
  },
};

const charIds = Object.keys(CHARACTERS);
const charCount = charIds.length;

// ————— Per-character widget data (localStorage + server sync) —————
const WIDGET_STORAGE_KEY = 'desktalk_widgets_v2';
const widgetStore = {};

function todayKey() { return new Date().toISOString().slice(0, 10); }

function defaultWidgetData(id) {
  if (id === 'sheets') return { type: 'todo', items: [{ text: 'Pick one top priority for the next hour', done: false }, { text: 'Clear one overdue item', done: false }] };
  if (id === 'monty') return { type: 'break_timer', last_break: null, breaks_today: 0, day: todayKey() };
  if (id === 'glug') return { type: 'sip_counter', sips: 0, goal: 8, last_sip: null, day: todayKey() };
  if (id === 'munch') return { type: 'snack_log', entries: [], day: todayKey() };
  return { type: 'none' };
}

function loadWidgets() {
  try {
    const raw = localStorage.getItem(WIDGET_STORAGE_KEY);
    if (raw) {
      const o = JSON.parse(raw);
      charIds.forEach((id) => {
        const saved = o[id];
        const def = defaultWidgetData(id);
        if (saved && saved.type === def.type) {
          if (saved.day && saved.day !== todayKey()) {
            if (def.type === 'break_timer') { saved.breaks_today = 0; saved.last_break = null; saved.day = todayKey(); }
            if (def.type === 'sip_counter') { saved.sips = 0; saved.last_sip = null; saved.day = todayKey(); }
            if (def.type === 'snack_log') { saved.entries = []; saved.day = todayKey(); }
          }
          widgetStore[id] = saved;
        } else widgetStore[id] = def;
      });
    } else charIds.forEach((id) => { widgetStore[id] = defaultWidgetData(id); });
  } catch (_) { charIds.forEach((id) => { widgetStore[id] = defaultWidgetData(id); }); }
}

function saveWidgets() { try { localStorage.setItem(WIDGET_STORAGE_KEY, JSON.stringify(widgetStore)); } catch (_) {} }

function getWidgetPayload(chatId) {
  if (!chatId || chatId === 'group') return null;
  const w = widgetStore[chatId];
  if (!w) return null;
  if (w.type === 'todo') return { type: 'todo', items: w.items };
  if (w.type === 'break_timer') return { type: 'break_timer', last_break: w.last_break, breaks_today: w.breaks_today };
  if (w.type === 'sip_counter') return { type: 'sip_counter', sips: w.sips, goal: w.goal, last_sip: w.last_sip };
  if (w.type === 'snack_log') return { type: 'snack_log', entries: w.entries };
  return null;
}

async function refreshWidgetFromServer(chatId) {
  if (!state.liveMode || !backend?.connected || chatId === 'group') return;
  try {
    const r = await fetch(`${backend.baseUrl}/api/chat_widget/${chatId}`);
    if (!r.ok) return;
    const data = await r.json();
    if (data.widget && data.widget.type) {
      const w = widgetStore[chatId];
      const sv = data.widget;
      if (w && w.type === sv.type) {
        if (sv.type === 'break_timer') {
          w.breaks_today = sv.breaks_today ?? w.breaks_today;
          w.last_break = sv.last_break ?? w.last_break;
        } else if (sv.type === 'sip_counter') {
          w.sips = sv.sips ?? w.sips;
          w.last_sip = sv.last_sip ?? w.last_sip;
        } else if (sv.type === 'snack_log' && sv.entries) {
          w.entries = sv.entries;
        }
        saveWidgets();
        if (state.currentScreen === 'chat' && state.currentChat === chatId) renderWidgetPanel(chatId);
      }
    }
  } catch (_) {}
}

async function pushWidgetToServer(chatId) {
  if (!state.liveMode || !backend?.connected || chatId === 'group') return;
  const payload = getWidgetPayload(chatId);
  if (payload) await backend.pushChatTodos(chatId, payload);
}

async function syncAllWidgetsToServer() {
  if (!state.liveMode || !backend?.connected) return;
  const copy = {};
  charIds.forEach((id) => { copy[id] = getWidgetPayload(id); });
  await backend.syncAllChatTodos(copy);
}

const CHAR_SVGS = {
  monty: '<svg viewBox="0 0 40 36" fill="none"><rect x="3" y="2" width="34" height="22" rx="4" fill="#dbe6f4" stroke="#4a8fe7" stroke-width="2"/><rect x="11" y="26" width="18" height="6" rx="3" fill="#e0ebf6" stroke="#4a8fe7" stroke-width="1.5"/><circle cx="15" cy="12" r="2.5" fill="#3D3552"/><circle cx="25" cy="12" r="2.5" fill="#3D3552"/><path d="M16 18Q20 15 24 18" stroke="#3D3552" stroke-width="2" stroke-linecap="round" fill="none"/></svg>',
  glug: '<svg viewBox="0 0 40 40" fill="none"><path d="M10 10L12 34Q12 37 15 37H25Q28 37 28 34L30 10Z" fill="#d0eee8" stroke="#00b894" stroke-width="2"/><path d="M30 16Q36 16 36 22Q36 28 30 28" stroke="#00b894" stroke-width="2" fill="none"/><circle cx="17" cy="22" r="2" fill="#2A3D3D"/><circle cx="24" cy="22" r="2" fill="#2A3D3D"/><ellipse cx="20" cy="28" rx="3" ry="2" stroke="#2A3D3D" stroke-width="1.5" fill="none"/><path d="M15 6Q17 2 19 6" stroke="#00b894" stroke-width="1.5" stroke-linecap="round" fill="none"/><path d="M22 4Q24 0 26 4" stroke="#00b894" stroke-width="1.5" stroke-linecap="round" fill="none"/></svg>',
  munch: '<svg viewBox="0 0 40 40" fill="none"><path d="M20 4L36 36H4Z" fill="#f8d8d2" stroke="#e17055" stroke-width="2" stroke-linejoin="round"/><path d="M4 36Q12 32 20 36Q28 32 36 36" fill="#f5f0e4" stroke="#d4a04a" stroke-width="2"/><circle cx="16" cy="22" r="2" fill="#3D2020"/><circle cx="24" cy="22" r="2" fill="#3D2020"/><path d="M17 28Q20 31 23 28" stroke="#3D2020" stroke-width="2" stroke-linecap="round" fill="none"/></svg>',
  sheets: '<svg viewBox="0 0 34 42" fill="none"><path d="M2 2H24L32 10V40H2Z" fill="#ede6d6" stroke="#d4a04a" stroke-width="2" stroke-linejoin="round"/><path d="M24 2V10H32" stroke="#d4a04a" stroke-width="2" stroke-linejoin="round" fill="#e5dece"/><circle cx="12" cy="20" r="2" fill="#3D3520"/><circle cx="22" cy="20" r="2" fill="#3D3520"/><path d="M14 26Q17 23 20 26" stroke="#3D3520" stroke-width="2" stroke-linecap="round" fill="none"/><path d="M8 32H24" stroke="#d4a04a44" stroke-width="1.5"/><path d="M8 36H18" stroke="#d4a04a44" stroke-width="1.5"/></svg>',
  group: '<svg viewBox="0 0 40 40" fill="none"><circle cx="20" cy="20" r="17" fill="#f0eeeb" stroke="#6c5ce7" stroke-width="2"/><circle cx="14" cy="17" r="2.5" fill="#6c5ce7"/><circle cx="26" cy="17" r="2.5" fill="#6c5ce7"/><path d="M14 25Q20 30 26 25" stroke="#6c5ce7" stroke-width="2.5" stroke-linecap="round" fill="none"/><circle cx="7" cy="8" r="3" fill="#4a8fe7" opacity="0.7"/><circle cx="33" cy="8" r="3" fill="#e17055" opacity="0.7"/><circle cx="7" cy="32" r="3" fill="#d4a04a" opacity="0.7"/><circle cx="33" cy="32" r="3" fill="#00b894" opacity="0.7"/></svg>',
};

const HABIT_AREAS = {
  glug:   'Hydration & plant reminders',
  monty:  'Screen breaks, posture & screen time',
  munch:  'Healthy eating & snack detection',
  sheets: 'Focus, organization & lost objects',
};

// Mention map: keyword → char_id (for frontend @mention autocomplete filtering)
const MENTION_ALIASES = {};
Object.entries(CHARACTERS).forEach(([id, ch]) => {
  MENTION_ALIASES[id] = id;
  MENTION_ALIASES[ch.name.toLowerCase()] = id;
  MENTION_ALIASES[ch.object.toLowerCase()] = id;
});
MENTION_ALIASES['phone'] = 'monty'; MENTION_ALIASES['cup'] = 'glug'; MENTION_ALIASES['water'] = 'glug';
MENTION_ALIASES['keyboard'] = 'monty'; MENTION_ALIASES['laptop'] = 'monty'; MENTION_ALIASES['computer'] = 'monty';
MENTION_ALIASES['cable'] = 'monty'; MENTION_ALIASES['charger'] = 'monty';
MENTION_ALIASES['snack'] = 'munch'; MENTION_ALIASES['food'] = 'munch';
MENTION_ALIASES['paper'] = 'sheets'; MENTION_ALIASES['homework'] = 'sheets';
MENTION_ALIASES['powerbank'] = 'monty'; MENTION_ALIASES['battery'] = 'monty'; MENTION_ALIASES['mouse'] = 'monty';

let mentionOptions = []; // populated from /api/context

// ————— State —————
const state = {
  currentScreen: 'splash',
  currentChat: null,
  groupMessages: [],
  individualMessages: Object.fromEntries(charIds.map(k => [k, []])),
  unread: Object.fromEntries(['group', ...charIds].map(k => [k, 0])),
  scheduledTimeouts: [],
  liveMode: false,
  detectionPollTimer: null,
  /** Where Live Desk returns: { screen, chatId } */
  liveBack: { screen: 'chatlist', chatId: null },
  /** Live desk: 'analysis' = YOLO overlay stream, 'clean' = raw camera + detection strip */
  liveViewMode: 'analysis',
};

// ————— DOM —————
const $ = (s) => document.querySelector(s);
const chatlistContent = $('#chatlist-content');
const chatMessages = $('#chat-messages');
const chatInput = $('#chat-input');
const chatHeaderName = $('#chat-header-name');
const chatHeaderIcon = $('#chat-header-icon');
const toastEl = $('#notification-toast');
const connectionBadge = $('#connection-badge');
const settingsContent = $('#settings-content');
const screens = {
  splash: $('#screen-splash'),
  chatlist: $('#screen-chatlist'),
  chat: $('#screen-chat'),
  camera: $('#screen-camera'),
  settings: $('#screen-settings'),
};

// ————— Snapshot overlay —————
function openSnapshot(url) {
  const o = document.createElement('div');
  o.className = 'snapshot-overlay';
  o.innerHTML = `<div class="snapshot-overlay-bg"></div>
    <img class="snapshot-overlay-img" src="${url}" alt="Proof">
    <button class="snapshot-overlay-close">✕</button>`;
  o.addEventListener('click', () => o.remove());
  document.body.appendChild(o);
  requestAnimationFrame(() => o.classList.add('visible'));
}

// ————— Greeting —————
function updateGreeting() {
  const h = new Date().getHours();
  let g;
  if (h < 12) g = 'Good Morning!';
  else if (h < 17) g = 'Good Afternoon!';
  else g = 'Good Evening!';
  const el = document.getElementById('header-greeting');
  if (el) el.textContent = g;
}

// ————— Navigation —————
function navigateTo(screen, chatId = null) {
  const prev = state.currentScreen;
  if (screen === 'camera') {
    if (prev === 'chat' && state.currentChat) {
      state.liveBack = { screen: 'chat', chatId: state.currentChat };
    } else {
      state.liveBack = { screen: 'chatlist', chatId: null };
    }
  }
  state.currentScreen = screen;
  if (screen !== 'camera') state.currentChat = chatId;
  Object.values(screens).forEach(s => s.classList.remove('active', 'slide-out-left'));
  if (prev === 'chatlist' && (screen === 'chat' || screen === 'camera' || screen === 'settings'))
    screens.chatlist.classList.add('slide-out-left');
  if (prev === 'chat' && screen === 'camera')
    screens.chat.classList.add('slide-out-left');
  screens[screen].classList.add('active');
  if (screen === 'chat') setupChatScreen(chatId);
  if (screen === 'chatlist') { updateGreeting(); renderChatList(); }
  if (screen === 'camera') { renderCameraStatus(); setupCameraView(); startDetectionPolling(); }
  else stopDetectionPolling();
  if (screen === 'settings') loadAndRenderRules();
  if (screen !== 'chat' && drawerOpen) { drawerOpen = false; cameraDrawer.classList.remove('open'); stopDrawerPolling(); }
}

function spawnDanmu(charId, text) {
  if (state.currentScreen !== 'camera') return;
  const layer = document.getElementById('danmu-layer');
  if (!layer || !text) return;
  const name = CHARACTERS[charId]?.name || charId;
  const line = `${name}: ${text}`.replace(/\s+/g, ' ').trim().slice(0, 100);
  const row = Math.floor(Math.random() * 7);
  const el = document.createElement('div');
  el.className = 'danmu-item';
  el.textContent = line;
  el.style.top = `${6 + row * 12}%`;
  el.style.animationDuration = `${9 + Math.random() * 5}s`;
  layer.appendChild(el);
  setTimeout(() => { try { el.remove(); } catch (_) {} }, 16000);
}

function attachSwipeLiveChat() {
  const chatScr = document.getElementById('screen-chat');
  const camScr = document.getElementById('screen-camera');
  if (!chatScr || !camScr) return;
  let sx = 0, sy = 0;
  chatScr.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 1) return;
    sx = e.touches[0].clientX; sy = e.touches[0].clientY;
  }, { passive: true });
  chatScr.addEventListener('touchend', (e) => {
    if (!e.changedTouches.length) return;
    const dx = e.changedTouches[0].clientX - sx;
    const dy = e.changedTouches[0].clientY - sy;
    if (Math.abs(dx) < 56 || Math.abs(dx) < Math.abs(dy)) return;
    if (dx < 0) navigateTo('camera');
  }, { passive: true });
  camScr.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 1) return;
    sx = e.touches[0].clientX; sy = e.touches[0].clientY;
  }, { passive: true });
  camScr.addEventListener('touchend', (e) => {
    if (!e.changedTouches.length) return;
    const dx = e.changedTouches[0].clientX - sx;
    const dy = e.changedTouches[0].clientY - sy;
    if (Math.abs(dx) < 56 || Math.abs(dx) < Math.abs(dy)) return;
    if (dx > 0) {
      const b = state.liveBack || { screen: 'chatlist', chatId: null };
      navigateTo(b.screen, b.chatId);
    }
  }, { passive: true });
}

function updateConnectionBadge() {
  if (state.liveMode) {
    const p = [];
    if (backend.cameraOk) p.push('Cam');
    if (backend.llmOk) {
      const lbl = backend.llmLabel;
      if (lbl.includes('Gemini')) p.push('Gemini');
      else if (lbl.includes('Groq')) p.push('Groq');
      else if (lbl.includes('Ollama')) p.push('Ollama');
      else if (lbl.includes('OpenAI')) p.push('OpenAI');
      else p.push('LLM');
    }
    connectionBadge.textContent = p.length ? `Live — ${p.join(' + ')}` : 'Live';
    connectionBadge.className = 'connection-badge live';
  } else {
    connectionBadge.textContent = 'Demo';
    connectionBadge.className = 'connection-badge demo';
  }
}

// ————— Live desk (primary full-bleed) —————
function getLiveMjpegUrl() {
  if (!state.liveMode || !backend?.baseUrl || !backend.cameraOk) return null;
  const idx = backend.cameraIndices[0] ?? 0;
  return state.liveViewMode === 'clean'
    ? `${backend.baseUrl}/api/video_feed_raw/${idx}`
    : `${backend.baseUrl}/api/video_feed/${idx}`;
}

function setLiveViewMode(mode) {
  if (mode !== 'analysis' && mode !== 'clean') return;
  state.liveViewMode = mode;
  const stage = document.getElementById('screen-camera')?.querySelector('.live-stage');
  if (stage) stage.classList.toggle('live-stage--clean-view', mode === 'clean');
  document.querySelectorAll('.live-view-tab').forEach((btn) => {
    const is = btn.dataset.view === mode;
    btn.classList.toggle('is-active', is);
    btn.setAttribute('aria-selected', is ? 'true' : 'false');
  });
  setupCameraView();
}

function wireLiveViewTabs() {
  const sc = document.getElementById('screen-camera');
  if (!sc || sc._liveTabsWired) return;
  sc._liveTabsWired = true;
  sc.addEventListener('click', (e) => {
    const t = e.target?.closest?.('.live-view-tab');
    if (t && t.dataset.view) setLiveViewMode(t.dataset.view);
  });
}

function _riskEventSummary(ev) {
  if (!ev || !ev.type) return '';
  const t = ev.type;
  if (t === 'zone_intrusion') {
    return `${ev.intruder_class || '?'} in ${ev.target_class || '?'} zone (${ev.zone_label || 'danger'})`;
  }
  if (t === 'edge_danger' || t === 'edge_warning') {
    return `${ev.class || 'Object'} near ${ev.edge || '?'} edge (${ev.distance_px != null ? Math.round(ev.distance_px) : '?'}px)`;
  }
  if (t === 'approaching') return 'Objects moving closer (tracked frames)';
  if (t === 'crowd') return `Crowded cluster (${(ev.count != null ? ev.count : (ev.cluster || []).length) || '—'} items)`;
  if (t === 'chain_reaction') return 'Chain: mediator between two hazards';
  if (t === 'repeated_intrusion') return 'Repeated zone entry';
  return t;
}

function renderLiveRisksBar(safety) {
  const list = document.getElementById('live-risks-list');
  const label = document.getElementById('live-risks-label');
  if (!list) return;
  if (!state.liveMode) {
    list.innerHTML = '<li class="live-risk-row live-risk-row--dim">Demo — risk list appears in live mode</li>';
    if (label) label.textContent = 'Risks and relationships (demo)';
    return;
  }
  if (!backend?.connected) {
    list.innerHTML = '<li class="live-risk-row live-risk-row--empty">Connect live for geometry / relationship output</li>';
    if (label) label.textContent = 'Risks and relationships';
    return;
  }
  if (!safety) {
    list.innerHTML = '<li class="live-risk-row live-risk-row--empty">No data</li>';
    if (label) label.textContent = 'Risks and relationships';
    return;
  }
  const expl = (safety.explanations && safety.explanations.length)
    ? safety.explanations
    : [];
  const evs = (safety.risk_events && safety.risk_events.length)
    ? safety.risk_events
    : [];
  const lines = [];
  const cap = 14;
  for (let i = 0; i < Math.min(expl.length, cap); i += 1) {
    lines.push(`<li class="live-risk-row">${escapeHtml(expl[i])}</li>`);
  }
  if (!lines.length) {
    for (let j = 0; j < Math.min(evs.length, cap); j += 1) {
      const s = _riskEventSummary(evs[j]);
      if (s) lines.push(`<li class="live-risk-row">${escapeHtml(s)}</li>`);
    }
  }
  if (!lines.length) {
    const rl = safety.risk_level != null ? safety.risk_level : 0;
    lines.push(
      `<li class="live-risk-row live-risk-row--dim">No extra geometry risks right now (risk level ${rl}/4).</li>`,
    );
  }
  list.innerHTML = lines.join('');
  const rl = safety.risk_level != null ? safety.risk_level : 0;
  if (label) {
    const st = safety.state || '—';
    label.textContent = `Risks and relationships · L${rl} · ${st}`;
  }
}

function renderLiveDetectionsBar(data) {
  const list = document.getElementById('live-detections-list');
  const label = document.getElementById('live-detections-label');
  if (!list) return;
  if (!state.liveMode) {
    list.innerHTML = [
      '<li class="live-check-row"><span class="live-check-ico" aria-hidden="true">✓</span><span class="live-check-body">Monty <em>demo</em></span></li>',
      '<li class="live-check-row"><span class="live-check-ico" aria-hidden="true">✓</span><span class="live-check-body">Glug <em>demo</em></span></li>',
      '<li class="live-check-row"><span class="live-check-ico" aria-hidden="true">✓</span><span class="live-check-body">Sheets <em>demo</em></span></li>',
    ].join('');
    if (label) label.textContent = 'Detected in frame (illustration)';
    return;
  }
  if (!backend?.connected) {
    list.innerHTML = '<li class="live-check-row live-check-row--empty"><span class="live-check-ico">—</span><span class="live-check-body">Connect live mode for real detections</span></li>';
    if (label) label.textContent = 'Detected in frame';
    return;
  }
  if (!data || (!data.objects && !data.extras)) {
    list.innerHTML = '<li class="live-check-row live-check-row--empty"><span class="live-check-ico">—</span><span class="live-check-body">No data</span></li>';
    return;
  }
  const seen = new Set();
  const rows = [];
  for (const o of Object.values(data.objects || {})) {
    if (!o.class) continue;
    seen.add(o.class);
    const pct = o.confidence != null ? Math.round((o.confidence) * 100) : '—';
    const title = escapeHtml(o.class);
    rows.push(
      `<li class="live-check-row" title="${title}"><span class="live-check-ico" aria-hidden="true">✓</span><span class="live-check-body"><span class="live-det-ico">${o.icon || '•'}</span> ${escapeHtml(o.name)} <em>${pct}%</em></span></li>`,
    );
  }
  for (const ex of data.extras || []) {
    const c = ex.yolo_class;
    if (!c || seen.has(c)) continue;
    seen.add(c);
    const pct = ex.confidence != null ? Math.round(ex.confidence * 100) : '—';
    rows.push(
      `<li class="live-check-row" title="YOLO: ${escapeHtml(c)}"><span class="live-check-ico live-check-ico--extra" aria-hidden="true">◆</span><span class="live-check-body">${escapeHtml(c)} <em>${pct}%</em> <em style="font-size:9px;opacity:0.5">extra</em></span></li>`,
    );
  }
  list.innerHTML = rows.length
    ? rows.join('')
    : '<li class="live-check-row live-check-row--empty"><span class="live-check-ico">—</span><span class="live-check-body">No objects in frame</span></li>';
  if (label) {
    const n = rows.length;
    label.textContent = n ? `Detected in frame · ${n} item${n === 1 ? '' : 's'}` : 'Detected in frame';
  }
}

function setupCameraView() {
  const primary = $('#live-video-primary');
  if (!primary) return;
  wireLiveViewTabs();
  document.querySelectorAll('.live-view-tab').forEach((btn) => {
    if (!btn.dataset.view) return;
    const is = btn.dataset.view === state.liveViewMode;
    btn.classList.toggle('is-active', is);
    btn.setAttribute('aria-selected', is ? 'true' : 'false');
  });
  const liveUrl = getLiveMjpegUrl();
  if (state.liveMode && backend.cameraOk && liveUrl) {
    primary.innerHTML = `
      <img src="${liveUrl}" alt="Live desk" class="live-video-full"
        onerror="this.style.display='none';this.nextElementSibling.style.display='flex'"
        onload="this.nextElementSibling.style.display='none'">
      <div class="camera-offline-msg">Camera connecting…</div>`;
  } else {
    const demo = document.getElementById('camera-topdown');
    primary.innerHTML = '';
    if (demo) {
      const wrap = document.createElement('div');
      wrap.className = 'camera-view topdown live-demo-fill';
      wrap.appendChild(demo.cloneNode(true));
      primary.appendChild(wrap);
    } else {
      primary.innerHTML = '<div class="camera-offline-msg">Demo desk</div>';
    }
  }
  const stage = document.getElementById('screen-camera')?.querySelector('.live-stage');
  if (stage) stage.classList.toggle('live-stage--clean-view', state.liveViewMode === 'clean');
  if (!state.liveMode || !backend?.connected) {
    renderLiveDetectionsBar(null);
    renderLiveRisksBar(null);
  }
}

function startDetectionPolling() {
  stopDetectionPolling();
  if (!state.liveMode) return;
  pollDetections();
  state.detectionPollTimer = setInterval(pollDetections, 2000);
}
function stopDetectionPolling() {
  if (state.detectionPollTimer) { clearInterval(state.detectionPollTimer); state.detectionPollTimer = null; }
}
async function pollDetections() {
  const pill = $('#live-detection-pill');
  if (!state.liveMode || !backend) {
    if (pill) pill.textContent = 'Demo';
    renderLiveDetectionsBar(null);
    renderLiveRisksBar(null);
    return;
  }
  const d = await backend.getDetections();
  if (!d) return;
  const det = Object.keys(d.objects || {});
  const extraN = (d.extras && d.extras.length) || 0;
  const total = det.length + (extraN || 0);
  let sub = total ? `${total} on desk` : '— on desk';
  let sd = null;
  try {
    const sr = await fetch(`${backend.baseUrl}/api/safety`);
    sd = await sr.json();
    if (sd.state === 'DANGEROUS') sub = `Alert · ${(sd.dangers && sd.dangers.length) || 1}`;
    else if (sd.risk_level != null && sd.risk_level > 0) sub = `L${sd.risk_level} · ${total ? `${total} on desk` : 'desk'}`;
  } catch (_) {}
  if (pill) pill.textContent = sub;
  if (state.currentScreen === 'camera') {
    renderLiveDetectionsBar(d);
    renderLiveRisksBar(sd);
  }
}

function snapshotHtml(snap) {
  if (!snap || !backend) return '';
  const url = backend.snapshotUrl(snap);
  return `<div class="msg-snapshot" onclick="openSnapshot('${url}')">
    <img src="${url}" alt="📷" loading="lazy"><span class="snapshot-badge">📷 proof</span></div>`;
}

function replyQuoteHtml(replyTo) {
  if (!replyTo || !replyTo.character || !replyTo.text) return '';
  const ch = CHARACTERS[replyTo.character];
  if (!ch) return '';
  const preview = replyTo.text.length > 80 ? replyTo.text.substring(0, 80) + '…' : replyTo.text;
  return `<div class="msg-reply-quote">
    <span class="reply-author ${ch.senderClass}">${ch.icon} ${ch.name}</span>
    <span class="reply-preview">${escapeHtml(preview)}</span></div>`;
}

/** Order of character cards in the chat list. */
const CHATLIST_ORDER = ['monty', 'glug', 'munch', 'sheets'];

// ————— Chat List — Surface banner + card rows (scales to any number) —————
function renderChatList() {
  const ids = CHATLIST_ORDER.filter((id) => CHARACTERS[id]);
  const uGroup = state.unread.group || 0;

  const lastGroupMsg = state.groupMessages.length
    ? state.groupMessages[state.groupMessages.length - 1] : null;
  const groupPreview = lastGroupMsg
    ? `<span class="surface-preview">${CHARACTERS[lastGroupMsg.charId]?.name || ''}: ${escapeHtml(lastGroupMsg.text.slice(0, 50))}</span>`
    : `<span class="surface-preview surface-preview--dim">No messages yet</span>`;

  const surfaceHtml = `
    <button type="button" class="surface-banner" data-chat="group" aria-label="Open group chat">
      <div class="surface-left">
        <div class="surface-dots" aria-hidden="true">
          ${ids.slice(0, 4).map(id => `<span class="surface-dot surface-dot--${id}">${CHAR_SVGS[id]}</span>`).join('')}
        </div>
      </div>
      <div class="surface-body">
        <div class="surface-title-row">
          <span class="surface-title">The Desk</span>
          <span class="surface-badge ${uGroup > 0 ? '' : 'hidden'}">${uGroup > 9 ? '9+' : uGroup}</span>
        </div>
        ${groupPreview}
      </div>
      <svg class="surface-arrow" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="9 18 15 12 9 6"/></svg>
    </button>`;

  const cardsHtml = ids.map((id, i) => {
    const ch = CHARACTERS[id];
    const u = state.unread[id] || 0;
    const lastMsg = (state.individualMessages[id] || []).slice(-1)[0];
    const preview = lastMsg
      ? escapeHtml(lastMsg.text.slice(0, 55))
      : `<span class="card-preview--dim">${ch.mission}</span>`;
    const delay = ((i + 1) * 0.04).toFixed(2);
    return `
    <button type="button" class="chat-card chat-card--${id}" data-chat="${id}"
      style="animation-delay:${delay}s"
      aria-label="Open chat with ${escapeHtml(ch.name)}">
      <span class="chat-card-avatar avatar-${id}">${CHAR_SVGS[id] || ch.icon}</span>
      <div class="chat-card-body">
        <div class="chat-card-top">
          <span class="chat-card-name">${escapeHtml(ch.name)}</span>
          <span class="chat-card-obj">${escapeHtml(ch.object)}</span>
        </div>
        <span class="chat-card-preview">${preview}</span>
      </div>
      <div class="chat-card-right">
        <span class="chat-card-badge ${u > 0 ? '' : 'hidden'}">${u > 9 ? '9+' : u}</span>
        <svg class="chat-card-arrow" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="9 18 15 12 9 6"/></svg>
      </div>
    </button>`;
  }).join('');

  chatlistContent.innerHTML = `
    <div class="chatlist-cards">
      ${surfaceHtml}
      <div class="chatlist-divider"><span>Private Chats</span></div>
      ${cardsHtml}
    </div>`;

  chatlistContent.querySelectorAll('.surface-banner, .chat-card').forEach((el) => {
    el.addEventListener('click', () => {
      const id = el.dataset.chat;
      if (!id) return;
      state.unread[id] = 0;
      navigateTo('chat', id);
    });
  });
}

// ————— Chat Screen · per-character widget rendering —————

function timeSince(iso) {
  if (!iso) return null;
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m ago`;
}

function renderWidgetPanel(chatId) {
  const panel = document.getElementById('chat-todo-panel');
  if (!panel) return;
  if (chatId === 'group' || !widgetStore[chatId]) {
    panel.classList.add('hidden');
    panel.setAttribute('aria-hidden', 'true');
    return;
  }
  const w = widgetStore[chatId];
  const ch = CHARACTERS[chatId];
  panel.classList.remove('hidden');
  panel.setAttribute('aria-hidden', 'false');

  if (w.type === 'todo') return renderTodoWidget(chatId, panel, ch, w);
  if (w.type === 'break_timer') return renderBreakWidget(chatId, panel, ch, w);
  if (w.type === 'sip_counter') return renderSipWidget(chatId, panel, ch, w);
  if (w.type === 'snack_log') return renderSnackWidget(chatId, panel, ch, w);
  panel.classList.add('hidden');
}

function renderTodoWidget(chatId, panel, ch, w) {
  const items = w.items || [];
  panel.innerHTML = `
    <div class="chat-todo-panel-head"><span>${ch.name} · to-do list</span></div>
    <ul class="chat-todo-ul">${items.map((t, i) => `
      <li class="chat-todo-li">
        <label class="chat-todo-item">
          <input type="checkbox" class="chat-todo-check" data-idx="${i}" ${t.done ? 'checked' : ''}>
          <span>${escapeHtml(t.text)}</span>
        </label>
        <button type="button" class="chat-todo-del" data-idx="${i}" aria-label="Remove">×</button>
      </li>`).join('') || '<li class="chat-todo-empty">Tap + to add tasks — Sheets will nag you about them.</li>'}</ul>
    <button type="button" class="chat-todo-add">+ Add item</button>`;
  panel.querySelectorAll('.chat-todo-check').forEach(cb => {
    cb.onchange = () => { const idx = +cb.dataset.idx; if (w.items[idx]) { w.items[idx].done = cb.checked; saveWidgets(); pushWidgetToServer(chatId); } };
  });
  panel.querySelectorAll('.chat-todo-del').forEach(btn => {
    btn.onclick = () => { w.items.splice(+btn.dataset.idx, 1); saveWidgets(); renderWidgetPanel(chatId); pushWidgetToServer(chatId); };
  });
  panel.querySelector('.chat-todo-add').onclick = () => {
    const line = window.prompt('New task', '');
    if (!line?.trim()) return;
    w.items.push({ text: line.trim().slice(0, 200), done: false });
    saveWidgets(); renderWidgetPanel(chatId); pushWidgetToServer(chatId);
  };
}

function renderBreakWidget(chatId, panel, ch, w) {
  const ago = timeSince(w.last_break);
  const autoLabel = state.liveMode ? '<span class="widget-auto-tag">Auto-detect on</span>' : '';
  panel.innerHTML = `
    <div class="widget-head"><span>${ch.name} · break timer</span>${autoLabel}</div>
    <div class="widget-body widget-break">
      <div class="widget-stat-row">
        <div class="widget-stat"><span class="widget-stat-num">${w.breaks_today}</span><span class="widget-stat-label">breaks today</span></div>
        <div class="widget-stat"><span class="widget-stat-num">${ago || '—'}</span><span class="widget-stat-label">last break</span></div>
      </div>
      <span class="widget-sub">${state.liveMode ? 'Logged when you leave for 5+ min' : 'Connect to auto-detect breaks'}</span>
      <button type="button" class="widget-action-btn widget-break-btn widget-btn-secondary">+ Log manually</button>
    </div>`;
  panel.querySelector('.widget-break-btn').onclick = () => {
    w.last_break = new Date().toISOString(); w.breaks_today++; w.day = todayKey();
    saveWidgets(); renderWidgetPanel(chatId); pushWidgetToServer(chatId);
    addIndividualMessage(chatId, randomPick(['Nice! Stretch those wrists.', 'Break logged — your eyes thank you.', 'Good call. Roll those shoulders too.', 'Screen break! Look at something 20 feet away for 20 seconds.']));
  };
}

function renderSipWidget(chatId, panel, ch, w) {
  const pct = Math.min(100, Math.round((w.sips / w.goal) * 100));
  const ago = timeSince(w.last_sip);
  const autoLabel = state.liveMode ? '<span class="widget-auto-tag">Auto-detect on</span>' : '';
  panel.innerHTML = `
    <div class="widget-head"><span>${ch.name} · hydration tracker</span>${autoLabel}</div>
    <div class="widget-body widget-sip">
      <div class="widget-progress-ring">
        <svg viewBox="0 0 80 80" class="sip-ring-svg">
          <circle cx="40" cy="40" r="34" fill="none" stroke="rgba(0,0,0,.06)" stroke-width="6"/>
          <circle cx="40" cy="40" r="34" fill="none" stroke="${ch.color}" stroke-width="6"
            stroke-dasharray="${2 * Math.PI * 34}" stroke-dashoffset="${2 * Math.PI * 34 * (1 - pct / 100)}"
            stroke-linecap="round" transform="rotate(-90 40 40)"/>
          <text x="40" y="44" text-anchor="middle" fill="var(--text-primary, #1a1a1a)" font-size="16" font-weight="700">${w.sips}</text>
        </svg>
        <span class="sip-goal-label">${pct}% of ${w.goal} sips</span>
      </div>
      ${ago ? `<span class="widget-sub">last sip ${ago}</span>` : `<span class="widget-sub">${state.liveMode ? 'Logged when cup leaves & returns' : 'Connect to auto-detect sips'}</span>`}
      <button type="button" class="widget-action-btn widget-sip-btn widget-btn-secondary">+ Log manually</button>
    </div>`;
  panel.querySelector('.widget-sip-btn').onclick = () => {
    w.sips++; w.last_sip = new Date().toISOString(); w.day = todayKey();
    saveWidgets(); renderWidgetPanel(chatId); pushWidgetToServer(chatId);
    if (w.sips >= w.goal) addIndividualMessage(chatId, randomPick(['Goal reached! Your kidneys send their regards.', 'Hydration goal hit — keep it up!']));
    else addIndividualMessage(chatId, randomPick(['Sip logged!', 'Nice, keep drinking.', 'One more down.', 'Hydration in progress…']));
  };
}

function renderSnackWidget(chatId, panel, ch, w) {
  const entries = w.entries || [];
  const autoLabel = state.liveMode ? '<span class="widget-auto-tag">Auto-detect on</span>' : '';
  panel.innerHTML = `
    <div class="widget-head"><span>${ch.name} · snack log</span>${autoLabel}</div>
    <div class="widget-body widget-snack">
      <div class="snack-pills">${entries.map((e, i) => `<span class="snack-pill ${e.healthy ? 'snack-healthy' : 'snack-junk'}">${escapeHtml(e.label)} <button class="snack-pill-x" data-idx="${i}">×</button></span>`).join('') || `<span class="widget-empty-hint">${state.liveMode ? 'Camera will log snacks automatically.' : 'No snacks logged yet today.'}</span>`}</div>
      <div class="snack-add-row">
        <input type="text" class="snack-input" placeholder="Or add manually..." maxlength="60">
        <button type="button" class="widget-action-btn snack-add-btn">🍎</button>
        <button type="button" class="widget-action-btn snack-junk-btn">🍕</button>
      </div>
    </div>`;
  const inp = panel.querySelector('.snack-input');
  const addEntry = (healthy) => {
    const label = inp.value.trim().slice(0, 60);
    if (!label) return;
    w.entries.push({ label, healthy, time: new Date().toISOString() }); inp.value = '';
    saveWidgets(); renderWidgetPanel(chatId); pushWidgetToServer(chatId);
    addIndividualMessage(chatId, healthy
      ? randomPick(['Solid choice!', 'Green-tier snack. Respect.', 'Your body says thanks.'])
      : randomPick(['No judgment… okay maybe a little.', 'Crumbs detected near the trackpad.', 'Snack logged. Napkin recommended.']));
  };
  panel.querySelector('.snack-add-btn').onclick = () => addEntry(true);
  panel.querySelector('.snack-junk-btn').onclick = () => addEntry(false);
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') addEntry(true); });
  panel.querySelectorAll('.snack-pill-x').forEach(btn => {
    btn.onclick = () => { w.entries.splice(+btn.dataset.idx, 1); saveWidgets(); renderWidgetPanel(chatId); pushWidgetToServer(chatId); };
  });
}

function randomPick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

function processServerActions(chatId, actions) {
  const w = widgetStore[chatId];
  if (!w || !actions?.length) return;
  let changed = false;
  for (const a of actions) {
    if (w.type === 'todo') {
      if (a.action === 'add_todo' && a.text) {
        w.items = w.items || [];
        if (w.items.length < 20) { w.items.push({ text: a.text.slice(0, 200), done: false }); changed = true; }
      } else if (a.action === 'done_todo' && a.text) {
        const item = (w.items || []).find(t => !t.done && t.text.toLowerCase().includes(a.text.toLowerCase()));
        if (item) { item.done = true; changed = true; }
      } else if (a.action === 'del_todo' && a.text) {
        const idx = (w.items || []).findIndex(t => t.text.toLowerCase().includes(a.text.toLowerCase()));
        if (idx >= 0) { w.items.splice(idx, 1); changed = true; }
      }
    } else if (w.type === 'break_timer' && a.action === 'log_break') {
      w.last_break = new Date().toISOString(); w.breaks_today++; w.day = todayKey(); changed = true;
    } else if (w.type === 'sip_counter' && a.action === 'log_sip') {
      w.sips++; w.last_sip = new Date().toISOString(); w.day = todayKey(); changed = true;
    } else if (w.type === 'snack_log' && a.action === 'log_snack' && a.label) {
      w.entries = w.entries || [];
      w.entries.push({ label: a.label.slice(0, 60), healthy: !!a.healthy, time: new Date().toISOString() });
      changed = true;
    }
  }
  if (changed) {
    saveWidgets();
    if (state.currentScreen === 'chat' && state.currentChat === chatId) renderWidgetPanel(chatId);
    pushWidgetToServer(chatId);
  }
}

function setupChatScreen(chatId) {
  const sub = document.getElementById('chat-header-subline');
  const realLifeEl = document.getElementById('chat-real-life');
  chatMessages.classList.toggle('chat-theme-sheets', chatId === 'sheets');

  if (chatId === 'group') {
    const todoPanel = document.getElementById('chat-todo-panel');
    if (todoPanel) { todoPanel.classList.add('hidden'); todoPanel.setAttribute('aria-hidden', 'true'); }
    chatHeaderName.textContent = 'The Desk';
    chatHeaderIcon.innerHTML = CHAR_SVGS.group || '';
    if (sub) {
      sub.textContent = 'Shared channel — not something the camera tracks as an object.';
      sub.classList.remove('hidden');
    }
    if (realLifeEl) {
      realLifeEl.textContent = 'Real life: everyone pipes up when two props get too close — the room isn’t a prop.';
      realLifeEl.classList.remove('hidden');
    }
  } else {
    const ch = CHARACTERS[chatId];
    const habit = HABIT_AREAS[chatId] || '';
    chatHeaderName.innerHTML = `${escapeHtml(ch.name)}${habit ? `<span class="chat-header-habit">${escapeHtml(habit)}</span>` : ''}`;
    chatHeaderIcon.innerHTML = CHAR_SVGS[chatId] || '';
    if (sub) {
      sub.textContent = ch.mission || '';
      sub.classList.toggle('hidden', !ch.mission);
    }
    if (realLifeEl) {
      if (ch.realLife) {
        realLifeEl.textContent = `Real life: ${ch.realLife}`;
        realLifeEl.classList.remove('hidden');
      } else realLifeEl.classList.add('hidden');
    }
    renderWidgetPanel(chatId);
  }
  state.unread[chatId] = 0;
  renderMessages();
  chatInput.value = '';
  chatInput.focus();
  hideMentionDropdown();
  if (state.liveMode) fetchMentionOptions();
}

function renderMessages() {
  const chatId = state.currentChat;
  if (!chatId) return;
  const msgs = chatId === 'group' ? state.groupMessages : state.individualMessages[chatId];
  const isG = chatId === 'group';
  chatMessages.innerHTML = msgs.map(m => buildMessageHtml(m, isG, chatId)).join('');
  scrollToBottom();
}

function buildMessageHtml(m, isGroup, chatId) {
  const mv = Math.floor(Math.random() * 4);
  if (m.from === 'user') {
    return `<div class="message from-user mv-${mv}"><div class="msg-body"><div class="msg-bubble">${formatMessageText(m.text)}</div></div></div>`;
  }
  const ch = CHARACTERS[m.char || chatId];
  const cid = ch.id || m.char || chatId;
  const bv = Math.floor(Math.random() * 3);
  let prog = '';
  if (m.progress) {
    const p = Math.round((m.progress.value / m.progress.max) * 100);
    prog = `<div class="msg-progress"><div class="progress-bar"><div class="progress-fill" style="width:${p}%;background:${m.progress.color}"></div></div><span class="progress-label">${m.progress.value}/${m.progress.max}</span></div>`;
  }
  const reply = replyQuoteHtml(m.replyTo);
  return `<div class="message from-character mv-${mv}">
    <div class="msg-avatar avatar-${cid}">${CHAR_SVGS[cid] || ch.icon}</div>
    <div class="msg-body">
      ${isGroup ? `<div class="msg-sender sender-${cid}">${ch.name}</div>` : ''}
      ${reply}
      <div class="msg-bubble ${ch.bubbleClass} bv-${bv}">${formatMessageText(m.text)}${snapshotHtml(m.snapshot)}${prog}</div>
    </div>
  </div>`;
}

function addGroupMessage(charId, text, silent = false, snapshot = null, replyTo = null) {
  const m = { char: charId, text, time: Date.now(), from: 'char', snapshot, replyTo };
  state.groupMessages.push(m);
  if (state.currentScreen === 'chat' && state.currentChat === 'group') appendMessageToDOM(m, true);
  else if (!silent) { state.unread.group++; if (state.currentScreen === 'chatlist') renderChatList(); }
  if (text.includes('@user') && !(state.currentScreen === 'chat' && state.currentChat === 'group'))
    showToast(CHARACTERS[charId].icon, `${CHARACTERS[charId].name}: ${text}`);
}

function addIndividualMessage(charId, text, progress = null, snapshot = null, replyTo = null) {
  const m = { text, time: Date.now(), from: 'char', progress, snapshot, replyTo };
  state.individualMessages[charId].push(m);
  if (state.currentScreen === 'chat' && state.currentChat === charId) appendMessageToDOM(m, false, charId);
  else { state.unread[charId]++; if (state.currentScreen === 'chatlist') renderChatList(); }
  if (text.includes('@user') && !(state.currentScreen === 'chat' && state.currentChat === charId))
    showToast(CHARACTERS[charId].icon, `${CHARACTERS[charId].name}: ${text}`);
}

async function addUserMessage(text) {
  const chatId = state.currentChat;
  if (!chatId) return;
  hideMentionDropdown();
  const m = { text, time: Date.now(), from: 'user' };
  if (chatId === 'group') state.groupMessages.push(m);
  else state.individualMessages[chatId].push(m);
  appendMessageToDOM(m, chatId === 'group');
  if (state.liveMode) {
    const resp_id = chatId === 'group' ? charIds[Math.floor(Math.random() * charCount)] : chatId;
    showTypingIndicator(resp_id);
    const response = await backend.sendMessage(chatId, text, getWidgetPayload(chatId));
    removeTypingIndicator();
    if (response?.messages) {
      for (const r of response.messages) {
        showTypingIndicator(r.character || chatId);
        await sleep(1200 + Math.random() * 1000);
        removeTypingIndicator();
        if (chatId === 'group') addGroupMessage(r.character, r.text);
        else addIndividualMessage(r.character || chatId, r.text);
      }
      if (response.actions && chatId !== 'group') {
        processServerActions(chatId, response.actions);
      }
    } else {
      offlineResponse(chatId);
    }
    return;
  }
  offlineResponse(chatId);
}

const OFFLINE_HINTS = {
  group: 'Connect the server for live cross-object chatter — The Desk is the room, not a mug or snack bag.',
  monty: 'Live mode: Monty tracks your screen breaks. Tap the button above to log one!',
  glug: 'Live mode: Glug counts your sips. Log hydration above — it feeds into AI replies.',
  munch: 'Live mode: Munch logs snacks. Add what you ate above and he judges your choices.',
  sheets: 'Live mode: Sheets nags your tasks — add items above, they feed into AI replies.',
};

function offlineResponse(chatId) {
  const cid = chatId !== 'group' ? chatId : charIds[Math.floor(Math.random() * charCount)];
  showTypingIndicator(cid);
  setTimeout(() => {
    removeTypingIndicator();
    const text = OFFLINE_HINTS[chatId] || OFFLINE_HINTS.group;
    if (chatId === 'group') addGroupMessage(cid, text);
    else addIndividualMessage(cid, text);
  }, 1500);
}

function appendMessageToDOM(msg, isGroup, singleCharId = null) {
  const chatId = state.currentChat;
  const wrapper = document.createElement('div');
  wrapper.innerHTML = buildMessageHtml(msg, isGroup, msg.char || singleCharId || chatId);
  const div = wrapper.firstElementChild;
  chatMessages.appendChild(div);
  scrollToBottom();
}

// ————— Typing / Toast —————
function showTypingIndicator(charId) {
  removeTypingIndicator();
  const ch = CHARACTERS[charId];
  const d = document.createElement('div');
  d.className = 'typing-indicator'; d.id = 'typing-indicator';
  d.innerHTML = `<span class="msg-sender ${ch.senderClass}" style="padding-left:0;opacity:0.6">${ch.name}</span>
    <span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>`;
  chatMessages.appendChild(d);
  scrollToBottom();
}
function removeTypingIndicator() { const e = document.getElementById('typing-indicator'); if (e) e.remove(); }

function showToast(icon, text) {
  toastEl.querySelector('.toast-icon').textContent = icon;
  toastEl.querySelector('.toast-text').textContent = text.replace(/@user/g, '@you');
  toastEl.classList.remove('hidden'); toastEl.classList.add('show');
  setTimeout(() => { toastEl.classList.remove('show'); setTimeout(() => toastEl.classList.add('hidden'), 400); }, 3500);
}

// ————— Camera Status —————
async function renderCameraStatus() {
  await pollDetections();
}

// ————— Simulation (demo) —————
function startSimulation() {
  // Chats start empty — messages only appear from live detection or habit reminders
}

// ————— Camera Drawer (peek feed only — settings on dedicated screen) —————
const cameraDrawer = $('#camera-drawer');
const cameraDrawerHandle = $('#camera-drawer-handle');
const drawerFeeds = $('#drawer-camera-feeds');
const drawerStatus = $('#drawer-status');
const drawerDetStrip = $('#drawer-detection-strip');
let drawerOpen = false;
let drawerPollTimer = null;

async function loadDrawerSnapshots() {
  const el = document.getElementById('drawer-snapshots');
  if (!el) return;
  if (!backend?.baseUrl) {
    el.innerHTML = '<div class="drawer-snapshots-empty">Connect in Live mode to load recent crops.</div>';
    return;
  }
  try {
    const r = await fetch(`${backend.baseUrl}/api/snapshots`);
    const j = await r.json();
    const items = j.items || [];
    if (!items.length) {
      el.innerHTML = '<div class="drawer-snapshots-empty">No recent crops yet — they appear with proximity alerts and proof.</div>';
      return;
    }
    el.innerHTML = items.slice(0, 32).map((it) => {
      const u = `${backend.baseUrl}/api/snapshot/${it.id}`;
      const t = it.ts != null ? new Date(it.ts * 1000).toLocaleString() : '';
      return `<button type="button" class="drawer-snap-thumb" data-url="${u}" title="${t}"><img src="${u}" alt="" loading="lazy"></button>`;
    }).join('');
    el.querySelectorAll('.drawer-snap-thumb').forEach((btn) => {
      btn.addEventListener('click', () => openSnapshot(btn.dataset.url));
    });
  } catch (_) {
    el.innerHTML = '<div class="drawer-snapshots-empty">Could not load snapshots.</div>';
  }
}

function toggleDrawer() {
  drawerOpen = !drawerOpen;
  cameraDrawer.classList.toggle('open', drawerOpen);
  if (drawerOpen) {
    setupDrawerFeeds();
    startDrawerPolling();
    loadDrawerSnapshots();
  } else {
    stopDrawerPolling();
  }
}

function setupDrawerFeeds() {
  if (!state.liveMode || !backend.cameraOk) {
    drawerFeeds.innerHTML = '<div class="drawer-camera-feed"><div class="camera-offline-msg">No camera connected</div></div>';
    return;
  }
  const idx = backend.cameraIndices[0] || 0;
  drawerFeeds.className = '';
  drawerFeeds.innerHTML = `
    <div class="drawer-camera-feed">
      <img src="${backend.baseUrl}/api/video_feed/${idx}" alt="Live desk" class="live-video-img"
        onerror="this.style.display='none';this.nextElementSibling.style.display=''"
        onload="this.nextElementSibling.style.display='none'">
      <div class="camera-offline-msg">Connecting...</div>
    </div>`;
}

function startDrawerPolling() {
  stopDrawerPolling();
  if (!state.liveMode) return;
  pollDrawerDetections();
  drawerPollTimer = setInterval(pollDrawerDetections, 2500);
}

function stopDrawerPolling() {
  if (drawerPollTimer) { clearInterval(drawerPollTimer); drawerPollTimer = null; }
}

async function pollDrawerDetections() {
  const d = await backend.getDetections();
  if (!d) return;
  const det = Object.keys(d.objects);
  let sd = null;
  try {
    const sr = await fetch(`${backend.baseUrl}/api/safety`);
    sd = await sr.json();
  } catch (_) {}
  const safety = sd && sd.state === 'DANGEROUS' ? 'DANGER' : 'SAFE';
  if (drawerDetStrip) {
    drawerDetStrip.textContent = `${det.length} object${det.length === 1 ? '' : 's'} · ${safety}`;
  }
  if (sd && sd.state === 'DANGEROUS') {
    drawerStatus.textContent = `${sd.dangers.length} alert`;
    drawerStatus.className = 'drawer-handle-status danger';
  } else if (det.length > 0) {
    drawerStatus.textContent = 'OK';
    drawerStatus.className = 'drawer-handle-status safe';
  } else {
    drawerStatus.textContent = '';
    drawerStatus.className = 'drawer-handle-status';
  }
}

cameraDrawerHandle.addEventListener('click', toggleDrawer);

// ————— Utils —————
function formatTime(ts) { const d = new Date(ts); let h = d.getHours(); const m = d.getMinutes().toString().padStart(2,'0'); const a = h >= 12 ? 'PM' : 'AM'; h = h%12||12; return `${h}:${m} ${a}`; }
function formatMessageText(t) {
  let s = escapeHtml(t);
  s = s.replace(/@user/g, '<span class="mention mention-user">@user</span>');
  s = s.replace(/@(\w+)/g, (match, name) => {
    const lower = name.toLowerCase();
    const cid = MENTION_ALIASES[lower];
    if (cid && CHARACTERS[cid]) {
      return `<span class="mention mention-object" data-char="${cid}">${CHARACTERS[cid].icon} @${CHARACTERS[cid].name}</span>`;
    }
    return match;
  });
  return s.replace(/\n/g, '<br>');
}
function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function scrollToBottom() { requestAnimationFrame(() => { chatMessages.scrollTop = chatMessages.scrollHeight; }); }
function updateStatusBarTime() { const n = new Date(); $('#status-time').textContent = `${n.getHours()}:${n.getMinutes().toString().padStart(2,'0')}`; }

// ————— @Mention Autocomplete —————
const mentionDropdown = $('#mention-dropdown');
let mentionActive = false;
let mentionQuery = '';
let mentionStartIdx = -1;

async function fetchMentionOptions() {
  if (!state.liveMode) return;
  try {
    const r = await fetch(`${backend.baseUrl}/api/context`);
    const data = await r.json();
    mentionOptions = data.mention_options || [];
  } catch (_) {}
}

function showMentionDropdown(filter = '') {
  const lower = filter.toLowerCase();
  const items = Object.values(CHARACTERS).map(ch => {
    const live = mentionOptions.find(o => o.id === ch.id);
    const detected = live ? live.detected : false;
    return { id: ch.id, name: ch.name, icon: ch.icon, object: ch.object, detected };
  }).filter(item => {
    if (!lower) return true;
    return item.name.toLowerCase().includes(lower) ||
           item.object.toLowerCase().includes(lower) ||
           item.id.includes(lower);
  });
  if (items.length === 0) { hideMentionDropdown(); return; }
  mentionDropdown.innerHTML = items.map(item =>
    `<div class="mention-option${item.detected ? ' detected' : ''}" data-id="${item.id}">
      <span class="mention-opt-icon">${item.icon}</span>
      <span class="mention-opt-name">${item.name}</span>
      <span class="mention-opt-object">${item.object}</span>
      ${item.detected ? '<span class="mention-opt-live">LIVE</span>' : ''}
    </div>`
  ).join('');
  mentionDropdown.classList.remove('hidden');
  mentionDropdown.querySelectorAll('.mention-option').forEach(el => {
    el.addEventListener('click', () => insertMention(el.dataset.id));
  });
}

function hideMentionDropdown() {
  mentionDropdown.classList.add('hidden');
  mentionActive = false;
  mentionStartIdx = -1;
}

function insertMention(charId) {
  const ch = CHARACTERS[charId];
  if (!ch) return;
  const val = chatInput.value;
  if (mentionStartIdx >= 0) {
    const before = val.substring(0, mentionStartIdx);
    const after = val.substring(chatInput.selectionStart);
    chatInput.value = `${before}@${ch.name.toLowerCase()} ${after}`;
  } else {
    const pos = chatInput.selectionStart || chatInput.value.length;
    chatInput.value = val.substring(0, pos) + `@${ch.name.toLowerCase()} ` + val.substring(pos);
  }
  hideMentionDropdown();
  chatInput.focus();
}

function handleMentionInput() {
  const val = chatInput.value;
  const pos = chatInput.selectionStart;
  const before = val.substring(0, pos);
  const atIdx = before.lastIndexOf('@');
  if (atIdx >= 0 && (atIdx === 0 || before[atIdx - 1] === ' ')) {
    const query = before.substring(atIdx + 1);
    if (query.length <= 15 && !query.includes(' ')) {
      mentionActive = true;
      mentionStartIdx = atIdx;
      mentionQuery = query;
      showMentionDropdown(query);
      return;
    }
  }
  if (mentionActive) hideMentionDropdown();
}

// ————— Safety Rules / Zone Editor —————
let availableObjects = [];

async function loadAndRenderRules() {
  if (!state.liveMode) {
    settingsContent.innerHTML = `<div class="settings-section">
      <div class="settings-info">Connect to the server to edit safety config.</div></div>`;
    return;
  }
  try {
    const [rRules, rHabit] = await Promise.all([
      fetch(`${backend.baseUrl}/api/rules`),
      fetch(`${backend.baseUrl}/api/habit_policy`),
    ]);
    const data = await rRules.json();
    const habitPolicy = rHabit.ok ? await rHabit.json() : { dnd_enabled: false, dnd_start_hour: 22, dnd_end_hour: 7 };
    availableObjects = data.available_objects || [];
    window._lastHabitPolicy = habitPolicy;
    renderRulesEditor(data, habitPolicy);
  } catch (e) {
    settingsContent.innerHTML = `<div class="settings-section">
      <div class="settings-info">Failed to load config.</div></div>`;
  }
}

function renderRulesEditor(data, habitPolicy) {
  const zones = data.danger_zones || {};
  const edge  = data.edge_proximity || {};
  const zoneKeys = Object.keys(zones);
  const hp = habitPolicy || { dnd_enabled: false, dnd_start_hour: 22, dnd_end_hour: 7, dnd_active_now: false };

  const zonesHtml = zoneKeys.map(cls => {
    const z = zones[cls];
    return `
    <div class="rule-card" data-zone="${escapeHtml(cls)}">
      <div class="rule-header">
        <span class="rule-pair">${escapeHtml(cls)}</span>
        <button class="zone-delete" data-zone="${escapeHtml(cls)}" aria-label="Remove zone">✕</button>
      </div>
      <div class="rule-label-row">
        <input type="text" class="zone-label-input" data-zone="${escapeHtml(cls)}"
          value="${escapeHtml(z.label || '')}" placeholder="Zone label...">
      </div>
      <div class="rule-distance-row">
        <label class="rule-dist-label">Zone radius</label>
        <input type="range" class="zone-slider" data-zone="${escapeHtml(cls)}"
          min="10" max="200" value="${z.expand || 60}">
        <span class="rule-dist-value">${z.expand || 60}px</span>
      </div>
      <p class="rule-relation-hint">Expand the bounding box by this many px. Other objects entering the zone trigger a danger event.</p>
    </div>`;
  }).join('');

  const objOptions = availableObjects.map(o =>
    `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join('');

  settingsContent.innerHTML = `
    <div class="settings-section">
      <div class="settings-section-title">Danger Zones</div>
      <div class="settings-subtitle">Each object class can have an expanded danger zone. Other objects entering that zone trigger an alert.</div>
      <div id="zones-list">${zonesHtml || '<div class="settings-info">No danger zones defined.</div>'}</div>
    </div>
    <div class="settings-section">
      <div class="settings-section-title">Add Danger Zone</div>
      <div class="add-rule-form">
        <div class="add-rule-row">
          <select id="new-zone-class" class="rule-select">${objOptions}</select>
        </div>
        <div class="add-rule-row">
          <input type="text" id="new-zone-label" class="rule-label-input" placeholder="Zone label (e.g. Spill zone)">
        </div>
        <div class="add-rule-row">
          <label class="rule-dist-label">Radius:</label>
          <input type="range" id="new-zone-expand" class="rule-slider" min="10" max="200" value="60">
          <span id="new-zone-val" class="rule-dist-value">60px</span>
        </div>
        <button class="add-rule-btn" id="btn-add-zone">+ Add Zone</button>
      </div>
    </div>
    <div class="settings-section">
      <div class="settings-section-title">Edge Proximity</div>
      <div class="settings-subtitle">Objects near the edge of the frame are at risk of falling off the desk.</div>
      <div class="rule-distance-row">
        <label class="rule-dist-label">Danger margin</label>
        <input type="range" id="edge-danger-px" class="rule-slider" min="10" max="120"
          value="${edge.danger_px || 35}">
        <span class="rule-dist-value">${edge.danger_px || 35}px</span>
      </div>
      <div class="rule-distance-row">
        <label class="rule-dist-label">Warning margin</label>
        <input type="range" id="edge-warn-px" class="rule-slider" min="20" max="200"
          value="${edge.warn_px || 75}">
        <span class="rule-dist-value">${edge.warn_px || 75}px</span>
      </div>
    </div>
    <div class="settings-section" id="habit-policy-section">
      <div class="settings-section-title">Habit reminders (DND)</div>
      <div class="settings-subtitle">When do-not-disturb is on, timed habit nudges are queued until the window ends. Desk signals still feed the LLM when a reminder is sent.</div>
      <label class="settings-inline-check"><input type="checkbox" id="habit-dnd-enabled" ${hp.dnd_enabled ? 'checked' : ''}/> Do not disturb (local hours)</label>
      <p class="settings-info habit-dnd-status">${hp.dnd_active_now ? 'DND active now' : 'DND not active'}</p>
      <div class="add-rule-row">
        <label class="rule-dist-label">Quiet from hour</label>
        <input type="number" id="habit-dnd-start" class="rule-label-input" min="0" max="23" value="${hp.dnd_start_hour != null ? hp.dnd_start_hour : 22}">
        <span class="rule-dist-value">to</span>
        <input type="number" id="habit-dnd-end" class="rule-label-input" min="0" max="23" value="${hp.dnd_end_hour != null ? hp.dnd_end_hour : 7}">
        <span class="rule-dist-value">(24h, wraps overnight)</span>
      </div>
      <button type="button" class="add-rule-btn" id="btn-save-habit-policy">Save habit DND</button>
      <div id="habit-policy-status" class="save-status"></div>
    </div>
    <div class="settings-section">
      <button class="save-rules-btn" id="btn-save-rules">Save Configuration</button>
      <div id="save-status" class="save-status"></div>
    </div>`;

  // Wire zone sliders
  settingsContent.querySelectorAll('.zone-slider').forEach(s => {
    s.addEventListener('input', (e) => {
      e.target.nextElementSibling.textContent = `${e.target.value}px`;
      const cls = e.target.dataset.zone;
      if (cls && zones[cls]) zones[cls].expand = parseInt(e.target.value);
    });
  });
  settingsContent.querySelectorAll('.zone-label-input').forEach(inp => {
    inp.addEventListener('input', (e) => {
      const cls = e.target.dataset.zone;
      if (cls && zones[cls]) zones[cls].label = e.target.value;
    });
  });
  settingsContent.querySelectorAll('.zone-delete').forEach(btn => {
    btn.addEventListener('click', (e) => {
      delete zones[e.target.dataset.zone];
      renderRulesEditor(data, window._lastHabitPolicy);
    });
  });

  // Edge sliders
  const edgeDanger = $('#edge-danger-px');
  const edgeWarn   = $('#edge-warn-px');
  if (edgeDanger) edgeDanger.addEventListener('input', (e) => {
    e.target.nextElementSibling.textContent = `${e.target.value}px`;
    data.edge_proximity = data.edge_proximity || {};
    data.edge_proximity.danger_px = parseInt(e.target.value);
  });
  if (edgeWarn) edgeWarn.addEventListener('input', (e) => {
    e.target.nextElementSibling.textContent = `${e.target.value}px`;
    data.edge_proximity = data.edge_proximity || {};
    data.edge_proximity.warn_px = parseInt(e.target.value);
  });

  // New zone expand slider
  const nzSlider = $('#new-zone-expand');
  const nzVal = $('#new-zone-val');
  if (nzSlider) nzSlider.addEventListener('input', () => { nzVal.textContent = `${nzSlider.value}px`; });

  // Add zone
  const addBtn = $('#btn-add-zone');
  if (addBtn) addBtn.addEventListener('click', () => {
    const cls = $('#new-zone-class').value;
    const label = $('#new-zone-label').value || `${cls} danger zone`;
    const expand = parseInt($('#new-zone-expand').value);
    data.danger_zones = data.danger_zones || {};
    data.danger_zones[cls] = { expand, label };
    renderRulesEditor(data, window._lastHabitPolicy);
  });

  // Save — store the current state back as _settingsData so saveRules can use it
  window._settingsData = data;
  const saveBtn = $('#btn-save-rules');
  if (saveBtn) saveBtn.addEventListener('click', saveRules);
  const saveHabit = document.getElementById('btn-save-habit-policy');
  if (saveHabit) saveHabit.addEventListener('click', saveHabitPolicy);
}

async function saveHabitPolicy() {
  const st = document.getElementById('habit-policy-status');
  if (!state.liveMode || !backend?.baseUrl) return;
  if (st) { st.textContent = 'Saving...'; st.className = 'save-status saving'; }
  const payload = {
    dnd_enabled: !!document.getElementById('habit-dnd-enabled')?.checked,
    dnd_start_hour: parseInt(document.getElementById('habit-dnd-start')?.value, 10) || 22,
    dnd_end_hour: parseInt(document.getElementById('habit-dnd-end')?.value, 10) || 7,
  };
  try {
    const r = await fetch(`${backend.baseUrl}/api/habit_policy`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (d.ok) {
      if (st) { st.textContent = 'Habit DND saved.'; st.className = 'save-status success'; }
    } else if (st) { st.textContent = 'Error'; st.className = 'save-status error'; }
  } catch (e) {
    if (st) { st.textContent = 'Failed.'; st.className = 'save-status error'; }
  }
  setTimeout(() => { if (st) { st.textContent = ''; st.className = 'save-status'; } }, 3000);
}

async function saveRules() {
  const statusEl = $('#save-status');
  statusEl.textContent = 'Saving...';
  statusEl.className = 'save-status saving';
  const payload = window._settingsData || {};
  try {
    const r = await fetch(`${backend.baseUrl}/api/rules`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await r.json();
    if (data.ok) {
      statusEl.textContent = 'Saved! Config reloaded.';
      statusEl.className = 'save-status success';
    } else {
      statusEl.textContent = `Error: ${data.error || 'Unknown'}`;
      statusEl.className = 'save-status error';
    }
  } catch (e) {
    statusEl.textContent = 'Failed to save.';
    statusEl.className = 'save-status error';
  }
  setTimeout(() => { statusEl.textContent = ''; statusEl.className = 'save-status'; }, 3000);
}

// ————— Listeners —————
$('#btn-settings').addEventListener('click', () => navigateTo('settings'));
$('#btn-settings-back').addEventListener('click', () => navigateTo('chatlist'));
$('#btn-camera').addEventListener('click', () => navigateTo('camera'));
const goLiveBtn = document.getElementById('btn-go-live');
if (goLiveBtn) goLiveBtn.addEventListener('click', () => navigateTo('camera'));
$('#btn-back').addEventListener('click', () => navigateTo('chatlist'));
$('#btn-cam-back').addEventListener('click', () => {
  const b = state.liveBack || { screen: 'chatlist', chatId: null };
  navigateTo(b.screen, b.chatId);
});
$('#btn-send').addEventListener('click', () => { const t = chatInput.value.trim(); if (!t) return; chatInput.value = ''; addUserMessage(t); });
chatInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') { e.preventDefault(); const t = chatInput.value.trim(); if (!t) return; chatInput.value = ''; addUserMessage(t); }
  if (e.key === 'Escape' && mentionActive) { hideMentionDropdown(); e.preventDefault(); }
});
chatInput.addEventListener('input', handleMentionInput);
$('#btn-mention').addEventListener('click', () => {
  fetchMentionOptions();
  const pos = chatInput.selectionStart || chatInput.value.length;
  const val = chatInput.value;
  const needsSpace = pos > 0 && val[pos - 1] !== ' ';
  chatInput.value = val.substring(0, pos) + (needsSpace ? ' @' : '@') + val.substring(pos);
  chatInput.focus();
  chatInput.selectionStart = chatInput.selectionEnd = pos + (needsSpace ? 2 : 1);
  mentionActive = true;
  mentionStartIdx = pos + (needsSpace ? 1 : 0);
  showMentionDropdown('');
});

// ————— Init —————
let splashDone = false;

function finishSplash(targetChat = null) {
  if (splashDone) return;
  splashDone = true;
  if (targetChat && CHARACTERS[targetChat]) {
    navigateTo('chat', targetChat);
  } else {
    navigateTo('chatlist');
    renderChatList();
  }
}

async function enterLiveMode() {
  const ok = await backend.connect();
  if (!ok) return false;
  state.liveMode = true;
  await syncAllWidgetsToServer();
  console.log('[Desk Talk] Connected —', backend.llmLabel, '— cameras:', backend.cameraIndices);
  updateConnectionBadge();
  cameraDrawer.style.display = backend.cameraOk ? '' : 'none';
  setupCameraView();
  setupDrawerFeeds();
  startDetectionPolling();
  startDrawerPolling();
  return true;
}

function enterDemoMode() {
  stopDetectionPolling();
  stopDrawerPolling();
  backend.disconnect();
  state.liveMode = false;
  updateConnectionBadge();
  cameraDrawer.style.display = 'none';
  setupCameraView();
  startSimulation();
  console.log('[Desk Talk] Switched to demo mode');
}

async function init() {
  updateStatusBarTime();
  setInterval(updateStatusBarTime, 10000);

  loadWidgets();
  backend = new Backend();

  const toggleInput = document.getElementById('mode-toggle-input');
  const toggleLabel = document.getElementById('mode-toggle-label');

  const serverAvailable = await backend.connect();
  if (serverAvailable) {
    state.liveMode = true;
    await syncAllWidgetsToServer();
    console.log('[Desk Talk] Connected —', backend.llmLabel, '— cameras:', backend.cameraIndices);
    if (toggleInput) toggleInput.checked = true;
    if (toggleLabel) toggleLabel.textContent = 'Live';
  } else {
    state.liveMode = false;
    console.log('[Desk Talk] No server — demo mode');
    startSimulation();
    if (toggleInput) toggleInput.checked = false;
    if (toggleLabel) toggleLabel.textContent = 'Demo';
  }

  if (toggleInput) {
    toggleInput.addEventListener('change', async () => {
      if (toggleInput.checked) {
        if (toggleLabel) toggleLabel.textContent = 'Live';
        const ok = await enterLiveMode();
        if (!ok) {
          toggleInput.checked = false;
          if (toggleLabel) toggleLabel.textContent = 'Demo';
          enterDemoMode();
          showToast('📡', 'Could not connect — is the server running?');
        }
      } else {
        if (toggleLabel) toggleLabel.textContent = 'Demo';
        enterDemoMode();
      }
      updateGreeting();
    });
  }

  updateConnectionBadge();
  updateGreeting();
  cameraDrawer.style.display = (state.liveMode && backend.cameraOk) ? '' : 'none';

  const camIconBtn = document.getElementById('btn-camera');
  if (camIconBtn && camIconBtn.classList.contains('icon-detailed-camera')) {
    camIconBtn.innerHTML = DETAILED_CAMERA_SVG;
  }

  attachSwipeLiveChat();

  const startBtn = document.getElementById('splash-start');
  if (startBtn) startBtn.addEventListener('click', () => finishSplash());

  document.querySelectorAll('.splash-pill[data-chat]').forEach(pill => {
    pill.addEventListener('click', () => finishSplash(pill.dataset.chat));
  });
}
document.addEventListener('DOMContentLoaded', init);
