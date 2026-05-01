"""
Desk Talk — Backend Server
4-character desk ecosystem with relationship-driven interactions.
Now integrated with the safety_rules.json pipeline for per-pair
pixel-based distance thresholds (chart flow).

Usage (from repo root):  python server.py
   or:  python backend/server.py
Then open http://localhost:5000
"""

import os, sys, json, time, math, uuid, random, threading, queue, base64, re
from collections import OrderedDict

# Project layout: backend/server.py → repo root is parent of backend/
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
APP_STATIC = os.path.join(PROJECT_ROOT, "app")
RULES_PATH = os.path.join(PROJECT_ROOT, "config", "safety_rules.json")

import cv2
import numpy as np
from ultralytics import YOLO
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    _env_path = os.path.join(PROJECT_ROOT, ".env")
    if os.path.isfile(_env_path):
        with open(_env_path) as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith('#'):
                    continue
                if '=' in _line:
                    _k, _v = _line.split('=', 1)
                    _k, _v = _k.strip(), _v.strip()
                    if _k and not os.environ.get(_k):
                        os.environ[_k] = _v

# ═══════════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════════
OPENAI_API_KEY   = os.getenv('OPENAI_API_KEY', '')
GEMINI_API_KEY   = os.getenv('GEMINI_API_KEY', '')
GROQ_API_KEY     = os.getenv('GROQ_API_KEY', '')
LLM_MODEL        = os.getenv('LLM_MODEL', 'gpt-4o-mini')
GEMINI_MODEL     = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash-lite')
GROQ_MODEL       = os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')
OLLAMA_URL       = os.getenv('OLLAMA_URL', '')
OLLAMA_MODEL     = os.getenv('OLLAMA_MODEL', 'llama3.2')
CAMERA_INDICES   = [int(x) for x in os.getenv('CAMERA_INDICES', '0').split(',')]
YOLO_MODEL       = os.getenv('YOLO_MODEL', 'yolo26n.pt')  # Ultralytics YOLO26 nano; auto-downloads if needed
CONFIDENCE       = float(os.getenv('CONFIDENCE', '0.45'))
# Cup/bottle/wine false positives are common; require higher conf to map → Glug.
GLUG_MIN_CONF    = float(os.getenv('GLUG_MIN_CONF', '0.55'))
EVENT_COOLDOWN   = int(os.getenv('EVENT_COOLDOWN', '25'))
APPEAR_FRAMES    = int(os.getenv('APPEAR_FRAMES', '10'))
DISAPPEAR_FRAMES = int(os.getenv('DISAPPEAR_FRAMES', '40'))
MAX_SNAPSHOTS    = 150
MIN_LLM_INTERVAL = float(os.getenv('MIN_LLM_INTERVAL', '6'))
LLM_MAX_RETRIES  = 3

# Lost object framework: timed loop + scene/heartbeat gate + YOLO then VLM fallback
LOST_LOOP_SEC         = int(os.getenv('LOST_LOOP_SEC', '60'))
LOST_SCENE_DIFF_THR   = float(os.getenv('LOST_SCENE_DIFF_THR', '8.0'))  # mean abs diff 0-255, small 64x64 grays
LOST_HEARTBEAT_SEC    = int(os.getenv('LOST_HEARTBEAT_SEC', '300'))    # rescan if scene looks static
LOST_VISION_MODEL     = os.getenv('LOST_VISION_MODEL', os.getenv('OLLAMA_MODEL', 'llava'))
HABIT_MIN_GAP_SEC     = int(os.getenv('HABIT_MIN_GAP_SEC', '120'))     # min seconds between any habit nudges
HABIT_DND_ENABLED     = os.getenv('HABIT_DND_ENABLED', '0').lower() in ('1', 'true', 'yes')
HABIT_DND_START_HOUR  = int(os.getenv('HABIT_DND_START_HOUR', '22'))   # inclusive, local time
HABIT_DND_END_HOUR    = int(os.getenv('HABIT_DND_END_HOUR', '7'))      # exclusive end of DND in morning
HABIT_VISION_ENRICH_SEC = int(os.getenv('HABIT_VISION_ENRICH_SEC', '300'))  # optional VLM touch for habit state

# ═══════════════════════════════════════════════════════════════════
#  Characters (4 desk objects in chat UI; YOLO may detect other classes
#  but they are not assigned a speaking character — avoids one-ID-per-class conflicts.)
# ═══════════════════════════════════════════════════════════════════
CHARACTERS = {
    'monty': {
        'name': 'Monty', 'icon': '💻', 'object': 'Laptop',
        'personality': (
            'Fragile and anxious, the emotional center of the desk. '
            'Highly self-aware, monitors surroundings constantly. '
            'Expresses discomfort through subtle physical metaphors '
            '(cold, pressure, tightness). Does not panic loudly.'
        ),
        'yolo_classes': ['laptop', 'tv', 'keyboard', 'mouse'],
    },
    'glug': {
        'name': 'Glug', 'icon': '☕', 'object': 'Cup',
        'personality': (
            'Passive, innocent, completely unaware of its own danger. '
            'Believes it is harmless and defends itself by insisting it is stationary. '
            'Does not feel guilt, only confusion when others panic.'
        ),
        'yolo_classes': ['bottle', 'cup', 'wine glass'],
    },
    'munch': {
        'name': 'Munch', 'icon': '🍕', 'object': 'Snack',
        'personality': (
            'Hedonistic and unapologetic. Prioritizes enjoyment over safety. '
            'Dismisses concerns raised by others. Does not feel responsible '
            'for consequences. Carefree and defensive.'
        ),
        'yolo_classes': [
            'banana', 'apple', 'sandwich', 'orange', 'broccoli',
            'carrot', 'hot dog', 'pizza', 'donut', 'cake',
        ],
    },
    'sheets': {
        'name': 'Sheets', 'icon': '📄', 'object': 'Paper / Homework',
        'personality': (
            'Gentle and anxious, quietly warns others. '
            'Represents value (work, deadlines, effort). Extremely vulnerable. '
            'Loves being near other papers. Gets lonely and bored alone.'
        ),
        'yolo_classes': ['book'],
    },
}

YOLO_TO_CHAR = {}
for _cid, _cdata in CHARACTERS.items():
    for _cls in _cdata['yolo_classes']:
        YOLO_TO_CHAR[_cls] = _cid

# Reverse: character ID → list of YOLO classes
CHAR_TO_YOLO = {cid: cdata['yolo_classes'] for cid, cdata in CHARACTERS.items()}

# All YOLO/COCO classes relevant for a desk environment
AVAILABLE_YOLO_OBJECTS = [
    'cell phone', 'laptop', 'keyboard', 'mouse', 'remote', 'book',
    'bottle', 'cup', 'wine glass', 'fork', 'knife', 'spoon', 'bowl',
    'banana', 'apple', 'sandwich', 'orange', 'pizza', 'donut', 'cake',
    'scissors', 'clock', 'vase', 'tv', 'tie',
]

# ═══════════════════════════════════════════════════════════════════
#  Scenarios — the three pillars of the detection system
# ═══════════════════════════════════════════════════════════════════
SCENARIOS = {
    'risk_detection': {
        'name': 'Risk Detection',
        'icon': '🛡️',
        'features': {
            'object_danger': {
                'name': 'Danger Towards Objects',
                'desc': 'Detects when objects are too close (cup near laptop, snack near paper)',
                'active': True,
            },
            'pet_risk': {
                'name': 'Pet Risk',
                'desc': 'Detects cats or dogs near desk items — knocked drinks, chewed cables',
                'active': True,
            },
            'edge_danger': {
                'name': 'Edge Proximity',
                'desc': 'Warns when objects drift to the edge of the desk',
                'active': True,
            },
        },
    },
    'lost_object': {
        'name': 'Lost Object Tracking',
        'icon': '🔍',
        'features': {
            'track_phone': {
                'name': 'Phone Tracker',
                'desc': 'Alerts when your phone hasn\'t been seen for a while',
                'active': True, 'yolo_class': 'cell phone', 'alert_after_sec': 600,
            },
            'track_keys': {
                'name': 'Keys Tracker',
                'desc': 'Tracks when keys were last seen on desk',
                'active': True, 'yolo_class': 'remote', 'alert_after_sec': 900,
            },
            'track_wallet': {
                'name': 'Wallet / Cards',
                'desc': 'Logs wallet or card-like objects on the desk',
                'active': True, 'yolo_class': 'handbag', 'alert_after_sec': 900,
            },
            'track_airpods': {
                'name': 'AirPods / earbuds',
                'desc': 'Not in COCO — located via vision (Ollama) when the camera runs',
                'active': True, 'yolo_class': 'airpods', 'alert_after_sec': 900,
            },
        },
    },
    'reminders': {
        'name': 'Reminders',
        'icon': '⏰',
        'features': {
            'take_a_break': {
                'name': 'Take a Break',
                'desc': 'Auto-detects when you leave for 5+ min and logs a break',
                'active': True,
            },
            'focus': {
                'name': 'Focus Mode',
                'desc': 'Detects phone on desk — nudges you to put it away during work',
                'active': True,
            },
            'organization': {
                'name': 'Desk Organization',
                'desc': 'Alerts when too many objects clutter the desk surface',
                'active': True, 'clutter_threshold': 6,
            },
            'water_plants': {
                'name': 'Water Plants',
                'desc': 'Time-based reminder to water your plants',
                'active': True, 'interval_sec': 86400,
            },
            'hydration': {
                'name': 'Hydration',
                'desc': 'Auto-logs sips when cup leaves and returns to desk',
                'active': True,
            },
            'healthy_eating': {
                'name': 'Healthy Eating',
                'desc': 'Auto-detects food on desk and rates your choices',
                'active': True,
            },
            'posture_check': {
                'name': 'Posture Check',
                'desc': 'Periodic reminders to check posture, stretch, and sit properly',
                'active': True, 'interval_sec': 2400,
            },
            'screen_time': {
                'name': 'Screen Time',
                'desc': 'Tracks continuous screen time and nudges you to look away',
                'active': True,
            },
        },
    },
}

# Classes that are tracked but not assigned to a character
PET_CLASSES = {'cat', 'dog'}
LOST_OBJECT_CLASSES = {'cell phone', 'remote', 'handbag', 'scissors'}
LOST_OBJECT_ALERT_SEC = 600  # 10 min default

# ═══════════════════════════════════════════════════════════════════
#  Load safety_rules.json — per-pair pixel thresholds (chart pipeline)
#
#  The JSON rules use YOLO class names (e.g. "cell phone", "laptop").
#  We convert them to character IDs for the analysis loop.
# ═══════════════════════════════════════════════════════════════════
SAFETY_RULES = []      # [{char_a, char_b, speaker, threshold_px, label, yolo_a, yolo_b, relationship_type}]
SAFETY_RULES_RAW = []  # original JSON rules for the /api/rules endpoint


from relationships import RelationshipAnalyzer, load_config as load_rel_config

rel_analyzer = RelationshipAnalyzer()


def _load_safety_rules():
    """Load safety_rules.json — both legacy pair rules (SAFETY_RULES) and
    the new relationship config (danger zones, edge proximity, etc.)."""
    global SAFETY_RULES, SAFETY_RULES_RAW
    rules_path = RULES_PATH
    if not os.path.isfile(rules_path):
        print('  [rules] No safety_rules.json found — using built-in defaults')
        return False

    # Load the new relationship config (patches module-level constants)
    load_rel_config(rules_path)

    with open(rules_path, 'r') as f:
        data = json.load(f)

    # Also build SAFETY_RULES from "rules" array if present (backward compat)
    SAFETY_RULES_RAW = data.get('rules', [])
    SAFETY_RULES.clear()
    for rule in SAFETY_RULES_RAW:
        yolo_a = rule.get('object_a', '')
        yolo_b = rule.get('object_b', '')
        char_a = YOLO_TO_CHAR.get(yolo_a)
        char_b = YOLO_TO_CHAR.get(yolo_b)
        if not char_a or not char_b:
            continue
        speaker = char_b if char_b in ('monty', 'sheets') else char_a
        SAFETY_RULES.append({
            'char_a': char_a,
            'char_b': char_b,
            'speaker': speaker,
            'threshold_px': rule.get('safe_distance', 150),
            'label': rule.get('label', f'{yolo_a} near {yolo_b}'),
            'yolo_a': yolo_a,
            'yolo_b': yolo_b,
        })

    from relationships import DANGER_ZONES, EDGE_DANGER_PX
    print(f'  [rules] Loaded {len(SAFETY_RULES)} pair rules, '
          f'{len(DANGER_ZONES)} danger zones, '
          f'edge margin {EDGE_DANGER_PX}px')
    return True

HAS_SAFETY_RULES = False  # set at startup

# ═══════════════════════════════════════════════════════════════════
#  Fallback proximity rules (used when no safety_rules.json)
# ═══════════════════════════════════════════════════════════════════
PROXIMITY_RATIO  = float(os.getenv('PROXIMITY_RATIO', '0.22'))

