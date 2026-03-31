/* ============================================
   DESK TALK — 8-Character Desk Ecosystem
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
    this.totalCharacters = 8;
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
      this.totalCharacters = d.total_characters || 8;
      this.startEventStream();
      return true;
    } catch (e) { return false; }
  }
  startEventStream() {
    this.eventSource = new EventSource(`${this.baseUrl}/api/events`);
    this.eventSource.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data);
        if (d.type === 'group_message' && d.character && d.text) {
          enqueueMessage('group', d.character, d.text, null, d.snapshot || null, d.reply_to || null);
          spawnDanmu(d.character, d.text);
        } else if (d.type === 'habit_reminder' && d.character && d.text)
          enqueueMessage(d.character, d.character, d.text);
      } catch (_) {}
    };
  }
  async sendMessage(chatId, text) {
    try {
      const r = await fetch(`${this.baseUrl}/api/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chat: chatId, message: text }),
      });
      return r.ok ? await r.json() : null;
    } catch (e) { return null; }
  }
  async getDetections() {
    try {
      const r = await fetch(`${this.baseUrl}/api/detections`);
      return r.ok ? await r.json() : null;
    } catch (e) { return null; }
  }
  snapshotUrl(id) { return `${this.baseUrl}/api/snapshot/${id}`; }
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

// ————— Characters (8) —————
const CHARACTERS = {
  monty: {
    id: 'monty', name: 'Monty', icon: '💻', object: 'Laptop',
    bubbleClass: 'bubble-monty', senderClass: 'sender-monty', avatarClass: 'avatar-monty',
    color: '#5b8cc7', status: 'active', statusDetail: 'screen on',
  },
  glug: {
    id: 'glug', name: 'Glug', icon: '☕', object: 'Cup',
    bubbleClass: 'bubble-glug', senderClass: 'sender-glug', avatarClass: 'avatar-glug',
    color: '#3ebfa0', status: 'idle', statusDetail: 'just sitting here',
  },
  munch: {
    id: 'munch', name: 'Munch', icon: '🍕', object: 'Snack',
    bubbleClass: 'bubble-munch', senderClass: 'sender-munch', avatarClass: 'avatar-munch',
    color: '#e17055', status: 'idle', statusDetail: 'on desk — tempting',
  },
  sheets: {
    id: 'sheets', name: 'Sheets', icon: '📄', object: 'Paper',
    bubbleClass: 'bubble-sheets', senderClass: 'sender-sheets', avatarClass: 'avatar-sheets',
    color: '#b8a86e', status: 'idle', statusDetail: 'on desk — still',
  },
  zip: {
    id: 'zip', name: 'Zip', icon: '🔌', object: 'Cable',
    bubbleClass: 'bubble-zip', senderClass: 'sender-zip', avatarClass: 'avatar-zip',
    color: '#e8943a', status: 'active', statusDetail: 'plugged in',
  },
  surge: {
    id: 'surge', name: 'Surge', icon: '🔋', object: 'Power Bank',
    bubbleClass: 'bubble-surge', senderClass: 'sender-surge', avatarClass: 'avatar-surge',
    color: '#6b5b95', status: 'idle', statusDetail: 'heavy — on desk',
  },
  buzz: {
    id: 'buzz', name: 'Buzz', icon: '📱', object: 'Phone',
    bubbleClass: 'bubble-buzz', senderClass: 'sender-buzz', avatarClass: 'avatar-buzz',
    color: '#e84393', status: 'active', statusDetail: 'screen lit',
  },
};

const charIds = Object.keys(CHARACTERS);
const charCount = charIds.length;

const CHAR_SVGS = {
  monty: '<svg viewBox="0 0 40 36" fill="none"><rect x="3" y="2" width="34" height="22" rx="4" fill="#B4D3D9" stroke="#7EADB6" stroke-width="2.5"/><rect x="11" y="26" width="18" height="6" rx="3" fill="#CADEDF" stroke="#7EADB6" stroke-width="1.5"/><circle cx="15" cy="12" r="2.5" fill="#3D3552"/><circle cx="25" cy="12" r="2.5" fill="#3D3552"/><path d="M16 18Q20 15 24 18" stroke="#3D3552" stroke-width="2" stroke-linecap="round" fill="none"/></svg>',
  glug: '<svg viewBox="0 0 40 40" fill="none"><path d="M10 10L12 34Q12 37 15 37H25Q28 37 28 34L30 10Z" fill="#A0C4C4" stroke="#6B9494" stroke-width="2.5"/><path d="M30 16Q36 16 36 22Q36 28 30 28" stroke="#6B9494" stroke-width="2.5" fill="none"/><circle cx="17" cy="22" r="2" fill="#2A3D3D"/><circle cx="24" cy="22" r="2" fill="#2A3D3D"/><ellipse cx="20" cy="28" rx="3" ry="2" stroke="#2A3D3D" stroke-width="1.5" fill="none"/><path d="M15 6Q17 2 19 6" stroke="#6B9494" stroke-width="1.5" stroke-linecap="round" fill="none"/><path d="M22 4Q24 0 26 4" stroke="#6B9494" stroke-width="1.5" stroke-linecap="round" fill="none"/></svg>',
  munch: '<svg viewBox="0 0 40 40" fill="none"><path d="M20 4L36 36H4Z" fill="#D4A0A0" stroke="#A06060" stroke-width="2.5" stroke-linejoin="round"/><path d="M4 36Q12 32 20 36Q28 32 36 36" fill="#D4C4A0" stroke="#9A8560" stroke-width="2"/><circle cx="16" cy="22" r="2" fill="#3D2020"/><circle cx="24" cy="22" r="2" fill="#3D2020"/><path d="M17 28Q20 31 23 28" stroke="#3D2020" stroke-width="2" stroke-linecap="round" fill="none"/></svg>',
  sheets: '<svg viewBox="0 0 34 42" fill="none"><path d="M2 2H24L32 10V40H2Z" fill="#D4C4A0" stroke="#9A8560" stroke-width="2.5" stroke-linejoin="round"/><path d="M24 2V10H32" stroke="#9A8560" stroke-width="2" stroke-linejoin="round" fill="#C4B490"/><circle cx="12" cy="20" r="2" fill="#3D3520"/><circle cx="22" cy="20" r="2" fill="#3D3520"/><path d="M14 26Q17 23 20 26" stroke="#3D3520" stroke-width="2" stroke-linecap="round" fill="none"/><path d="M8 32H24" stroke="#9A856044" stroke-width="1.5"/><path d="M8 36H18" stroke="#9A856044" stroke-width="1.5"/></svg>',
  zip: '<svg viewBox="0 0 44 36" fill="none"><path d="M6 28Q6 10 18 10Q30 10 30 28" stroke="#6B8F6B" stroke-width="5" stroke-linecap="round" fill="none"/><circle cx="30" cy="28" r="7" fill="#A8BFA8" stroke="#6B8F6B" stroke-width="2.5"/><circle cx="28" cy="26" r="1.5" fill="#1E2E1E"/><circle cx="33" cy="26" r="1.5" fill="#1E2E1E"/><path d="M28 31Q31 33 33 31" stroke="#1E2E1E" stroke-width="1.5" stroke-linecap="round" fill="none"/><circle cx="6" cy="28" r="3" fill="#A8BFA8" stroke="#6B8F6B" stroke-width="1.5"/></svg>',
  surge: '<svg viewBox="0 0 36 40" fill="none"><rect x="3" y="2" width="30" height="36" rx="6" fill="#BDA6CE" stroke="#9B8EC7" stroke-width="2.5"/><path d="M20 10L14 22H22L16 34" stroke="#2D2040" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/><circle cx="11" cy="12" r="2" fill="#2D2040"/><circle cx="25" cy="12" r="2" fill="#2D2040"/></svg>',
  buzz: '<svg viewBox="0 0 30 42" fill="none"><rect x="2" y="2" width="26" height="38" rx="6" fill="#D4A0B8" stroke="#A06080" stroke-width="2.5"/><rect x="5" y="7" width="20" height="22" rx="3" fill="#F2EAE0"/><circle cx="11" cy="16" r="2.5" fill="#3D2030"/><circle cx="19" cy="16" r="2.5" fill="#3D2030"/><path d="M12 22Q15 25 18 22" stroke="#3D2030" stroke-width="2" stroke-linecap="round" fill="none"/><circle cx="15" cy="36" r="2" fill="#F2EAE0"/></svg>',
  group: '<svg viewBox="0 0 40 40" fill="none"><circle cx="20" cy="20" r="17" fill="#F2EAE0" stroke="#9B8EC7" stroke-width="2.5"/><circle cx="14" cy="17" r="2.5" fill="#3D3552"/><circle cx="26" cy="17" r="2.5" fill="#3D3552"/><path d="M14 25Q20 30 26 25" stroke="#3D3552" stroke-width="2.5" stroke-linecap="round" fill="none"/><circle cx="7" cy="8" r="3" fill="#B4D3D9" opacity="0.7"/><circle cx="33" cy="8" r="3" fill="#D4A0A0" opacity="0.7"/><circle cx="7" cy="32" r="3" fill="#A8BFA8" opacity="0.7"/><circle cx="33" cy="32" r="3" fill="#BDA6CE" opacity="0.7"/></svg>',
};

const HABIT_AREAS = {
  glug:   'Hydration',
  monty:  'Screen Breaks & Posture',
  munch:  'Healthy Eating',
  sheets: 'Task Management',
  zip:    'Desk Organization',
  surge:  'Energy & Breaks',
  buzz:   'Screen Time',
};

// Mention map: keyword → char_id (for frontend @mention autocomplete filtering)
const MENTION_ALIASES = {};
Object.entries(CHARACTERS).forEach(([id, ch]) => {
  MENTION_ALIASES[id] = id;
  MENTION_ALIASES[ch.name.toLowerCase()] = id;
  MENTION_ALIASES[ch.object.toLowerCase()] = id;
});
MENTION_ALIASES['phone'] = 'buzz'; MENTION_ALIASES['cup'] = 'glug'; MENTION_ALIASES['water'] = 'glug';
MENTION_ALIASES['keyboard'] = 'monty'; MENTION_ALIASES['laptop'] = 'monty'; MENTION_ALIASES['computer'] = 'monty';
MENTION_ALIASES['cable'] = 'zip'; MENTION_ALIASES['charger'] = 'zip';
MENTION_ALIASES['snack'] = 'munch'; MENTION_ALIASES['food'] = 'munch';
MENTION_ALIASES['paper'] = 'sheets'; MENTION_ALIASES['homework'] = 'sheets';
MENTION_ALIASES['powerbank'] = 'surge'; MENTION_ALIASES['battery'] = 'surge';

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
    if (backend.cameraOk) p.push(`${backend.cameraIndices.length} Cam`);
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
function setupCameraView() {
  const primary = $('#live-video-primary');
  if (!primary) return;
  if (state.liveMode && backend.cameraOk) {
    const idx = backend.cameraIndices[0];
    primary.innerHTML = `
      <img src="${backend.baseUrl}/api/video_feed/${idx}" alt="Live desk" class="live-video-full"
        onerror="this.style.display='none';this.nextElementSibling.style.display='flex'"
        onload="this.nextElementSibling.style.display='none'">
      <div class="camera-offline-msg">Camera ${idx} connecting…</div>`;
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
    return;
  }
  const d = await backend.getDetections();
  if (!d) return;
  const det = Object.keys(d.objects);
  let sub = `${det.length} on desk`;
  try {
    const sr = await fetch(`${backend.baseUrl}/api/safety`);
    const sd = await sr.json();
    if (sd.state === 'DANGEROUS') sub = `Alert · ${(sd.dangers && sd.dangers.length) || 1}`;
  } catch (_) {}
  if (pill) pill.textContent = sub;
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

// ————— Chat List (Card Grid) —————
function renderChatList() {
  const chats = [
    { id: 'group', name: 'The Desk', icon: '💬', messages: state.groupMessages, subtitle: 'Safety Alerts' },
    ...charIds.map(id => ({
      id, name: CHARACTERS[id].name, icon: CHARACTERS[id].icon,
      messages: state.individualMessages[id],
      subtitle: HABIT_AREAS[id] || '',
    })),
  ];
  const cardHtml = chats.map((c, idx) => {
    const avatarClass = c.id === 'group' ? 'avatar-group' : `avatar-${c.id}`;
    const cardClass = c.id === 'group' ? 'card-group' : `card-${c.id}`;
    const u = state.unread[c.id] || 0;
    const delay = (idx * 0.05).toFixed(2);
    const tag = c.subtitle;
    const last = c.messages[c.messages.length - 1];
    let prev = '';
    if (last) {
      if (c.id === 'group') { const p = last.from === 'user' ? 'You' : (CHARACTERS[last.char]?.name||''); prev = `${p}: ${last.text.replace(/\n/g,' ')}`; }
      else prev = last.from === 'user' ? `You: ${last.text}` : last.text.replace(/\n/g,' ');
    }
    if (prev.length > 35) prev = prev.substring(0, 35) + '…';
    return `<div class="chat-card ${cardClass}" data-chat="${c.id}" style="animation-delay:${delay}s">
      <div class="card-blob-wrap">
        <div class="card-avatar ${avatarClass}">${CHAR_SVGS[c.id] || c.icon}</div>
        <div class="card-name">${c.name}</div>
      </div>
      ${prev ? `<div class="card-preview">${escapeHtml(prev)}</div>` : ''}
      <div class="card-tag">${tag}</div>
      <div class="card-unread ${u > 0 ? '' : 'hidden'}">${u > 0 ? (u > 9 ? '9+' : u) : ''}</div>
    </div>`;
  }).join('');
  chatlistContent.innerHTML = `<div class="chat-grid">${cardHtml}</div>`;
  chatlistContent.querySelectorAll('.chat-card').forEach(r => {
    r.addEventListener('click', () => { state.unread[r.dataset.chat] = 0; navigateTo('chat', r.dataset.chat); });
  });
}

// ————— Chat Screen —————
function setupChatScreen(chatId) {
  if (chatId === 'group') {
    chatHeaderName.textContent = 'The Desk';
    chatHeaderIcon.innerHTML = CHAR_SVGS.group || '';
  } else {
    const habit = HABIT_AREAS[chatId] || '';
    chatHeaderName.innerHTML = `${escapeHtml(CHARACTERS[chatId].name)}${habit ? `<span class="chat-header-habit">${escapeHtml(habit)}</span>` : ''}`;
    chatHeaderIcon.innerHTML = CHAR_SVGS[chatId] || '';
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
    const response = await backend.sendMessage(chatId, text);
    removeTypingIndicator();
    if (response?.messages) {
      for (const r of response.messages) {
        showTypingIndicator(r.character || chatId);
        await sleep(1200 + Math.random() * 1000);
        removeTypingIndicator();
        if (chatId === 'group') addGroupMessage(r.character, r.text);
        else addIndividualMessage(r.character || chatId, r.text);
      }
    } else {
      offlineResponse(chatId);
    }
    return;
  }
  offlineResponse(chatId);
}

function offlineResponse(chatId) {
  const cid = chatId !== 'group' ? chatId : charIds[Math.floor(Math.random() * charCount)];
  showTypingIndicator(cid);
  setTimeout(() => {
    removeTypingIndicator();
    const text = 'Connect to the server with cameras for live responses.';
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

function toggleDrawer() {
  drawerOpen = !drawerOpen;
  cameraDrawer.classList.toggle('open', drawerOpen);
  if (drawerOpen) {
    setupDrawerFeeds();
    startDrawerPolling();
  } else {
    stopDrawerPolling();
  }
}

function setupDrawerFeeds() {
  if (!state.liveMode || !backend.cameraOk) {
    drawerFeeds.innerHTML = '<div class="drawer-camera-feed"><div class="camera-offline-msg">No camera connected</div></div>';
    return;
  }
  const multi = backend.cameraIndices.length > 1;
  drawerFeeds.className = multi ? 'multi-cam' : '';
  drawerFeeds.innerHTML = backend.cameraIndices.map((idx, i) => `
    <div class="drawer-camera-feed">
      <div class="camera-label">Cam ${i + 1}</div>
      <img src="${backend.baseUrl}/api/video_feed/${idx}" alt="Cam ${idx}" class="live-video-img"
        onerror="this.style.display='none';this.nextElementSibling.style.display=''"
        onload="this.nextElementSibling.style.display='none'">
      <div class="camera-offline-msg">Connecting...</div>
    </div>`).join('');
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
    const r = await fetch(`${backend.baseUrl}/api/rules`);
    const data = await r.json();
    availableObjects = data.available_objects || [];
    renderRulesEditor(data);
  } catch (e) {
    settingsContent.innerHTML = `<div class="settings-section">
      <div class="settings-info">Failed to load config.</div></div>`;
  }
}

function renderRulesEditor(data) {
  const zones = data.danger_zones || {};
  const edge  = data.edge_proximity || {};
  const zoneKeys = Object.keys(zones);

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
      renderRulesEditor(data);
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
    renderRulesEditor(data);
  });

  // Save — store the current state back as _settingsData so saveRules can use it
  window._settingsData = data;
  const saveBtn = $('#btn-save-rules');
  if (saveBtn) saveBtn.addEventListener('click', saveRules);
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

async function init() {
  updateStatusBarTime();
  setInterval(updateStatusBarTime, 10000);

  backend = new Backend();
  const ok = await backend.connect();
  if (ok) {
    state.liveMode = true;
    console.log('[Desk Talk] Connected —', backend.llmLabel, '— cameras:', backend.cameraIndices);
  } else {
    state.liveMode = false;
    console.log('[Desk Talk] No server — demo mode');
    startSimulation();
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