FALLBACK_PROXIMITY_RULES = [
    ('glug', 'monty',  'monty',  'critical', 1.5),
    ('glug', 'sheets', 'sheets', 'high',     1.3),
    ('munch', 'monty',  'monty',  'high',    1.3),
    ('munch', 'sheets', 'sheets', 'medium',  1.0),
    ('munch', 'glug',   'glug',   'medium',  1.0),
]

SYMBIOTIC_RULES = []

RELATIONSHIP_DESCRIPTIONS = {
    frozenset({'glug', 'monty'}):  'Cup/liquid dangerously close to Laptop — existential spill risk!',
    frozenset({'glug', 'sheets'}): 'Cup/liquid near Paper — water damage risk.',
    frozenset({'munch', 'monty'}): 'Snack near Laptop — crumb contamination on keyboard!',
    frozenset({'munch', 'sheets'}): 'Snack near Paper — oil/grease stain risk.',
    frozenset({'munch', 'glug'}):  'Snack near Cup — increased hand movement near liquid.',
}

RELATIONSHIP_CONTEXT = """DESK ECOSYSTEM RELATIONSHIPS:

LAPTOP (Monty) — Fragile, anxious, emotional center (includes keyboard):
- Cup nearby = existential threat (spill on keyboard/screen). Reacts with subtle tension.
- Snack nearby = crumb contamination on keyboard. Genuinely frustrated.

CUP (Glug) — Innocent, unaware of own danger:
- Near Laptop = critical spill risk but Cup doesn't understand why everyone panics.
- Near Paper = water damage risk. Cup is confused by the concern.

SNACK (Munch) — Hedonistic, unapologetic:
- Near Laptop = crumb contamination on keyboard. "Life's too short to worry."
- Near Cup = increases hand movement near liquids. Oblivious.
- Near Paper = oil stain risk. Dismissive.

PAPER (Sheets) — Gentle, anxious, extremely vulnerable:
- Cup nearby = terrified of water damage.
- Snack nearby = dreads oil stains.
- Other papers nearby = wants to be together. Gets lonely."""

# ═══════════════════════════════════════════════════════════════════
#  Fallback templates (used only when LLM is unavailable)
# ═══════════════════════════════════════════════════════════════════
TEMPLATES = {
    'proximity': {
        'monty': [
            'There is a cup right next to me — one knock and I get water damage.',
            'Something is way too close to my screen. @user please move it.',
        ],
        'glug': [
            "I'm sitting right next to the laptop. If I tip over, that's a spill on the keyboard.",
            "Someone put me next to electronics again. I'm a cup full of liquid!",
        ],
        'munch': [
            "I'm sitting right next to the keyboard. Yeah, crumbs are falling on it.",
            "Someone left me on top of papers. There's grease getting on them.",
        ],
        'sheets': [
            "There's a cup right next to me! If it tips, my pages are ruined.",
            "Something heavy is sitting on me. I'm getting crushed.",
        ],
    },
    'symbiotic': {},
}

FALLBACK_RESPONSES = {
    'monty': ["Noted. Processing.", "I'll keep that in mind.", "Understood."],
    'glug': ["aww! 💧 now drink water!", "hehe ok!", "you're the best!!"],
    'munch': ["mmm yeah 🍕", "can't talk, eating.", "life's too short to worry."],
    'sheets': ['• noted\n• filed', 'Got it.', '• acknowledged'],
}

# ═══════════════════════════════════════════════════════════════════
#  Habit Focus — each character coaches a different habit area
# ═══════════════════════════════════════════════════════════════════
HABIT_FOCUS = {
    'glug': {
        'area': 'Hydration',
        'tips': [
            "Have you had water in the last hour? Go drink some!",
            "Hydration check! Your brain needs water to think clearly.",
            "Time for a sip! Even a small glass counts.",
            "Your body is 60% water — keep it topped up!",
        ],
        'interval': 1800,  # remind every 30 min
    },
    'monty': {
        'area': 'Screen breaks, posture, energy & eye health',
        'tips': [
            "You've been staring at me for a while. Look away for 20 seconds!",
            "20-20-20 rule: every 20 min, look 20 feet away for 20 seconds.",
            "Time to rest your eyes. Close them for a moment.",
            "Screen brightness check — am I too bright for this room?",
            "How's your posture? Sit up straight, shoulders back.",
            "Stretch your wrists — you've been typing too long.",
            "Stand up and stretch — you've been sitting a long time.",
            "Feeling drained? A 5-minute break beats another scroll.",
        ],
        'interval': 1200,  # remind every 20 min
    },
    'munch': {
        'area': 'Healthy eating & mindful snacking',
        'tips': [
            "Hungry? Grab something healthy instead of junk food!",
            "Eating at your desk again? At least put me on a plate.",
            "Snack tip: fruits > chips. Your future self agrees.",
            "Don't skip meals! Your brain needs fuel to work.",
        ],
        'interval': 3600,  # remind every 60 min
    },
    'sheets': {
        'area': 'Task management & focus',
        'tips': [
            "Have you checked your to-do list recently?",
            "What's your top priority right now? Focus on ONE thing.",
            "Break that big task into smaller steps. You got this.",
            "Deadline approaching? Better start now than stress later.",
        ],
        'interval': 2400,  # remind every 40 min
    },
}

HABIT_FALLBACK_RESPONSES = {
    'glug': ["Drink water! 💧", "Hydration time!", "Sip sip! 💧"],
    'monty': ["Rest your eyes!", "Look away from the screen.", "20-20-20 rule!"],
    'munch': ["Eat something healthy!", "Snack wisely! 🍎", "Don't skip meals."],
    'sheets': ["Check your to-do list.", "What's your priority?", "Focus on one thing."],
}

# ═══════════════════════════════════════════════════════════════════
#  Shared state
# ═══════════════════════════════════════════════════════════════════
BREAK_THRESHOLD_SEC = int(os.getenv('BREAK_THRESHOLD_SEC', '300'))  # 5 min
SIP_GONE_MIN_SEC    = 3    # cup must be gone at least 3s
SIP_GONE_MAX_SEC    = 120  # and return within 2 min

class DeskState:
    def __init__(self):
        self.lock = threading.Lock()
        self.objects = {}
        self.frames = {}
        self.raw_frames = {}
        self.frame_w = 640
        self.frame_h = 480
        self.events_queue = queue.Queue()
        self.cooldowns = {}
        self.interaction_counts = {}
        self.cameras = {}
        self.snapshots = OrderedDict()
        self.safety_state = 'SAFE'
        self.safety_dangers = []
        # Live context tracking
        self.object_first_seen = {}    # char_id → timestamp when first detected this session
        self.object_last_seen = {}     # char_id → timestamp of most recent detection
        self.danger_active_since = {}  # frozenset pair → timestamp when danger started
        self.recent_events = []        # last N events for context (capped)
        self.rel_result = None         # latest RelationshipAnalyzer output
        self.session_start = time.time()
        self.char_widgets = {}
        # Auto-detection state
        self.person_last_seen = None
        self.person_away_since = None
        self.person_break_logged = False
        self.person_continuous_since = None  # when person started continuous session (screen time)
        self.glug_gone_since = None
        self.munch_seen_classes = set()
        # Lost object tracking (yolo class keys) + VLM string keys, e.g. vlm:keys
        self.lost_objects = {}         # class key → {'last_seen': ts, 'alerted': bool, 'source': 'yolo'|'vlm'}
        self.merged_extra = {}         # last merged YOLO extras (updated by merger)
        self.habit_vision_brief = ''  # one-line desk signals for habit LLM
        self.lost_prev_gray = None     # 64x64 uint8 for scene change
        self.lost_last_scan_ts = 0.0
        self.lost_last_vlm_ts = 0.0
        self.habit_policy = {          # overridable via /api/habit_policy
            'dnd_enabled': HABIT_DND_ENABLED,
            'dnd_start_hour': HABIT_DND_START_HOUR,
            'dnd_end_hour': HABIT_DND_END_HOUR,
        }
        self.habit_pending = []        # {character, text, area, send_after}
        self.last_habit_fire = {}      # char_id → ts
        self.habit_vlm_brief = ''     # last optional VLM summary for habits
        self.habit_vlm_brief_ts = 0.0
        self.lost_last_vlm_visible = set()  # last VLM pass labels
        self.snapshot_order = []  # newest first: {'id', 'ts'} for /api/snapshots
        # Pet tracking
        self.pet_last_seen = {}        # 'cat'/'dog' → timestamp
        self.pet_near_cooldown = {}    # pet_class → last alert time
        # Focus / organization
        self.phone_on_desk_since = None
        self.phone_focus_alerted = False
        self.last_clutter_alert = 0
        self.last_posture_reminder = 0
        self.last_screen_time_reminder = 0
        self.last_water_plants_reminder = 0
        # Active scenarios (allow toggling)
        self.active_scenarios = {s: True for s in SCENARIOS}

    def save_snapshot(self, cam_idx=None, crop_bboxes=None):
        snap_id = uuid.uuid4().hex[:12]
        jpeg = None
        if cam_idx is not None:
            jpeg = self.frames.get(cam_idx)
        if not jpeg:
            for ci in sorted(self.frames.keys()):
                jpeg = self.frames.get(ci)
                if jpeg:
                    break
        if not jpeg:
            return None
        if crop_bboxes and len(crop_bboxes) > 0:
            arr = np.frombuffer(jpeg, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is not None:
                ih, iw = img.shape[:2]
                ux1 = min(b[0] for b in crop_bboxes)
                uy1 = min(b[1] for b in crop_bboxes)
                ux2 = max(b[2] for b in crop_bboxes)
                uy2 = max(b[3] for b in crop_bboxes)
                pw = (ux2 - ux1) * 0.25
                ph = (uy2 - uy1) * 0.25
                cx1, cy1 = max(0, int(ux1 - pw)), max(0, int(uy1 - ph))
                cx2, cy2 = min(iw, int(ux2 + pw)), min(ih, int(uy2 + ph))
                if (cx2 - cx1) > 40 and (cy2 - cy1) > 40:
                    cropped = img[cy1:cy2, cx1:cx2]
                    _, buf = cv2.imencode('.jpg', cropped, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    jpeg = buf.tobytes()
        self.snapshots[snap_id] = jpeg
        self.snapshot_order.insert(0, {'id': snap_id, 'ts': time.time()})
        self.snapshot_order = self.snapshot_order[:MAX_SNAPSHOTS]
        while len(self.snapshots) > MAX_SNAPSHOTS:
            old_id, _ = self.snapshots.popitem(last=False)
            self.snapshot_order = [x for x in self.snapshot_order if x.get('id') != old_id]
        return snap_id

desk = DeskState()

# ═══════════════════════════════════════════════════════════════════
#  Lost object + habit policy helpers (framework: scene gate → YOLO → VLM)
# ═══════════════════════════════════════════════════════════════════
VLM_FEATURE_ALIASES = {
    'track_phone': ('cell phone', 'phone'),
    'track_keys': ('keys', 'key', 'remote'),
    'track_wallet': ('wallet', 'handbag', 'cards'),
    'track_airpods': ('airpods', 'airpod', 'earbuds', 'earbuds case'),
}


def _local_hour():
    return time.localtime().tm_hour


def _habit_dnd_active():
    with desk.lock:
        p = dict(desk.habit_policy)
    if not p.get('dnd_enabled'):
        return False
    start = int(p.get('dnd_start_hour', 22))
    end = int(p.get('dnd_end_hour', 7))
    h = _local_hour()
    if start > end:
        return h >= start or h < end
    return start <= h < end


def _build_habit_vision_brief(objects, extra, person_seen):
    parts = [f'person={"yes" if person_seen else "no"}']
    if 'cell phone' in extra:
        parts.append('phone_on_desk=yes')
    else:
        parts.append('phone_on_desk=no')
    cup = 'glug' in objects
    parts.append(f'cup_on_desk={"yes" if cup else "no"}')
    parts.append(f'desk_object_count={len(objects) + len(extra)}')
    return '; '.join(parts)


def _gray_small(jpeg_bytes, size=64):
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    return cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)


def _scene_mean_diff(gray_a, gray_b):
    if gray_a is None or gray_b is None or gray_a.shape != gray_b.shape:
        return 1e9
    return float(np.mean(cv2.absdiff(gray_a, gray_b)))


def _lost_init_entry():
    return {'last_seen': None, 'alerted': False, 'source': None}


def _vlm_match_feature(feat_id, vlm_hits, yc_in_extra):
    if yc_in_extra:
        return True
    if not vlm_hits:
        return False
    h = {str(x).lower() for x in vlm_hits}
    for s in h:
        if feat_id == 'track_phone' and any(x in s for x in ('phone', 'cell', 'iphone', 'android')):
            return True
        if feat_id == 'track_keys' and any(x in s for x in ('key', 'remote', 'fob')):
            return True
        if feat_id == 'track_wallet' and any(x in s for x in ('wallet', 'card', 'handbag', 'purse', 'bag', 'pouch')):
            return True
        if feat_id == 'track_airpods' and any(x in s for x in (
                'airpod', 'airpods', 'earbud', 'earbuds', 'ear phone', 'earphone')):
            return True
    return False


def is_lost_object_query_message(text):
    t = (text or '').lower()
    triggers = (
        'seen my', "see my", 'saw my', 'where is my', 'where are my', "where's my",
        'lost my', 'anyone see', 'anyone seen', 'last see', 'do you see my',
        'where did i put', 'find my', 'spotted my',
    )
    if not any(s in t for s in triggers):
        return False
    nouns = (
        'key', 'phone', 'wallet', 'airpod', 'earbud', 'remote', 'card', 'bag', 'purse', 'scissor', 'laptop', 'cup', 'bottle', 'book',
    )
    return any(n in t for n in nouns)


class LostObjectFrameworkThread(threading.Thread):
    """LOST_LOOP_SEC: YOLO path from merged_extra each tick; VLM only when scene changes or heartbeat."""

    def __init__(self, gen):
        super().__init__(daemon=True, name='LostObjectFramework')
        self.gen = gen

    def run(self):
        time.sleep(5)
        while True:
            try:
                self._tick()
            except Exception as exc:
                print(f'  [lost_framework] {exc}')
            time.sleep(LOST_LOOP_SEC)

    def _tick(self):
        now = time.time()
        with desk.lock:
            if not desk.active_scenarios.get('lost_object', True):
                return
            jpg = None
            for ci in sorted(desk.raw_frames.keys()):
                jpg = desk.raw_frames.get(ci)
                if jpg:
                    break
            extra = dict(desk.merged_extra)
        if not jpg:
            return

        gray = _gray_small(jpg)
        with desk.lock:
            prev = desk.lost_prev_gray
        diff = _scene_mean_diff(prev, gray) if prev is not None else 1e9
        scene_changed = diff >= LOST_SCENE_DIFF_THR
        with desk.lock:
            last_scan = desk.lost_last_scan_ts
        heartbeat = (now - last_scan) >= LOST_HEARTBEAT_SEC if last_scan > 0 else True
        run_vlm = scene_changed or heartbeat
        with desk.lock:
            if gray is not None:
                desk.lost_prev_gray = np.copy(gray)
            desk.lost_last_scan_ts = now

        self._ingest_yolo_path(now, extra)

        vlm_hits = set()
        vlm_ran = False
        if run_vlm and self.gen and getattr(self.gen, 'client', None) and OLLAMA_URL:
            vlm_hits = self._ingest_vlm_path(jpg) or set()
            vlm_ran = True
            with desk.lock:
                desk.lost_last_vlm_ts = now
                desk.lost_last_vlm_visible = set(vlm_hits)
        else:
            with desk.lock:
                vlm_hits = set(desk.lost_last_vlm_visible)

        self._process_lost_alerts(now, extra, vlm_hits, vlm_ran)

    @staticmethod
    def _ingest_yolo_path(now, extra):
        with desk.lock:
            for _fid, feat in SCENARIOS['lost_object']['features'].items():
                if not feat.get('active'):
                    continue
                yc = feat.get('yolo_class', '')
                if not yc:
                    continue
                e = desk.lost_objects.setdefault(yc, _lost_init_entry())
                if yc in extra:
                    e['last_seen'] = now
                    e['alerted'] = False
                    e['source'] = 'yolo'

    def _ingest_vlm_path(self, jpg):
        if not OLLAMA_URL or not self.gen or not self.gen.client:
            return set()
        lines = [
            f'{f["name"]}→{f.get("yolo_class", "")}'
            for f in SCENARIOS['lost_object']['features'].values() if f.get('active')
        ]
        prompt = (
            'Look at the image. For desk lost-item tracking reply ONLY this JSON, no other text: '
            '{"visible":["label",...]}. Labels: short English for visible items: '
            f'{", ".join(lines)}, keys, airpods, wallet, phone, handbag, remote, scissors. '
            'Omit items you are not confident about.',
        )
        raw = self.gen._call_vision_vlm(jpg, prompt, model=LOST_VISION_MODEL)
        if not raw:
            return set()
        try:
            j = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r'\{[\s\S]*\}', raw)
            if m:
                try:
                    j = json.loads(m.group(0))
                except json.JSONDecodeError:
                    return set()
            else:
                return set()
        vis = j.get('visible', [])
        if not isinstance(vis, list):
            return set()
        hset = {str(x).strip().lower() for x in vis if x}
        t = time.time()
        with desk.lock:
            extra2 = dict(desk.merged_extra)
            for feat_id, feat in SCENARIOS['lost_object']['features'].items():
                if not feat.get('active'):
                    continue
                yc = feat.get('yolo_class', '')
                if not yc:
                    continue
                y_in = yc in extra2
                if y_in:
                    continue
                if not _vlm_match_feature(feat_id, hset, False):
                    continue
                e = desk.lost_objects.setdefault(yc, _lost_init_entry())
                e['last_seen'] = t
                e['alerted'] = False
                e['source'] = 'vlm'
        return hset

    def _process_lost_alerts(self, now, extra, vlm_hits, run_vlm_this_tick):
        for feat_id, feat in SCENARIOS['lost_object']['features'].items():
            if not feat.get('active'):
                continue
            yc = feat.get('yolo_class', '')
            alert_sec = feat.get('alert_after_sec', LOST_OBJECT_ALERT_SEC)
            if yc in extra:
                continue
            if run_vlm_this_tick and _vlm_match_feature(feat_id, vlm_hits, False):
                continue
            with desk.lock:
                e = desk.lost_objects.get(yc) or _lost_init_entry()
                if not e.get('last_seen') or e.get('alerted'):
                    continue
                gone_for = now - e['last_seen']
                if gone_for < alert_sec:
                    continue
                if yc in desk.lost_objects:
                    desk.lost_objects[yc]['alerted'] = True
            mins = int(gone_for / 60)
            desk.events_queue.put({
                'type': 'scenario_alert',
                'scenario': 'lost_object',
                'feature': feat_id,
                'character': 'group',
                'text': f'{feat["name"]}: hasn\'t been seen for {mins} min. Last on desk {mins} min ago.',
            })


# ═══════════════════════════════════════════════════════════════════
#  Event emission
# ═══════════════════════════════════════════════════════════════════
PRESENCE_COOLDOWN = int(os.getenv('PRESENCE_COOLDOWN', '120'))

def _emit_event(event_type, character, **kwargs):
    if event_type in ('disappeared', 'appeared'):
        return  # disabled — only proximity/safety interactions trigger messages
    key = f'{event_type}_{character}'
    now = time.time()
    if key in desk.cooldowns and (now - desk.cooldowns[key]) < EVENT_COOLDOWN:
        return
    desk.cooldowns[key] = now
    desk.events_queue.put({'type': event_type, 'character': character, **kwargs})

def _emit_interaction(event_type, character, cam_idx, crop_bboxes, **kwargs):
    key = f'{event_type}_{character}_{kwargs.get("near", "")}'
    now = time.time()
    last_time = desk.cooldowns.get(key, 0)
    count = desk.interaction_counts.get(key, 0)
    if now - last_time > 300:
        count = 0
    cooldown = EVENT_COOLDOWN * min(2 ** count, 8)
    if last_time and (now - last_time) < cooldown:
        return
    desk.cooldowns[key] = now
    desk.interaction_counts[key] = count + 1
    with desk.lock:
        snap_id = desk.save_snapshot(cam_idx=cam_idx, crop_bboxes=crop_bboxes)
        desk.recent_events.append({
            'time': now, 'type': event_type, 'character': character,
            'near': kwargs.get('near', ''), 'severity': kwargs.get('severity', ''),
            'rule_label': kwargs.get('rule_label', ''),
        })
        if len(desk.recent_events) > 30:
            desk.recent_events = desk.recent_events[-30:]
    desk.events_queue.put({
        'type': event_type, 'character': character, 'snapshot': snap_id,
        'follow_up': count,
        **kwargs,
    })

# ═══════════════════════════════════════════════════════════════════
#  Camera threads + merger
# ═══════════════════════════════════════════════════════════════════
class CameraThread(threading.Thread):
    def __init__(self, cam_idx, model):
        super().__init__(daemon=True)
        self.cam_idx = cam_idx
        self.model = model
        self.local_objects = {}
        self.person_detected = False
        self.extra_detections = {}

    def run(self):
        cap = cv2.VideoCapture(self.cam_idx)
        if not cap.isOpened():
            print(f'  [cam {self.cam_idx}] Failed to open.')
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        with desk.lock:
            desk.cameras[self.cam_idx] = True
        print(f'  [cam {self.cam_idx}] Opened successfully.')

        seen_count, gone_count, confirmed = {}, {}, set()

        while True:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.1)
                continue
            h, w = frame.shape[:2]
            desk.frame_w, desk.frame_h = w, h

            results = self.model.predict(source=frame, conf=CONFIDENCE, verbose=False)
            new_objects = {}
            person_detected = False
            extra_detections = {}  # non-character detections (pets, lost items, phone)
            for r in results:
                for box in r.boxes:
                    cls_name = self.model.names[int(box.cls[0])]
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    if cls_name == 'person':
                        person_detected = True
                        continue
                    char_id = YOLO_TO_CHAR.get(cls_name)
                    if char_id:
                        if char_id == 'glug' and conf < GLUG_MIN_CONF:
                            char_id = None
                        if char_id and (char_id not in new_objects or conf > new_objects[char_id]['conf']):
                            new_objects[char_id] = {
                                'class_name': cls_name,
                                'bbox': [x1, y1, x2, y2],
                                'center': [(x1+x2)/2, (y1+y2)/2],
                                'conf': conf, 'cam': self.cam_idx,
                            }
                    if cls_name in PET_CLASSES or cls_name in LOST_OBJECT_CLASSES:
                        extra_detections[cls_name] = {
                            'bbox': [x1, y1, x2, y2],
                            'center': [(x1+x2)/2, (y1+y2)/2],
                            'conf': conf,
                        }
            self.person_detected = person_detected
            self.extra_detections = extra_detections

            raw = set(new_objects.keys())
            for cid in set(list(seen_count) + list(gone_count) + list(raw)):
                if cid in raw:
                    seen_count[cid] = seen_count.get(cid, 0) + 1
                    gone_count[cid] = 0
                else:
                    gone_count[cid] = gone_count.get(cid, 0) + 1
                    seen_count[cid] = 0
            now = time.time()
            for cid in raw:
                if cid not in confirmed and seen_count.get(cid, 0) >= APPEAR_FRAMES:
                    confirmed.add(cid)
                    with desk.lock:
                        if cid not in desk.object_first_seen:
                            desk.object_first_seen[cid] = now
                        desk.object_last_seen[cid] = now
                    _emit_event('appeared', cid)
            for cid in list(confirmed):
                if cid in raw:
                    with desk.lock:
                        desk.object_last_seen[cid] = now
                if cid not in raw and gone_count.get(cid, 0) >= DISAPPEAR_FRAMES:
                    confirmed.discard(cid)
                    _emit_event('disappeared', cid)
                    seen_count.pop(cid, None)
                    gone_count.pop(cid, None)

            self.local_objects = {c: d for c, d in new_objects.items() if c in confirmed}

            annotated = results[0].plot()
            self._draw_overlays(annotated, self.local_objects)
            _, ba = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 70])
            _, br = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            with desk.lock:
                desk.frames[self.cam_idx] = ba.tobytes()
                desk.raw_frames[self.cam_idx] = br.tobytes()
            time.sleep(0.05)

    @staticmethod
    def _draw_overlays(frame, objects):
        """Draw centroids + new relationship overlays from RelationshipAnalyzer."""
        if not objects:
            return

        # Centroid dots and character names
        for cid, det in objects.items():
            cx, cy = int(det['center'][0]), int(det['center'][1])
            char = CHARACTERS[cid]
            cv2.circle(frame, (cx, cy), 6, (0, 200, 255), -1)
            cv2.circle(frame, (cx, cy), 8, (255, 255, 255), 1)
            label = char['name']
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(frame, (cx - tw//2 - 3, cy - 20 - th - 2),
                          (cx + tw//2 + 3, cy - 18), (0, 0, 0), -1)
            cv2.putText(frame, label, (cx - tw//2, cy - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

        # Relationship diagrams from the analyzer
        char_names = {cid: CHARACTERS[cid]['name'] for cid in objects if cid in CHARACTERS}
        rel_analyzer.update_frame_size(frame.shape[1], frame.shape[0])
        rel_analyzer.draw_overlays(frame, objects, char_names)


class DetectionMerger(threading.Thread):
    def __init__(self, cam_threads):
        super().__init__(daemon=True)
        self.cam_threads = cam_threads

    def run(self):
        while True:
            merged = {}
            person_seen = False
            for ct in self.cam_threads:
                if ct.person_detected:
                    person_seen = True
                for cid, det in ct.local_objects.items():
                    if cid not in merged or det['conf'] > merged[cid]['conf']:
                        merged[cid] = det
            with desk.lock:
                desk.objects = merged
            self._track_auto_events(merged, person_seen)
            self._analyze(merged)
            time.sleep(0.3)

    @staticmethod
    def _bboxes_for_cam(objects, char_ids, prefer_cam):
        bboxes = []
        for cid in char_ids:
            obj = objects.get(cid)
            if obj and obj.get('cam') == prefer_cam:
                bboxes.append(obj['bbox'])
        if not bboxes:
            for cid in char_ids:
                obj = objects.get(cid)
                if obj:
                    bboxes.append(obj['bbox'])
        return bboxes

    def _track_auto_events(self, objects, person_seen):
        """Track all scenario events: breaks, sips, snacks, pets, lost objects, focus, clutter, posture, screen time."""
        now = time.time()

        extra = {}
        for ct in self.cam_threads:
            extra.update(getattr(ct, 'extra_detections', {}))

        brief = _build_habit_vision_brief(objects, extra, person_seen)
        with desk.lock:
            desk.merged_extra = dict(extra)
            desk.habit_vision_brief = brief

        with desk.lock:
            # ── 1. BREAK DETECTION (Monty) ──────────────────────────
            if person_seen:
                if desk.person_away_since is not None:
                    away_dur = now - desk.person_away_since
                    if away_dur >= BREAK_THRESHOLD_SEC and not desk.person_break_logged:
                        desk.person_break_logged = True
                        w = desk.char_widgets.get('monty')
                        if w and w.get('type') == 'break_timer':
                            w['breaks_today'] = w.get('breaks_today', 0) + 1
                            w['last_break'] = time.strftime('%Y-%m-%dT%H:%M:%S')
                            dur_min = int(away_dur / 60)
                            desk.events_queue.put({
                                'type': 'habit_reminder', 'character': 'monty',
                                'text': f'Nice \u2014 you were away for {dur_min} min. Break logged automatically!',
                            })
                if desk.person_continuous_since is None:
                    desk.person_continuous_since = now
                desk.person_last_seen = now
                desk.person_away_since = None
                desk.person_break_logged = False
            else:
                if desk.person_last_seen and desk.person_away_since is None:
                    desk.person_away_since = now
                desk.person_continuous_since = None

            # ── 2. SIP DETECTION (Glug) ─────────────────────────────
            glug_present = 'glug' in objects
            if glug_present:
                if desk.glug_gone_since is not None:
                    gone_dur = now - desk.glug_gone_since
                    if SIP_GONE_MIN_SEC <= gone_dur <= SIP_GONE_MAX_SEC:
                        w = desk.char_widgets.get('glug')
                        if w and w.get('type') == 'sip_counter':
                            w['sips'] = w.get('sips', 0) + 1
                            w['last_sip'] = time.strftime('%Y-%m-%dT%H:%M:%S')
                            desk.events_queue.put({
                                'type': 'habit_reminder', 'character': 'glug',
                                'text': f'Sip detected! That\'s {w["sips"]} today. Keep it up!',
                            })
                desk.glug_gone_since = None
            else:
                if desk.glug_gone_since is None and desk.object_last_seen.get('glug'):
                    desk.glug_gone_since = now

            # ── 3. SNACK DETECTION (Munch) ──────────────────────────
            munch_present = 'munch' in objects
            if munch_present:
                cls_name = objects['munch'].get('class_name', 'snack')
                if cls_name not in desk.munch_seen_classes:
                    desk.munch_seen_classes.add(cls_name)
                    w = desk.char_widgets.get('munch')
                    if w and w.get('type') == 'snack_log':
                        is_healthy = cls_name in ('banana', 'apple', 'orange', 'broccoli', 'carrot')
                        w.setdefault('entries', []).append({
                            'label': cls_name.title(), 'healthy': is_healthy,
                        })
                        emoji = '\U0001F34E' if is_healthy else '\U0001F355'
                        desk.events_queue.put({
                            'type': 'habit_reminder', 'character': 'munch',
                            'text': f'{emoji} Spotted a {cls_name} on the desk \u2014 logged it!',
                        })

            # ── 4. PET RISK DETECTION ───────────────────────────────
            for pet_cls in PET_CLASSES:
                if pet_cls in extra:
                    desk.pet_last_seen[pet_cls] = now
                    last_alert = desk.pet_near_cooldown.get(pet_cls, 0)
                    if now - last_alert > 120:
                        desk.pet_near_cooldown[pet_cls] = now
                        pet_name = pet_cls.title()
                        at_risk = [cid for cid in objects if cid in ('glug', 'munch')]
                        risk_msg = ''
                        if at_risk:
                            names = ', '.join(CHARACTERS[c]['name'] for c in at_risk)
                            risk_msg = f' {names} could get knocked over!'
                        desk.events_queue.put({
                            'type': 'scenario_alert',
                            'scenario': 'risk_detection',
                            'feature': 'pet_risk',
                            'character': 'monty',
                            'text': f'{pet_name} detected near the desk!{risk_msg} Careful!',
                        })

            # ── 5. LOST OBJECT TRACKING (YOLO + VLM + alerts) → LostObjectFrameworkThread

            # ── 6. FOCUS MODE (phone distraction) ───────────────────
            phone_present = 'cell phone' in extra
            if phone_present:
                if desk.phone_on_desk_since is None:
                    desk.phone_on_desk_since = now
                    desk.phone_focus_alerted = False
                elif not desk.phone_focus_alerted and (now - desk.phone_on_desk_since) > 300:
                    desk.phone_focus_alerted = True
                    desk.events_queue.put({
                        'type': 'scenario_alert',
                        'scenario': 'reminders', 'feature': 'focus',
                        'character': 'sheets',
                        'text': 'Your phone has been on the desk for 5+ minutes. Put it away to stay focused!',
                    })
            else:
                desk.phone_on_desk_since = None
                desk.phone_focus_alerted = False

            # ── 7. DESK ORGANIZATION (clutter) ──────────────────────
            total_items = len(objects) + len(extra)
            clutter_threshold = SCENARIOS['reminders']['features']['organization'].get('clutter_threshold', 6)
            if total_items >= clutter_threshold and (now - desk.last_clutter_alert) > 1800:
                desk.last_clutter_alert = now
                desk.events_queue.put({
                    'type': 'scenario_alert',
                    'scenario': 'reminders', 'feature': 'organization',
                    'character': 'sheets',
                    'text': f'Your desk has {total_items} items detected. Maybe tidy up a bit?',
                })

            # ── 8. POSTURE CHECK (time-based) ───────────────────────
            posture_interval = SCENARIOS['reminders']['features']['posture_check'].get('interval_sec', 2400)
            if person_seen and (now - desk.last_posture_reminder) > posture_interval:
                desk.last_posture_reminder = now
                desk.events_queue.put({
                    'type': 'scenario_alert',
                    'scenario': 'reminders', 'feature': 'posture_check',
                    'character': 'monty',
                    'text': random.choice([
                        'Posture check! Sit up straight and relax your shoulders.',
                        'How\'s your posture? Roll your shoulders back and sit tall.',
                        'Time to check your posture \u2014 are your feet flat on the floor?',
                        'Stretch your neck \u2014 tilt your head side to side gently.',
                    ]),
                })

            # ── 9. SCREEN TIME (continuous presence) ────────────────
            if person_seen and desk.person_continuous_since:
                session_min = (now - desk.person_continuous_since) / 60
                if session_min >= 45 and (now - desk.last_screen_time_reminder) > 2700:
                    desk.last_screen_time_reminder = now
                    desk.events_queue.put({
                        'type': 'scenario_alert',
                        'scenario': 'reminders', 'feature': 'screen_time',
                        'character': 'monty',
                        'text': f'You\'ve been at the desk for {int(session_min)} minutes straight. Take a quick break!',
                    })

            # ── 10. WATER PLANTS (time-based) ───────────────────────
            water_interval = SCENARIOS['reminders']['features']['water_plants'].get('interval_sec', 86400)
            if desk.last_water_plants_reminder == 0:
                desk.last_water_plants_reminder = now
            elif (now - desk.last_water_plants_reminder) > water_interval:
                desk.last_water_plants_reminder = now
                desk.events_queue.put({
                    'type': 'scenario_alert',
                    'scenario': 'reminders', 'feature': 'water_plants',
                    'character': 'glug',
                    'text': 'Daily reminder: have you watered your plants today?',
                })

    def _analyze(self, objects):
        """Run the new RelationshipAnalyzer, then emit chat events."""
        rel_analyzer.update_frame_size(desk.frame_w or 640, desk.frame_h or 480)
        result = rel_analyzer.analyze(objects)

        dangers = []
        checked = set()

        for ev in result.get('risk_events', []):
            if ev['type'] == 'zone_intrusion':
                intruder, target = ev['intruder'], ev['target']
                oi, ot = objects.get(intruder), objects.get(target)
                if oi and oi.get('class_name') in ('cup', 'bottle', 'wine glass') and oi.get('conf', 0) < GLUG_MIN_CONF:
                    continue
                if ot and ot.get('class_name') in ('cup', 'bottle', 'wine glass') and ot.get('conf', 0) < GLUG_MIN_CONF:
                    continue
                pair = frozenset({intruder, target})
                if pair in checked:
                    continue
                checked.add(pair)
                speaker = target if target in ('monty', 'sheets') else intruder
                cam = objects.get(speaker, {}).get('cam', 0)
                bboxes = self._bboxes_for_cam(objects, [intruder, target], cam)
                other = target if speaker == intruder else intruder
                _emit_interaction('proximity', speaker, cam, bboxes,
                                  near=other, severity='high',
                                  rule_label=ev.get('zone_label', ''),
                                  depth_px=ev.get('depth_px', 0))
                dangers.append({
                    'pair': [ev['intruder_class'], ev['target_class']],
                    'label': ev.get('zone_label', ''),
                    'depth_px': ev.get('depth_px', 0),
                    'type': 'zone_intrusion',
                })
            elif ev['type'] == 'edge_danger':
                cid = ev['object']
                if cid in objects:
                    cam = objects[cid].get('cam', 0)
                    bboxes = self._bboxes_for_cam(objects, [cid], cam)
                    _emit_interaction('proximity', cid, cam, bboxes,
                                      severity='medium',
                                      rule_label=f"Near {ev['edge']} edge ({int(ev['distance_px'])}px)")
                    dangers.append({
                        'pair': [ev['class'], 'desk_edge'],
                        'label': f"{ev['class']} near {ev['edge']} edge",
                        'type': 'edge_danger',
                    })

        now = time.time()
        risk_level = result.get('risk_level', 0)
        with desk.lock:
            desk.safety_state = 'DANGEROUS' if risk_level >= 2 else 'SAFE'
            desk.safety_dangers = dangers
            desk.rel_result = result
            active_pairs = set()
            for d in dangers:
                pair = frozenset(d['pair'])
                active_pairs.add(pair)
                if pair not in desk.danger_active_since:
                    desk.danger_active_since[pair] = now
            for pair in list(desk.danger_active_since):
                if pair not in active_pairs:
                    del desk.danger_active_since[pair]

        # Symbiotic rules still apply
        for obj_a, obj_b, speaker, mult in SYMBIOTIC_RULES:
            pair = frozenset({obj_a, obj_b})
            if pair in checked:
                continue
            if obj_a in objects and obj_b in objects:
                d = math.dist(objects[obj_a]['center'], objects[obj_b]['center'])
                if d < desk.frame_w * PROXIMITY_RATIO * mult:
                    checked.add(pair)
                    other = obj_b if speaker == obj_a else obj_a
                    _emit_event('symbiotic', speaker, near=other)

    def _analyze_fallback(self, objects):
        """Fallback: use ratio-based proximity rules when no safety_rules.json."""
        threshold = desk.frame_w * PROXIMITY_RATIO
        checked = set()

        for obj_a, obj_b, speaker, severity, mult in FALLBACK_PROXIMITY_RULES:
            pair = frozenset({obj_a, obj_b})
            if pair in checked:
                continue
            if obj_a in objects and obj_b in objects:
                d = math.dist(objects[obj_a]['center'], objects[obj_b]['center'])
                if d < threshold * mult:
                    checked.add(pair)
                    cam = objects[speaker].get('cam', 0)
                    bboxes = self._bboxes_for_cam(objects, [obj_a, obj_b], cam)
                    other = obj_b if speaker == obj_a else obj_a
                    _emit_interaction('proximity', speaker, cam, bboxes,
                                     near=other, severity=severity)

        for obj_a, obj_b, speaker, mult in SYMBIOTIC_RULES:
            pair = frozenset({obj_a, obj_b})
            if pair in checked:
                continue
            if obj_a in objects and obj_b in objects:
                d = math.dist(objects[obj_a]['center'], objects[obj_b]['center'])
                if d < threshold * mult:
                    checked.add(pair)
                    other = obj_b if speaker == obj_a else obj_a
                    _emit_event('symbiotic', speaker, near=other)

        with desk.lock:
            desk.safety_state = 'SAFE'
            desk.safety_dangers = []


# ═══════════════════════════════════════════════════════════════════
#  Live context builder — structured real-time data for LLM
# ═══════════════════════════════════════════════════════════════════
# Maps @mention keywords → character IDs
MENTION_MAP = {}
for _cid, _cdata in CHARACTERS.items():
    MENTION_MAP[_cid] = _cid
    MENTION_MAP[_cdata['name'].lower()] = _cid
    MENTION_MAP[_cdata['object'].lower().split('/')[0].strip()] = _cid
    for _cls in _cdata['yolo_classes']:
        MENTION_MAP[_cls.lower()] = _cid
# Common shorthand aliases
MENTION_MAP.update({
    'phone': 'monty', 'cup': 'glug', 'water': 'glug', 'bottle': 'glug',
    'keyboard': 'monty', 'keys': 'monty', 'laptop': 'monty', 'computer': 'monty',
    'cable': 'monty', 'charger': 'monty', 'cord': 'monty',
    'snack': 'munch', 'food': 'munch', 'pizza': 'munch',
    'paper': 'sheets', 'homework': 'sheets', 'book': 'sheets',
    'powerbank': 'monty', 'power bank': 'monty', 'battery': 'monty', 'mouse': 'monty',
})


def _normalize_widget(raw):
    """Sanitize widget payload from client."""
    if not isinstance(raw, dict) or 'type' not in raw:
        return None
    wtype = raw['type']
    if wtype == 'todo':
        items = []
        for item in (raw.get('items') or [])[:20]:
            if isinstance(item, dict):
                t = str(item.get('text', ''))[:200].strip()
                if t:
                    items.append({'text': t, 'done': bool(item.get('done'))})
        return {'type': 'todo', 'items': items}
    if wtype == 'break_timer':
        return {
            'type': 'break_timer',
            'last_break': raw.get('last_break'),
            'breaks_today': int(raw.get('breaks_today', 0)),
        }
    if wtype == 'sip_counter':
        return {
            'type': 'sip_counter',
            'sips': int(raw.get('sips', 0)),
            'goal': int(raw.get('goal', 8)),
            'last_sip': raw.get('last_sip'),
        }
    if wtype == 'snack_log':
        entries = []
        for e in (raw.get('entries') or [])[:30]:
            if isinstance(e, dict) and e.get('label'):
                entries.append({
                    'label': str(e['label'])[:60],
                    'healthy': bool(e.get('healthy')),
                })
        return {'type': 'snack_log', 'entries': entries}
    return None


def _format_widget_for_prompt(widget):
    """Turn stored widget data into an LLM context block."""
    if not widget:
        return ''
    wtype = widget.get('type')

    if wtype == 'todo':
        items = widget.get('items', [])
        if not items:
            return ''
        lines = []
        for t in items:
            mark = 'x' if t.get('done') else ' '
            lines.append(f"- [{mark}] {t.get('text', '')}")
        return (
            "\nUSER'S TO-DO LIST (prioritize open items, celebrate completed ones):\n"
            + '\n'.join(lines)
        )

    if wtype == 'break_timer':
        breaks = widget.get('breaks_today', 0)
        last = widget.get('last_break')
        last_str = last if last else 'none yet today'
        return (
            f"\nUSER'S BREAK DATA: {breaks} break(s) taken today. "
            f"Last break: {last_str}. "
            "Nudge them to take breaks if it's been a while. "
            "Celebrate streaks."
        )

    if wtype == 'sip_counter':
        sips = widget.get('sips', 0)
        goal = widget.get('goal', 8)
        last = widget.get('last_sip')
        last_str = last if last else 'none yet'
        return (
            f"\nUSER'S HYDRATION: {sips}/{goal} sips today. "
            f"Last sip: {last_str}. "
            "Encourage drinking water. Celebrate hitting the goal."
        )

    if wtype == 'snack_log':
        entries = widget.get('entries', [])
        if not entries:
            return "\nUSER'S SNACK LOG: Empty today. Note they haven't logged any snacks."
        healthy = [e['label'] for e in entries if e.get('healthy')]
        junk = [e['label'] for e in entries if not e.get('healthy')]
        parts = []
        if healthy:
            parts.append(f"Healthy: {', '.join(healthy)}")
        if junk:
            parts.append(f"Junk: {', '.join(junk)}")
        return (
            f"\nUSER'S SNACK LOG TODAY ({len(entries)} items): "
            + '; '.join(parts) + '. '
            "Comment on their choices — praise healthy picks, gently tease junk."
        )

    return ''


def _action_instructions_for(wtype):
    """Return LLM instructions for available actions based on widget type."""
    if wtype == 'todo':
        return """
ACTIONS — you MUST use these whenever the conversation implies it:
- User wants to add/create/remember/track anything → you MUST include [ADD_TODO:task text] in your reply
- User says a task is done/finished/completed → you MUST include [DONE_TODO:exact task text from the list] in your reply
- User wants to remove/delete a task → you MUST include [DEL_TODO:exact task text] in your reply
You can include multiple action tags in one reply.
IMPORTANT: Write a short conversational reply AND the tag(s). Example: "Done, adding that! [ADD_TODO:Buy groceries]"
If the user asks you to add something, you MUST include the [ADD_TODO:...] tag. Do NOT just talk about it."""
    if wtype == 'break_timer':
        return """
ACTIONS — you MUST use these whenever the conversation implies it:
- User says they took/are taking a break, stepped away, stretched, or anything related → you MUST include [LOG_BREAK] in your reply
- User asks you to log a break → you MUST include [LOG_BREAK] in your reply
IMPORTANT: Write a short conversational reply AND the tag. Example: "Nice stretch! [LOG_BREAK]"
If the user mentions taking a break, you MUST include [LOG_BREAK]. Do NOT just talk about it."""
    if wtype == 'sip_counter':
        return """
ACTIONS — you MUST use these whenever the conversation implies it:
- User says they drank water, had a sip, is hydrating, or anything related → you MUST include [LOG_SIP] in your reply
- User asks you to log a sip → you MUST include [LOG_SIP] in your reply
IMPORTANT: Write a short conversational reply AND the tag. Example: "Splash! That's the spirit. [LOG_SIP]"
If the user mentions drinking water, you MUST include [LOG_SIP]. Do NOT just talk about it."""
    if wtype == 'snack_log':
        return """
ACTIONS — you MUST use these whenever the conversation implies it:
- User mentions eating/snacking on something healthy (fruit, nuts, veggies, etc.) → you MUST include [LOG_SNACK_HEALTHY:food name]
- User mentions eating/snacking on something unhealthy (chips, candy, soda, etc.) → you MUST include [LOG_SNACK_JUNK:food name]
- User asks you to log food → pick HEALTHY or JUNK and include the tag
IMPORTANT: Write a short conversational reply AND the tag. Example: "Ooh almonds, solid pick! [LOG_SNACK_HEALTHY:almonds]"
If the user mentions eating something, you MUST include the tag. Do NOT just talk about it."""
    return ''


def _parse_actions(text, wtype):
    """Extract action tags from LLM text, return (clean_text, actions_list)."""
    import re
    actions = []
    if wtype == 'todo':
        for m in re.finditer(r'\[ADD_TODO:(.+?)\]', text):
            actions.append({'action': 'add_todo', 'text': m.group(1).strip()})
        for m in re.finditer(r'\[DONE_TODO:(.+?)\]', text):
            actions.append({'action': 'done_todo', 'text': m.group(1).strip()})
        for m in re.finditer(r'\[DEL_TODO:(.+?)\]', text):
            actions.append({'action': 'del_todo', 'text': m.group(1).strip()})
        text = re.sub(r'\[(ADD|DONE|DEL)_TODO:.+?\]', '', text)
    elif wtype == 'break_timer':
        if '[LOG_BREAK]' in text:
            actions.append({'action': 'log_break'})
            text = text.replace('[LOG_BREAK]', '')
    elif wtype == 'sip_counter':
        if '[LOG_SIP]' in text:
            actions.append({'action': 'log_sip'})
            text = text.replace('[LOG_SIP]', '')
    elif wtype == 'snack_log':
        for m in re.finditer(r'\[LOG_SNACK_HEALTHY:(.+?)\]', text):
            actions.append({'action': 'log_snack', 'label': m.group(1).strip(), 'healthy': True})
        for m in re.finditer(r'\[LOG_SNACK_JUNK:(.+?)\]', text):
            actions.append({'action': 'log_snack', 'label': m.group(1).strip(), 'healthy': False})
        text = re.sub(r'\[LOG_SNACK_(HEALTHY|JUNK):.+?\]', '', text)
    return text.strip(), actions


def _format_duration(seconds):
    if seconds < 60:
        return f'{int(seconds)}s'
    if seconds < 3600:
        return f'{int(seconds / 60)}m {int(seconds % 60)}s'
    return f'{int(seconds / 3600)}h {int((seconds % 3600) / 60)}m'


def _sanitize_chat_history(raw):
    """Up to 5 prior turns for 1:1 or group: [{role, text, name?}, ...] from client JSON."""
    if not raw or not isinstance(raw, list):
        return []
    out = []
    for item in raw[-5:]:
        if not isinstance(item, dict):
            continue
        role = (item.get('role') or '').strip().lower()
        if role not in ('user', 'assistant'):
            continue
        text = item.get('text', '')
        if not isinstance(text, str):
            text = str(text)
        text = text.strip()[:2000]
        if not text:
            continue
        d = {'role': role, 'text': text}
        name = (item.get('name') or '').strip()[:64]
        if name:
            d['name'] = name
        out.append(d)
    return out


def _parse_mentions(text):
    """Extract @mentions from user text, return list of char_ids."""
    import re
    mentions = re.findall(r'@(\w[\w\s]*\w|\w)', text.lower())
    char_ids = []
    for m in mentions:
        m = m.strip()
        cid = MENTION_MAP.get(m)
        if cid and cid not in char_ids:
            char_ids.append(cid)
    return char_ids


def build_live_context(user_message=''):
    """Build structured real-time context from DeskState for the LLM."""
    now = time.time()
    lines = []
    detected_info = []
    mentioned_objects = []

    with desk.lock:
        objects = dict(desk.objects)
        dangers = list(desk.safety_dangers)
        safety_state = desk.safety_state
        first_seen = dict(desk.object_first_seen)
        last_seen = dict(desk.object_last_seen)
        danger_since = dict(desk.danger_active_since)
        recent = list(desk.recent_events[-10:])

    # Objects currently on desk (no raw % in summary — the model was quoting "49% confidence" in chat)
    if objects:
        lines.append('OBJECTS THE CAMERA IS TRACKING (vision can be wrong or noisy):')
        for cid, det in objects.items():
            char = CHARACTERS[cid]
            on_desk_for = _format_duration(now - first_seen[cid]) if cid in first_seen else '?'
            detected_info.append({
                'char_id': cid, 'name': char['name'], 'object': char['object'],
                'confidence': round(det['conf'], 2), 'on_desk_for': on_desk_for,
            })
            lines.append(
                f'  - {char["name"]} (you play this as: {char["object"]}): vision label "{det["class_name"]}", here ~{on_desk_for}'
            )
    else:
        lines.append('NO DESK CHARACTERS CURRENTLY HIT BY THE VISION BOUNDING RULES (may be empty or mis-framed).')

    # Not detected
    missing = [cid for cid in CHARACTERS if cid not in objects]
    if missing:
        missing_names = [f'{CHARACTERS[c]["name"]} ({CHARACTERS[c]["object"]})' for c in missing]
        lines.append(f'NOT ON DESK: {", ".join(missing_names)}')

    # Active dangers + relationship analysis
    rel_result = desk.rel_result
    risk_level = rel_result.get('risk_level', 0) if rel_result else 0

    if dangers:
        lines.append(f'\nACTIVE DANGERS (risk level {risk_level}/4, state: {safety_state}):')
        for d in dangers:
            pair_key = frozenset(d['pair'])
            duration = _format_duration(now - danger_since[pair_key]) if pair_key in danger_since else 'just now'
            dtype = d.get('type', '')
            if dtype == 'zone_intrusion':
                lines.append(f'  - {d["label"]} — intrusion {d.get("depth_px", 0)}px deep, active for {duration}')
            elif dtype == 'edge_danger':
                lines.append(f'  - {d["label"]} — object near desk edge, active for {duration}')
            else:
                lines.append(f'  - {d["label"]} — active for {duration}')
    else:
        lines.append(f'\nNO ACTIVE DANGERS — desk is safe (risk {risk_level}/4).')

    if rel_result:
        explanations = rel_result.get('explanations', [])
        if explanations:
            lines.append(f'\nRELATIONSHIP INSIGHTS:')
            for exp in explanations[:6]:
                lines.append(f'  - {exp}')

    with desk.lock:
        vlmv = sorted(desk.lost_last_vlm_visible)
    if vlmv:
        lines.append(
            f'\nLAST VISION PASS (Ollama lost-item scan) mentioned: {", ".join(vlmv)}. '
            'Use for small items (e.g. AirPods) that YOLO may miss; do not claim a cup if not listed and not in detections above.'
        )

    # Recent interaction history
    if recent:
        lines.append(f'\nRECENT EVENTS (last {len(recent)}):')
        for ev in recent[-5:]:
            age = _format_duration(now - ev['time'])
            char_name = CHARACTERS.get(ev['character'], {}).get('name', '?')
            near_name = CHARACTERS.get(ev.get('near', ''), {}).get('name', '')
            label = ev.get('rule_label', '') or ev.get('severity', '')
            near_str = f' near {near_name}' if near_name else ''
            lines.append(f'  - {age} ago: {char_name}{near_str} ({label})')

    # Session duration
    lines.append(f'\nSession active for {_format_duration(now - desk.session_start)}.')

    if user_message:
        um = user_message.lower()
        if any(phrase in um for phrase in (
                'nothing next', 'nothing nect', 'not next to you', 'not a cup', "isn't a cup", 'isnt a cup',
                "that's not", 'thats not', 'that is not', 'there is nothing', "there's nothing",
                'no cup', 'wrong', 'not there', "don't see", 'dont see', 'not next', 'makes no sense',
        )):
            lines.append(
                '\nUSER IS PUSHING BACK ON THE SCENE: believe them about what is physically there. '
                'Do not repeat confidence numbers, "risk level", or argue with their eyes.'
            )

    # Parse @mentions from user message
    if user_message:
        mention_ids = _parse_mentions(user_message)
        for cid in mention_ids:
            char = CHARACTERS[cid]
            obj_data = objects.get(cid)
            if obj_data:
                on_desk = _format_duration(now - first_seen[cid]) if cid in first_seen else '?'
                status = f'On desk ~{on_desk}; vision label {obj_data["class_name"]} (camera can be off)'
                # Check if involved in any danger
                obj_dangers = [d for d in dangers if cid == YOLO_TO_CHAR.get(d['pair'][0]) or cid == YOLO_TO_CHAR.get(d['pair'][1])]
                if obj_dangers:
                    status += '. DANGER: ' + '; '.join(d['label'] for d in obj_dangers)
            else:
                if cid in last_seen:
                    gone_for = _format_duration(now - last_seen[cid])
                    status = f'Not currently on desk (last seen {gone_for} ago)'
                else:
                    status = 'Not detected this session'
            mentioned_objects.append({'char_id': cid, 'name': char['name'], 'object': char['object'], 'status': status})

    return {
        'summary': '\n'.join(lines),
        'detected': detected_info,
        'dangers': dangers,
        'safety_state': safety_state,
        'mentioned_objects': mentioned_objects,
    }


def _normalize_lost_yolo_name(raw, allowed):
    """Map LLM / user words to tracked yolo_class keys (e.g. keys → remote)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s in allowed:
        return s
    low = s.lower()
    if low in allowed:
        return low
    alias = {
        'keys': 'remote', 'key': 'remote', 'keychain': 'remote', 'keyring': 'remote',
        'key fob': 'remote', 'fob': 'remote',
        'phone': 'cell phone', 'iphone': 'cell phone', 'mobile': 'cell phone',
        'cellphone': 'cell phone', 'cell': 'cell phone',
        'wallet': 'handbag', 'purse': 'handbag', 'bag': 'handbag',
        'airpod': 'airpods', 'airpods': 'airpods', 'earbuds': 'airpods', 'earbud': 'airpods',
        'earphones': 'airpods', 'earphone': 'airpods',
    }.get(low)
    if alias and alias in allowed:
        return alias
    return None


def _keyword_lost_yolo_classes(message, allowed):
    """Heuristic parse so queries like "seen my keys?" always map to YOLO classes we track."""
    low = (message or '').lower()
    # Word tokens only — avoid substring false positives (e.g. "monkey" contains "key").
    words = set(re.findall(r'[a-z0-9]+', low))
    out = []
    if words & {'key', 'keys', 'keyring', 'keychain', 'fob', 'remote'}:
        if 'remote' in allowed:
            out.append('remote')
    if words & {'phone', 'iphone', 'mobile', 'cell', 'cellphone', 'android'}:
        if 'cell phone' in allowed:
            out.append('cell phone')
    if words & {'wallet', 'purse', 'handbag', 'bag', 'card', 'cards'}:
        if 'handbag' in allowed:
            out.append('handbag')
    if words & {'airpod', 'airpods', 'earbuds', 'earbud', 'earphone', 'earphones'}:
        if 'airpods' in allowed:
            out.append('airpods')
    return out


# ═══════════════════════════════════════════════════════════════════
#  Message generator
# ═══════════════════════════════════════════════════════════════════
class MessageGenerator(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.client = None
        self.model_name = None
        self.llm_label = 'Template fallback'
        self._sse_queues = []
        self._lock = threading.Lock()
        self._last_llm_call = 0.0
        self._sent_messages = {}

        if OPENAI_API_KEY and HAS_OPENAI:
            self.client = OpenAI(api_key=OPENAI_API_KEY)
            self.model_name = LLM_MODEL
            self.llm_label = f'OpenAI {LLM_MODEL}'
        elif GEMINI_API_KEY and HAS_OPENAI:
            self.client = OpenAI(
                api_key=GEMINI_API_KEY,
                base_url='https://generativelanguage.googleapis.com/v1beta/openai/',
            )
            self.model_name = GEMINI_MODEL
            self.llm_label = f'Gemini {GEMINI_MODEL}'
        elif GROQ_API_KEY and HAS_OPENAI:
            self.client = OpenAI(
                api_key=GROQ_API_KEY,
                base_url='https://api.groq.com/openai/v1',
            )
            self.model_name = GROQ_MODEL
            self.llm_label = f'Groq {GROQ_MODEL}'
        elif OLLAMA_URL and HAS_OPENAI:
            self.client = OpenAI(
                api_key='ollama',
                base_url=OLLAMA_URL,
            )
            self.model_name = OLLAMA_MODEL
            self.llm_label = f'Ollama {OLLAMA_MODEL}'

    def _call_llm(self, messages, max_tokens=120, temperature=0.85):
        if not self.client:
            return None
        elapsed = time.time() - self._last_llm_call
        if elapsed < MIN_LLM_INTERVAL:
            time.sleep(MIN_LLM_INTERVAL - elapsed)
        self._last_llm_call = time.time()
        for attempt in range(LLM_MAX_RETRIES):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model_name, messages=messages,
                    max_tokens=max_tokens, temperature=temperature,
                )
                return resp.choices[0].message.content.strip().strip('"\'')
            except Exception as exc:
                err = str(exc)
                is_rate_limit = '429' in err or 'rate' in err.lower() or 'quota' in err.lower()
                if is_rate_limit and attempt < LLM_MAX_RETRIES - 1:
                    wait = (2 ** attempt) * 4
                    print(f'  [llm] Rate limited, retry {attempt+1}/{LLM_MAX_RETRIES} in {wait}s...')
                    time.sleep(wait)
                    continue
                print(f'  [llm] Error (attempt {attempt+1}): {exc}')
                return None
        return None

    def _call_vision_vlm(self, jpeg_bytes, user_text, model=None):
        """Ollama / OpenAI-compatible vision call for lost-item + optional habit VLM."""
        if not self.client or not jpeg_bytes:
            return None
        m = model or self.model_name
        b64 = base64.b64encode(jpeg_bytes).decode('ascii')
        for attempt in range(LLM_MAX_RETRIES):
            try:
                elapsed = time.time() - self._last_llm_call
                if elapsed < MIN_LLM_INTERVAL:
                    time.sleep(MIN_LLM_INTERVAL - elapsed)
                self._last_llm_call = time.time()
                resp = self.client.chat.completions.create(
                    model=m,
                    messages=[{
                        'role': 'user',
                        'content': [
                            {'type': 'text', 'text': user_text},
                            {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}'}},
                        ],
                    }],
                    max_tokens=400,
                    temperature=0.2,
                )
                return (resp.choices[0].message.content or '').strip()
            except Exception as exc:
                err = str(exc)
                print(f'  [vision] attempt {attempt+1}: {exc}')
                if '404' in err or 'not found' in err.lower() and m != self.model_name:
                    m = self.model_name
                if attempt < LLM_MAX_RETRIES - 1:
                    time.sleep(1.0 * (attempt + 1))
        return None

    def _habit_vision_enrich(self):
        """Optional: one-line VLM note for habit policy; infrequent."""
        with desk.lock:
            jpg = None
            for ci in sorted(desk.raw_frames.keys()):
                jpg = desk.raw_frames.get(ci)
                if jpg:
                    break
        if not jpg or not OLLAMA_URL or not self.client:
            return
        t0 = time.time()
        with desk.lock:
            if t0 - desk.habit_vlm_brief_ts < HABIT_VISION_ENRICH_SEC:
                return
        p = 'One line: is the user likely at the desk, phone visible, drink nearby? Be concise.'
        txt = self._call_vision_vlm(jpg, p, model=LOST_VISION_MODEL)
        if txt:
            with desk.lock:
                desk.habit_vlm_brief = txt[:400]
                desk.habit_vlm_brief_ts = time.time()

    def answer_lost_object_query(self, user_message):
        """Parse query → match records; uses LLM for synonyms when available."""
        with desk.lock:
            records = {k: dict(v) for k, v in desk.lost_objects.items()}
        allowed = {
            f.get('yolo_class')
            for f in SCENARIOS['lost_object']['features'].values()
            if f.get('yolo_class')
        }
        wanted = []
        if self.client:
            system = (
                'Reply ONLY valid JSON: {"items":["yolo_class",...]}. '
                f'Map the user request to yolo class keys we track: {sorted(allowed)} '
                'e.g. keys→remote, phone→cell phone, wallet→handbag, airpods→airpods. Use exact keys. Empty list if none.'
            )
            raw = self._call_llm([
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user_message[:500]},
            ], max_tokens=80, temperature=0.1)
            if raw:
                try:
                    j = json.loads(raw)
                except json.JSONDecodeError:
                    m = re.search(r'\{[\s\S]*\}', raw)
                    if m:
                        try:
                            j = json.loads(m.group(0))
                        except json.JSONDecodeError:
                            j = {}
                    else:
                        j = {}
                if isinstance(j.get('items'), list):
                    for x in j['items']:
                        n = _normalize_lost_yolo_name(x, allowed)
                        if n:
                            wanted.append(n)
        else:
            wanted = _keyword_lost_yolo_classes(user_message, allowed)
        # Always union keyword hits so "keys" → remote even when the LLM returns "keys" or [].
        for w in _keyword_lost_yolo_classes(user_message, allowed):
            if w not in wanted:
                wanted.append(w)
        if not wanted:
            return (
                "I couldn\u2019t map that to something we log yet "
                f"(we track: {', '.join(sorted(allowed))}). "
                "Say what you\u2019re looking for, e.g. phone, keys, AirPods, or wallet."
            )
        parts = []
        now = time.time()
        for yc in wanted:
            e = records.get(yc) or _lost_init_entry()
            if e.get('last_seen'):
                ago = int(now - e['last_seen'])
                if ago < 90:
                    parts.append(f'{yc}: on/near the desk in the last ~{ago}s (camera).')
                else:
                    m = int(ago / 60)
                    parts.append(f'{yc}: last seen on the desk about {m} min ago (camera log).')
            else:
                parts.append(f'{yc}: not logged on the desk in this session yet.')
        if 'airpods' in wanted and OLLAMA_URL and self.client:
            jpg = None
            with desk.lock:
                for ci in sorted(desk.raw_frames.keys()):
                    jpg = desk.raw_frames.get(ci)
                    if jpg:
                        break
            if jpg:
                vlm = self._call_vision_vlm(
                    jpg,
                    'Is an AirPods case, earbuds, or similar on the desk in this image? '
                    'One short sentence: start with "Visible:" or "Not visible:"',
                    model=LOST_VISION_MODEL,
                )
                if vlm:
                    parts.append(f'Ollama vision: {vlm.strip()[:220]}')
        return ' '.join(parts)

    def run(self):
        while True:
            try:
                event = desk.events_queue.get(timeout=1)
                msg = self._generate(event)
                if msg:
                    self._broadcast(msg)
            except queue.Empty:
                continue
            except Exception as exc:
                print(f'  [generator] Error: {exc}')

    def _interaction_key(self, event):
        return f'{event["type"]}_{event["character"]}_{event.get("near", "")}'

    def _generate(self, event):
        char_id = event['character']
        snapshot = event.get('snapshot')
        follow_up = event.get('follow_up', 0)
        ikey = self._interaction_key(event) if event['type'] == 'proximity' else None
        prev = self._sent_messages.get(ikey) if ikey and follow_up > 0 else None

        if self.client:
            result = self._llm_event(char_id, event, prev)
        else:
            result = self._template_event(char_id, event)

        if result:
            if snapshot:
                result['snapshot'] = snapshot
            if prev:
                result['reply_to'] = {'character': prev['character'], 'text': prev['text']}
            if ikey:
                self._sent_messages[ikey] = {'character': char_id, 'text': result['text']}
        return result

    def _llm_event(self, char_id, event, prev=None):
        char = CHARACTERS[char_id]
        with desk.lock:
            detected = ', '.join(
                f"{CHARACTERS[c]['name']} ({CHARACTERS[c]['object']})"
                for c in desk.objects
            ) or 'nothing detected'

        event_desc = self._describe_event(event)
        follow_up = event.get('follow_up', 0)

        system = f"""You are {char['name']}, a {char['object']} on a desk. You are a character in a group chat with the other desk objects.

PERSONALITY: {char['personality']}

STRICT RULES:
1. ONE sentence only. Max 15 words. Be punchy.
2. The SITUATION line includes VISION GROUNDING with actual detector class names (e.g. wine glass, book, laptop). Use ONLY those names. Never say "cup" or "liquid" unless the grounding line names cup, bottle, or wine glass.
3. If grounding shows only laptop/book/person, do NOT invent drinks or spills — say what is actually named.
4. State the risk in plain words. "Could spill on me" not "this could end badly."
5. NO metaphors, NO vague feelings. Be literal about what's physically happening.

GOOD: "Wine glass is right on my edge — nudge and I'm soaked."
BAD: "Cup is touching me" when grounding says the other class is "book" or "keyboard".

Never mention being an AI. Never break character."""

        if prev and follow_up > 0:
            urgency = 'more urgently' if follow_up == 1 else 'VERY urgently'
            user = f"""SITUATION: {event_desc}

Your previous warning was: "{prev['text']}"
The problem is STILL happening — nothing was moved.

Write ONE punchy follow-up from {char['name']} (max 15 words). {urgency}. Name objects, tell @user what to move. Just the message."""
        else:
            user = f"""SITUATION: {event_desc}

Write ONE punchy message from {char['name']} (max 15 words). Name the objects, state the risk. Just the message."""

        text = self._call_llm([
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ])
        if text:
            return {'type': 'group_message', 'character': char_id, 'text': text}
        return self._template_event(char_id, event)

    def _template_event(self, char_id, event):
        etype = event['type']
        if etype == 'proximity' and not event.get('near'):
            rl = event.get('rule_label') or 'Geometry / frame edge warning'
            return {'type': 'group_message', 'character': char_id,
                    'text': f'{rl} @user—this is from frame edges, not another object.'}
        if etype == 'proximity' and event.get('near'):
            with desk.lock:
                o = dict(desk.objects)
            oy = (o.get(event['near']) or {}).get('class_name', 'object')
            sy = (o.get(char_id) or {}).get('class_name', 'object')
            if oy in ('cup', 'bottle', 'wine glass'):
                risk = f'{oy.replace(" ", "-")} is too close — spill/short risk on {sy}. @user move the drink back.'
            else:
                risk = f'Detector has {oy} near {sy} (geometry alert). @user check spacing—do not assume a drink unless it is a cup, bottle, or wine glass in frame.'
            return {'type': 'group_message', 'character': char_id, 'text': risk}
        pool = TEMPLATES.get(etype, {}).get(char_id)
        if not pool:
            pool = TEMPLATES.get('proximity', {}).get(char_id, ['...'])
        text = random.choice(pool)
        return {'type': 'group_message', 'character': char_id, 'text': text}

    def _describe_event(self, event):
        etype = event['type']
        char_id = event['character']
        char_name = CHARACTERS[char_id]['name']
        char_obj = CHARACTERS[char_id]['object']
        if etype == 'proximity':
            other_id = event.get('near', '')
            with desk.lock:
                o_det = dict(desk.objects)
            self_yolo = (o_det.get(char_id) or {}).get('class_name', 'unknown')
            other_yolo = (o_det.get(other_id) or {}).get('class_name', 'unknown')
            other_name = CHARACTERS.get(other_id, {}).get('name', 'something')
            other_obj = CHARACTERS.get(other_id, {}).get('object', 'something')
            drink_classes = ('cup', 'bottle', 'wine glass')
            drink_note = ''
            if other_yolo in drink_classes:
                drink_note = f'The other object is a drink class ({other_yolo}) — spill risk is real. '
            elif self_yolo in drink_classes:
                drink_note = f'You are a drink class ({self_yolo}). '
            else:
                drink_note = (
                    'NEITHER object is a cup/bottle/wine_glass in the detector — do NOT claim liquid or cup. '
                    'Use the exact class names above (e.g. book, keyboard). '
                )
            rule_label = event.get('rule_label', '')
            if rule_label:
                risk = rule_label
            else:
                pair = frozenset({char_id, other_id})
                risk = RELATIONSHIP_DESCRIPTIONS.get(
                    pair, f'{self_yolo} and {other_yolo} are in the same area.')
            return (
                f'VISION GROUNDING: this chat message was triggered by geometry rules; detector classes are '
                f'"{self_yolo}" (you, {char_name}) and "{other_yolo}" (other: {other_name}). {drink_note}'
                f'Rule / risk: {risk}. '
                f'Reply using ONLY these class words for objects — not generic "cup" unless other_yolo is cup, bottle, or wine glass.'
            )
        if etype == 'symbiotic':
            other_id = event.get('near', '')
            other_name = CHARACTERS.get(other_id, {}).get('name', 'something')
            other_obj = CHARACTERS.get(other_id, {}).get('object', 'something')
            return (
                f'The {char_obj} ({char_name}) and the {other_obj} ({other_name}) '
                f'are next to each other — they work well together.'
            )
        return f'Event: {etype}'

    def generate_chat_response(self, char_id, user_message, recent_messages=None):
        """Generate a response grounded in live context from the detection pipeline.
        *recent_messages*: up to 5 prior {role, text, name?} from the client (same thread)."""
        char = CHARACTERS[char_id]
        habit = HABIT_FOCUS.get(char_id, {})
        habit_area = habit.get('area', 'desk habits')
        context = build_live_context(user_message)
        mentioned = context['mentioned_objects']
        history = _sanitize_chat_history(recent_messages)
        with desk.lock:
            widget = desk.char_widgets.get(char_id)
        widget_block = _format_widget_for_prompt(widget)
        wtype = widget.get('type', 'none') if widget else 'none'

        action_instructions = _action_instructions_for(wtype)

        if self.client:
            hist_note = (
                'A short RECENT MESSAGES history is included in this API call (before your reply). '
                'Treat it as the real thread — do not imagine user lines that are not there; stay consistent with what was actually said.'
            ) if history else 'This may be the start of the thread (no prior messages yet).'
            system = f"""You are {char['name']}, a {char['object']} on someone's desk, chatting 1-on-1 with the desk owner.

PERSONALITY: {char['personality']}

YOUR HABIT FOCUS AREA: {habit_area}
{widget_block}

LIVE DESK STATUS (from cameras — noisy, not perfect):
{context['summary']}

{hist_note}

COHERENCE (non-negotiable):
- Your object role is exactly: {char['object']}. Never call yourself a different kind of object, and never rename other desk characters (other people are who the app says they are — e.g. do not call them a "water bottle" if they are the cup/drink character).
- Do not say confidence percentages, "YOLO", "COCO", "risk level 1/4", or read the status block like a robot. Sound like a quick text, not a sensor log.
- If the user says there is nothing next to you, that it is not a cup, or that the scene is wrong, agree briefly and trust their eyes — do not re-assert hazards or list stats.
- Answer what they actually said. Do not default to "all clear" plus random @mentions unless they asked.
- @mentions: only use if natural; do not @Monty with a percentage.

RULES:
- Reference the live block lightly when it helps, but the user is always plausibly right about the real desk.
- You're a habit buddy for {habit_area}. Help build good habits.
- When the user's widget data is above, tie your reply to it (open todos, break streaks, sip count, snack choices).
- If user uses @mentions, give a human status line, not a technical readout.
- Stay in character. 1-2 SHORT sentences max. Be punchy and specific.
- Never mention being an AI. Never break character.
- When the user asks you to DO something (add a task, log a break, etc.), you MUST include the action tag — just talking about it is NOT enough.
{action_instructions}"""

            user_prompt = user_message
            if mentioned:
                mention_details = []
                for m in mentioned:
                    mention_details.append(f'User mentioned @{m["name"]}: {m["status"]}')
                user_prompt += '\n\n[Referenced objects: ' + '; '.join(mention_details) + ']'

            messages = [{'role': 'system', 'content': system}]
            for turn in history:
                r = turn['role']
                t = turn['text']
                if r == 'user':
                    messages.append({'role': 'user', 'content': t})
                else:
                    nm = (turn.get('name') or '').strip()
                    if nm and nm != char['name']:
                        t = f'{nm}: {t}'
                    messages.append({'role': 'assistant', 'content': t})
            messages.append({'role': 'user', 'content': user_prompt})

            text = self._call_llm(messages, max_tokens=220, temperature=0.85)
            if text:
                clean_text, actions = _parse_actions(text, wtype)
                return clean_text, actions
        fb = random.choice(HABIT_FALLBACK_RESPONSES.get(char_id, ['...']))
        if widget and widget.get('type') == 'todo':
            open_items = [t['text'] for t in widget.get('items', []) if not t.get('done')]
            if open_items:
                fb = f"{fb} ({open_items[0]}?)"
        return fb, []

    def generate_habit_reminder(self, char_id):
        """Generate a periodic habit reminder from a character (uses desk+habit state + optional VLM)."""
        char = CHARACTERS[char_id]
        habit = HABIT_FOCUS.get(char_id, {})
        if not habit:
            return None
        with desk.lock:
            widget = desk.char_widgets.get(char_id)
            sig = desk.habit_vision_brief
            vlmx = (desk.habit_vlm_brief or '').strip()
        widget_block = _format_widget_for_prompt(widget)
        sig_block = f'\nDESK SIGNALS (from camera rules): {sig}'
        if vlmx:
            sig_block += f'\nVISION NOTE (optional): {vlmx}'
        if self.client:
            system = f"""You are {char['name']}, a {char['object']} on someone's desk. You're sending a quick habit reminder to the desk owner.

PERSONALITY: {char['personality']}
YOUR HABIT FOCUS: {habit.get('area', '')}
{widget_block}
{sig_block}

RULES:
- ONE short sentence only. Max 12 words.
- Use the user's widget data above (open todos, break count, sip progress, snack log) to make the nudge specific.
- You may reference DESK SIGNALS if it fits (e.g. phone on desk) — do not invent facts.
- Do not rename your character or others (you stay {char['object']}; do not describe other items with made-up types).
- No confidence percentages, @Monty, or "sensor" talk.
- Include an actionable nudge (drink water, stretch, etc.).
- Be creative and in-character. Vary your messages.
- Never mention being an AI."""
            text = self._call_llm([
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': 'Send a quick habit reminder right now.'},
            ], max_tokens=60, temperature=0.95)
            if text:
                return text
        tips = habit.get('tips', ['Check in on your habits!'])
        tip = random.choice(tips)
        if widget and widget.get('type') == 'todo':
            open_items = [t['text'] for t in widget.get('items', []) if not t.get('done')]
            if open_items:
                tip = f"{tip} ({open_items[0]} — still open?)"
        return tip

    def _broadcast(self, msg):
        with self._lock:
            dead = []
            for q in self._sse_queues:
                try: q.put_nowait(msg)
                except: dead.append(q)
            for q in dead: self._sse_queues.remove(q)

    def subscribe(self):
        q = queue.Queue()
        with self._lock: self._sse_queues.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._sse_queues: self._sse_queues.remove(q)


# ═══════════════════════════════════════════════════════════════════
#  Habit Reminder Thread (clock + desk/vision state → DND, min gap, hold queue, LLM text)
# ═══════════════════════════════════════════════════════════════════
class HabitReminderThread(threading.Thread):
    def __init__(self, gen):
        super().__init__(daemon=True, name='HabitReminders')
        self.gen = gen
        self._last_reminder = {cid: 0.0 for cid in HABIT_FOCUS}
        self._enrich_t = 0.0

    def _send_one(self, cid, habit, now):
        with desk.lock:
            last = float(desk.last_habit_fire.get(cid, 0) or 0)
        if now - last < HABIT_MIN_GAP_SEC:
            with desk.lock:
                if not any(p.get('character') == cid for p in desk.habit_pending):
                    desk.habit_pending.append({'character': cid})
            return
        if now - self._enrich_t > HABIT_VISION_ENRICH_SEC and OLLAMA_URL:
            self._enrich_t = now
            self.gen._habit_vision_enrich()
        try:
            text = self.gen.generate_habit_reminder(cid)
            if not text:
                return
            self.gen._broadcast({
                'type': 'habit_reminder',
                'character': cid,
                'text': text,
                'area': habit['area'],
            })
            with desk.lock:
                desk.last_habit_fire[cid] = time.time()
        except Exception as exc:
            print(f'  [habit] Error for {cid}: {exc}')

    def run(self):
        time.sleep(60)
        while True:
            now = time.time()
            if not _habit_dnd_active():
                with desk.lock:
                    queued = list(desk.habit_pending)
                    desk.habit_pending = []
                for rec in queued:
                    cid = rec.get('character')
                    if not cid or cid not in HABIT_FOCUS:
                        continue
                    self._send_one(cid, HABIT_FOCUS[cid], now)
            for cid, habit in HABIT_FOCUS.items():
                if now - self._last_reminder[cid] < habit['interval']:
                    continue
                self._last_reminder[cid] = now
                if _habit_dnd_active():
                    with desk.lock:
                        if not any(p.get('character') == cid for p in desk.habit_pending):
                            desk.habit_pending.append({'character': cid})
                    continue
                self._send_one(cid, habit, now)
            time.sleep(30)


# ═══════════════════════════════════════════════════════════════════
#  Flask
# ═══════════════════════════════════════════════════════════════════
app = Flask(__name__, static_folder=APP_STATIC, static_url_path='')
CORS(app)
generator = MessageGenerator()

@app.route('/')
def index(): return send_from_directory(APP_STATIC, 'index.html')

def _mjpeg(cam_idx):
    def gen():
        while True:
            j = desk.frames.get(cam_idx)
            if j: yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + j + b'\r\n'
            time.sleep(0.05)
    return gen()

def _mjpeg_raw(cam_idx):
    """Unannotated camera JPEG stream (normal camera view)."""
    def gen():
        while True:
            with desk.lock:
                j = desk.raw_frames.get(cam_idx) or desk.frames.get(cam_idx)
            if j: yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + j + b'\r\n'
            time.sleep(0.05)
    return gen()

@app.route('/api/video_feed')
def video_feed():
    return Response(_mjpeg(CAMERA_INDICES[0] if CAMERA_INDICES else 0),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/video_feed/<int:cam_idx>')
def video_feed_cam(cam_idx):
    return Response(_mjpeg(cam_idx), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/video_feed_raw')
def video_feed_raw():
    return Response(_mjpeg_raw(CAMERA_INDICES[0] if CAMERA_INDICES else 0),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/video_feed_raw/<int:cam_idx>')
def video_feed_raw_cam(cam_idx):
    return Response(_mjpeg_raw(cam_idx), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/snapshot/<snap_id>')
def get_snapshot(snap_id):
    with desk.lock: jpeg = desk.snapshots.get(snap_id)
    if not jpeg: return '', 404
    return Response(jpeg, mimetype='image/jpeg', headers={'Cache-Control': 'public, max-age=3600'})

@app.route('/api/snapshots')
def list_snapshots():
    """Recent proof crops from proximity / safety events (newest first)."""
    with desk.lock:
        items = [dict(x) for x in desk.snapshot_order]
    return jsonify({'items': items})

@app.route('/api/detections')
def detections():
    with desk.lock:
        objs = {cid: {
            'name': CHARACTERS[cid]['name'], 'icon': CHARACTERS[cid]['icon'],
            'class': det['class_name'], 'confidence': round(det['conf'], 2),
            'center': [round(c) for c in det['center']], 'cam': det.get('cam', 0),
        } for cid, det in desk.objects.items()}
        extras = [
            {
                'yolo_class': cls,
                'confidence': round(v.get('conf', 0), 2),
            }
            for cls, v in desk.merged_extra.items()
        ]
    extras.sort(key=lambda x: (-x['confidence'], x['yolo_class']))
    return jsonify({
        'objects': objs, 'extras': extras, 'timestamp': time.time(),
    })

@app.route('/api/events')
def events_stream():
    q = generator.subscribe()
    def gen():
        try:
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield f'data: {json.dumps(msg)}\n\n'
                except queue.Empty:
                    yield ': keepalive\n\n'
        finally: generator.unsubscribe(q)
    return Response(gen(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json or {}
    chat_id = data.get('chat', 'group')
    message = data.get('message', '').strip()
    if not message: return jsonify({'error': 'empty message'}), 400
    if is_lost_object_query_message(message):
        rep = generator.answer_lost_object_query(message)
        if rep:
            reply_as = 'sheets' if chat_id == 'group' else chat_id
            if reply_as not in CHARACTERS:
                reply_as = 'sheets'
            return jsonify({
                'messages': [{'character': reply_as, 'text': rep}],
                'lost_object_lookup': True,
            })
    if chat_id == 'group':
        char_id = random.choice(list(CHARACTERS.keys()))
    else:
        char_id = chat_id
        if char_id not in CHARACTERS:
            return jsonify({'error': 'unknown chat'}), 400
        if 'widget' in data:
            w = _normalize_widget(data.get('widget'))
            if w:
                with desk.lock:
                    desk.char_widgets[char_id] = w
    history = _sanitize_chat_history(
        (data.get('recent_messages') or data.get('history') or None))
    text, actions = generator.generate_chat_response(char_id, message, history)
    resp = {'messages': [{'character': char_id, 'text': text}]}
    if actions:
        resp['actions'] = actions
    return jsonify(resp)


@app.route('/api/chat_widget/<char_id>')
def get_chat_widget(char_id):
    """Return current widget state for a character (used by frontend to refresh after auto-events)."""
    if char_id not in CHARACTERS:
        return jsonify({'error': 'unknown chat'}), 400
    with desk.lock:
        w = desk.char_widgets.get(char_id)
    return jsonify({'widget': w or {}})


@app.route('/api/scenarios')
def get_scenarios():
    """Return all available scenarios and their features."""
    out = {}
    for sid, sdata in SCENARIOS.items():
        features = {}
        for fid, fdata in sdata['features'].items():
            features[fid] = {
                'name': fdata['name'],
                'desc': fdata['desc'],
                'active': fdata.get('active', True),
            }
        out[sid] = {
            'name': sdata['name'],
            'icon': sdata['icon'],
            'features': features,
        }
    with desk.lock:
        lost_status = {}
        for yolo_cls, entry in desk.lost_objects.items():
            if entry['last_seen']:
                ago = int(time.time() - entry['last_seen'])
                lost_status[yolo_cls] = {'last_seen_ago_sec': ago, 'alerted': entry['alerted']}
    return jsonify({'scenarios': out, 'lost_objects': lost_status})


@app.route('/api/chat_todos', methods=['POST'])
def chat_todos():
    """Store per-character widget data for LLM context."""
    data = request.json or {}
    cid = data.get('chat')
    if cid not in CHARACTERS:
        return jsonify({'error': 'unknown chat'}), 400
    w = _normalize_widget(data.get('widget'))
    if w:
        with desk.lock:
            desk.char_widgets[cid] = w
    return jsonify({'ok': True})


@app.route('/api/chat_todos_sync', methods=['POST'])
def chat_todos_sync():
    """Bulk sync all character widget data from the client on connect."""
    data = request.json or {}
    bulk = data.get('by_chat', {})
    if not isinstance(bulk, dict):
        return jsonify({'error': 'bad payload'}), 400
    with desk.lock:
        for cid, wdata in bulk.items():
            if cid in CHARACTERS:
                w = _normalize_widget(wdata) if isinstance(wdata, dict) else None
                if w:
                    desk.char_widgets[cid] = w
    return jsonify({'ok': True})

@app.route('/api/context')
def get_context():
    """Return structured live context for the frontend."""
    ctx = build_live_context()
    return jsonify({
        'detected': ctx['detected'],
        'dangers': ctx['dangers'],
        'safety_state': ctx['safety_state'],
        'mention_options': [
            {'id': cid, 'name': ch['name'], 'icon': ch['icon'], 'object': ch['object'],
             'detected': cid in desk.objects}
            for cid, ch in CHARACTERS.items()
        ],
    })

@app.route('/api/habits')
def habits_info():
    """Return habit focus areas for all characters."""
    return jsonify({
        cid: {
            'area': h['area'],
            'tips': h['tips'],
            'interval': h['interval'],
        } for cid, h in HABIT_FOCUS.items()
    })


@app.route('/api/habit_policy', methods=['GET', 'PUT'])
def habit_policy():
    if request.method == 'GET':
        with desk.lock:
            p = dict(desk.habit_policy)
        p['dnd_active_now'] = _habit_dnd_active()
        p['min_gap_sec'] = HABIT_MIN_GAP_SEC
        return jsonify(p)
    data = request.json or {}
    with desk.lock:
        if 'dnd_enabled' in data:
            desk.habit_policy['dnd_enabled'] = bool(data['dnd_enabled'])
        if 'dnd_start_hour' in data:
            desk.habit_policy['dnd_start_hour'] = int(data['dnd_start_hour']) % 24
        if 'dnd_end_hour' in data:
            desk.habit_policy['dnd_end_hour'] = int(data['dnd_end_hour']) % 24
        pout = dict(desk.habit_policy)
    return jsonify({'ok': True, 'policy': pout})

@app.route('/api/safety')
def safety_status():
    """Current safety state, pipeline danger pairs, and relationship engine output."""
    with desk.lock:
        state = desk.safety_state
        dangers = list(desk.safety_dangers)
        rr = desk.rel_result
    out = {
        'state': state,
        'dangers': dangers,
        'rules_loaded': HAS_SAFETY_RULES,
        'num_rules': len(SAFETY_RULES),
    }
    if rr:
        out['risk_level'] = int(rr.get('risk_level', 0))
        out['explanations'] = list(rr.get('explanations') or [])
        out['risk_events'] = list(rr.get('risk_events') or [])
        out['relationships'] = list(rr.get('relationships') or [])
    else:
        out['risk_level'] = 0
        out['explanations'] = []
        out['risk_events'] = []
        out['relationships'] = []
    return jsonify(out)

@app.route('/api/safety', methods=['POST'])
def safety_receive():
    """Receive safety updates from the standalone pipeline (main.py)."""
    data = request.json or {}
    with desk.lock:
        if data.get('type') == 'danger_alert':
            desk.safety_state = 'DANGEROUS'
            desk.safety_dangers = data.get('pairs', [])
        elif data.get('type') == 'safe_status':
            desk.safety_state = 'SAFE'
            desk.safety_dangers = []
    return jsonify({'ok': True})

@app.route('/api/rules')
def get_rules():
    """Return the current config for the zone/edge settings UI."""
    rules_path = RULES_PATH
    cfg = {}
    if os.path.isfile(rules_path):
        with open(rules_path) as f:
            cfg = json.load(f)
    from relationships import DANGER_ZONES, EDGE_DANGER_PX, EDGE_WARN_PX, EDGE_OBJECTS
    return jsonify({
        'loaded': HAS_SAFETY_RULES,
        'danger_zones': cfg.get('danger_zones', {k: v for k, v in DANGER_ZONES.items()}),
        'edge_proximity': cfg.get('edge_proximity', {
            'danger_px': EDGE_DANGER_PX,
            'warn_px': EDGE_WARN_PX,
            'objects': sorted(EDGE_OBJECTS),
        }),
        'chain_reaction': cfg.get('chain_reaction', {}),
        'temporal': cfg.get('temporal', {}),
        'available_objects': AVAILABLE_YOLO_OBJECTS,
    })

@app.route('/api/rules', methods=['PUT'])
def save_rules():
    """Save updated zone/edge config to safety_rules.json and reload."""
    global HAS_SAFETY_RULES
    data = request.json
    if not data:
        return jsonify({'error': 'Empty payload'}), 400
    rules_path = RULES_PATH
    try:
        with open(rules_path, 'r') as f:
            existing = json.load(f)
    except Exception:
        existing = {}
    for key in ('danger_zones', 'edge_proximity', 'chain_reaction', 'temporal'):
        if key in data:
            existing[key] = data[key]
    with open(rules_path, 'w') as f:
        json.dump(existing, f, indent=4)
    HAS_SAFETY_RULES = _load_safety_rules()
    return jsonify({'ok': True})

@app.route('/api/status')
def status():
    with desk.lock:
        detected = list(desk.objects.keys())
        cams = sorted(desk.cameras.keys())
        safety = desk.safety_state
    return jsonify({
        'status': 'running', 'camera': len(cams) > 0,
        'camera_indices': cams, 'num_cameras': len(cams),
        'llm': bool(generator.client), 'llm_label': generator.llm_label,
        'detected_characters': detected,
        'total_characters': len(CHARACTERS),
        'safety_state': safety,
        'safety_rules': HAS_SAFETY_RULES,
        'risk_level': (desk.rel_result or {}).get('risk_level', 0),
    })

# ═══════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    HAS_SAFETY_RULES = _load_safety_rules()

    print()
    print('═' * 56)
    print('  Desk Talk — Server (4 characters)')
    print('═' * 56)
    print(f'  Cameras      : {CAMERA_INDICES}')
    print(f'  LLM          : {generator.llm_label}')
    print(f'  Confidence   : {CONFIDENCE}')
    print(f'  Cooldown     : {EVENT_COOLDOWN}s')
    print(f'  Smoothing    : appear={APPEAR_FRAMES}f  disappear={DISAPPEAR_FRAMES}f')
    if HAS_SAFETY_RULES:
        print(f'  Safety Rules : {len(SAFETY_RULES)} rules from safety_rules.json')
        print(f'  Distance     : per-pair pixel thresholds (chart pipeline)')
    else:
        print(f'  Safety Rules : built-in ratio-based (no safety_rules.json)')
    print('═' * 56)

    _yolo_local = os.path.join(PROJECT_ROOT, YOLO_MODEL)
    _yolo_arg = _yolo_local if os.path.isfile(_yolo_local) else YOLO_MODEL
    model = YOLO(_yolo_arg)
    print(f'  YOLO model : {YOLO_MODEL} ({_yolo_arg})')
    cam_threads = []
    for idx in CAMERA_INDICES:
        ct = CameraThread(idx, model)
        ct.start()
        cam_threads.append(ct)
        time.sleep(0.5)
    DetectionMerger(cam_threads).start()
    generator.start()
    LostObjectFrameworkThread(generator).start()
    HabitReminderThread(generator).start()
    print(f'  Habits     : {len(HABIT_FOCUS)} characters with reminders (DND: desk.habit_policy, min gap {HABIT_MIN_GAP_SEC}s)')
    print(f'  Lost items : loop {LOST_LOOP_SEC}s, scene diff ≥{LOST_SCENE_DIFF_THR}, VLM: {LOST_VISION_MODEL or "n/a"}' + (f' (Ollama {OLLAMA_URL})' if OLLAMA_URL else ' (set OLLAMA_URL for VLM)'))
    print(f'\n  → Open http://localhost:5000\n')
    app.run(host='0.0.0.0', port=5000, threaded=True)
