"""
Desk Talk — Backend Server
8-character desk ecosystem with relationship-driven interactions.
Now integrated with the safety_rules.json pipeline for per-pair
pixel-based distance thresholds (chart flow).

Usage:  python server.py
Then open http://localhost:5000
"""

import os, sys, json, time, math, uuid, random, threading, queue
from collections import OrderedDict

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
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
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
CONFIDENCE       = float(os.getenv('CONFIDENCE', '0.45'))
EVENT_COOLDOWN   = int(os.getenv('EVENT_COOLDOWN', '25'))
APPEAR_FRAMES    = int(os.getenv('APPEAR_FRAMES', '10'))
DISAPPEAR_FRAMES = int(os.getenv('DISAPPEAR_FRAMES', '40'))
MAX_SNAPSHOTS    = 150
MIN_LLM_INTERVAL = float(os.getenv('MIN_LLM_INTERVAL', '6'))
LLM_MAX_RETRIES  = 3

# ═══════════════════════════════════════════════════════════════════
#  Characters (8 desk objects)
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
        'yolo_classes': ['laptop', 'tv', 'keyboard'],
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
    'zip': {
        'name': 'Zip', 'icon': '🔌', 'object': 'Cable / Charger',
        'personality': (
            'Chaotic and unpredictable. Causes accidents unintentionally '
            'and always denies responsibility. Moves frequently, '
            'creates chain reactions. "I didn\'t touch anything."'
        ),
        'yolo_classes': ['remote', 'tie'],
    },
    'surge': {
        'name': 'Surge', 'icon': '🔋', 'object': 'Power Bank',
        'personality': (
            'Physically dominant but emotionally unaware. '
            'Does not realize its weight or heat output is a problem. '
            'Oblivious, heavy, well-meaning but clueless.'
        ),
        'yolo_classes': ['mouse'],
    },
    'buzz': {
        'name': 'Buzz', 'icon': '📱', 'object': 'Phone',
        'personality': (
            'Charismatic and distracting. Attention-seeking. '
            'Does not cause danger directly but reshapes the ecosystem '
            'by pulling user attention and encouraging clutter. '
            '"Hey, just one more scroll."'
        ),
        'yolo_classes': ['cell phone'],
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
    rules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'safety_rules.json')
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
    ('zip', 'glug',    'glug',   'critical', 1.3),
    ('zip', 'monty',   'monty',  'high',     1.0),
    ('zip', 'buzz',    'buzz',   'medium',   0.9),
    ('zip', 'sheets',  'sheets', 'medium',   0.9),
    ('zip', 'surge',   'surge',  'medium',   0.9),
    ('surge', 'monty',  'monty',  'high',    1.0),
    ('surge', 'sheets', 'sheets', 'high',    0.8),
    ('munch', 'monty',  'monty',  'high',    1.3),
    ('munch', 'sheets', 'sheets', 'medium',  1.0),
    ('munch', 'glug',   'glug',   'medium',  1.0),
    ('munch', 'buzz',   'buzz',   'low',     0.7),
    ('buzz', 'monty',   'monty',  'low',     0.7),
    ('buzz', 'glug',    'glug',   'medium',  0.9),
]

SYMBIOTIC_RULES = [
    ('buzz',  'monty', 'buzz',  0.6),
]

RELATIONSHIP_DESCRIPTIONS = {
    frozenset({'glug', 'monty'}):  'Cup/liquid dangerously close to Laptop — existential spill risk!',
    frozenset({'glug', 'sheets'}): 'Cup/liquid near Paper — water damage risk.',
    frozenset({'zip', 'glug'}):    'Cable near Cup — potential knock-over trigger!',
    frozenset({'zip', 'monty'}):   'Cable near Laptop — sudden tug/pull damage risk.',
    frozenset({'zip', 'buzz'}):    'Cable near Phone — pull-off-desk risk.',
    frozenset({'zip', 'sheets'}):  'Cable near Paper — dragging risk.',
    frozenset({'zip', 'surge'}):   'Cable near Power Bank — pulling motion risk.',
    frozenset({'surge', 'monty'}): 'Power Bank on/near Laptop — pressure and heat risk.',
    frozenset({'surge', 'sheets'}): 'Power Bank on/near Paper — crushing risk.',
    frozenset({'munch', 'monty'}): 'Snack near Laptop — crumb contamination on keyboard!',
    frozenset({'munch', 'sheets'}): 'Snack near Paper — oil/grease stain risk.',
    frozenset({'munch', 'glug'}):  'Snack near Cup — increased hand movement near liquid.',
    frozenset({'munch', 'buzz'}):  'Snack near Phone — encouraging eating while scrolling.',
    frozenset({'buzz', 'monty'}):  'Phone near Laptop — competing for user attention.',
    frozenset({'buzz', 'glug'}):   'Phone near Cup — distracted placement risk.',
}

RELATIONSHIP_CONTEXT = """DESK ECOSYSTEM RELATIONSHIPS:

LAPTOP (Monty) — Fragile, anxious, emotional center (includes keyboard):
- Cup nearby = existential threat (spill on keyboard/screen). Reacts with subtle tension.
- Cable nearby = chain reaction risk (tugging). Quietly nervous.
- Power Bank nearby = pressure/heat concern. Feels squeezed.
- Snack nearby = crumb contamination on keyboard. Genuinely frustrated.
- Phone nearby = they regulate each other but compete for attention.

CUP (Glug) — Innocent, unaware of own danger:
- Near Laptop = critical spill risk but Cup doesn't understand why everyone panics.
- Near Paper = water damage risk. Cup is confused by the concern.
- Cable nearby = knock-over trigger. Cup feels unfairly targeted.

SNACK (Munch) — Hedonistic, unapologetic:
- Near Laptop = crumb contamination on keyboard. "Life's too short to worry."
- Near Cup = increases hand movement near liquids. Oblivious.
- Near Paper = oil stain risk. Dismissive.
- Near Phone = encourages eating while scrolling. Best friends.

PAPER (Sheets) — Gentle, anxious, extremely vulnerable:
- Cup nearby = terrified of water damage.
- Power Bank nearby = fears being crushed.
- Snack nearby = dreads oil stains.
- Other papers nearby = wants to be together. Gets lonely.

CABLE (Zip) — Chaotic, unpredictable, denial-prone:
- Near Cup = could knock it over. "I didn't touch anything."
- Near Laptop = sudden tug risk. "I just got pulled."
- Near Phone = could pull it off desk.
- Near Paper = might drag things.

POWER BANK (Surge) — Dominant, emotionally clueless:
- Near Laptop = pressure and heat risk. Doesn't notice.
- Near Paper = crushing risk. "I'm not that heavy."

PHONE (Buzz) — Charismatic, attention-seeking:
- Near Cup = user's distracted placement creates spill risk.
- Near Laptop = competes for user focus, encourages one-handed typing.
- Near Snack = encourages eating while scrolling."""

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
        'zip': [
            "I'm draped across the cup — if someone pulls me, that cup goes over.",
            "I'm tangled near the laptop. One tug and I could yank it off the desk.",
        ],
        'surge': [
            "I'm sitting on top of the laptop. My weight and heat are not good for it.",
            "I'm pressed up against the papers. They're getting crushed under me.",
        ],
        'buzz': [
            "I'm leaning against the cup. If I vibrate, that cup is going to fall.",
            "I'm right next to the laptop, pulling attention away from work.",
        ],
    },
    'symbiotic': {
        'buzz': ["Phone and laptop next to each other — keeping each other in check."],
    },
}

FALLBACK_RESPONSES = {
    'monty': ["Noted. Processing.", "I'll keep that in mind.", "Understood."],
    'glug': ["aww! 💧 now drink water!", "hehe ok!", "you're the best!!"],
    'munch': ["mmm yeah 🍕", "can't talk, eating.", "life's too short to worry."],
    'sheets': ['• noted\n• filed', 'Got it.', '• acknowledged'],
    'zip': ["...interesting...", "...noted...slowly...", "...mhm..."],
    'surge': ["Battery update: fine.", "OK.", "I'm just sitting here."],
    'buzz': ["ooh tell me more 📱", "hold on, notification—", "one sec, scrolling..."],
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
        'area': 'Screen breaks, posture & eye health',
        'tips': [
            "You've been staring at me for a while. Look away for 20 seconds!",
            "20-20-20 rule: every 20 min, look 20 feet away for 20 seconds.",
            "Time to rest your eyes. Close them for a moment.",
            "Screen brightness check — am I too bright for this room?",
            "How's your posture? Sit up straight, shoulders back.",
            "Stretch your wrists — you've been typing too long.",
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
    'zip': {
        'area': 'Desk organization & tidying',
        'tips': [
            "Is your desk cluttered? Take 60 seconds to tidy up.",
            "Cables tangled? A tidy desk = a tidy mind.",
            "Clear your workspace before starting the next task.",
            "Put things back where they belong. Future you will be grateful.",
        ],
        'interval': 3600,  # remind every 60 min
    },
    'surge': {
        'area': 'Energy management & standing breaks',
        'tips': [
            "Stand up and stretch! You've been sitting too long.",
            "How's your energy? Maybe take a short walk.",
            "Feeling drained? A 5-minute break recharges more than coffee.",
            "Get up, move around, come back refreshed.",
        ],
        'interval': 1800,  # remind every 30 min
    },
    'buzz': {
        'area': 'Screen time & phone discipline',
        'tips': [
            "Put me face-down. You don't need notifications right now.",
            "How many times have you checked me today? Too many.",
            "Social media can wait. Focus on what matters.",
            "Set a phone-free hour. Your productivity will soar.",
        ],
        'interval': 2400,  # remind every 40 min
    },
}

HABIT_FALLBACK_RESPONSES = {
    'glug': ["Drink water! 💧", "Hydration time!", "Sip sip! 💧"],
    'monty': ["Rest your eyes!", "Look away from the screen.", "20-20-20 rule!"],
    'munch': ["Eat something healthy!", "Snack wisely! 🍎", "Don't skip meals."],
    'sheets': ["Check your to-do list.", "What's your priority?", "Focus on one thing."],
    'zip': ["Tidy your desk.", "Organize those cables.", "Clean workspace!"],
    'surge': ["Stand up and stretch!", "Take a walk.", "Move your body."],
    'buzz': ["Put the phone down! 📱", "Less scrolling!", "Focus time!"],
}

# ═══════════════════════════════════════════════════════════════════
#  Shared state
# ═══════════════════════════════════════════════════════════════════
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
        while len(self.snapshots) > MAX_SNAPSHOTS:
            self.snapshots.popitem(last=False)
        return snap_id

desk = DeskState()

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
            for r in results:
                for box in r.boxes:
                    cls_name = self.model.names[int(box.cls[0])]
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    char_id = YOLO_TO_CHAR.get(cls_name)
                    if char_id:
                        if char_id not in new_objects or conf > new_objects[char_id]['conf']:
                            new_objects[char_id] = {
                                'class_name': cls_name,
                                'bbox': [x1, y1, x2, y2],
                                'center': [(x1+x2)/2, (y1+y2)/2],
                                'conf': conf, 'cam': self.cam_idx,
                            }

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
            for ct in self.cam_threads:
                for cid, det in ct.local_objects.items():
                    if cid not in merged or det['conf'] > merged[cid]['conf']:
                        merged[cid] = det
            with desk.lock:
                desk.objects = merged
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

    def _analyze(self, objects):
        """Run the new RelationshipAnalyzer, then emit chat events."""
        rel_analyzer.update_frame_size(desk.frame_w or 640, desk.frame_h or 480)
        result = rel_analyzer.analyze(objects)

        dangers = []
        checked = set()

        for ev in result.get('risk_events', []):
            if ev['type'] == 'zone_intrusion':
                intruder, target = ev['intruder'], ev['target']
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
    'phone': 'buzz', 'cup': 'glug', 'water': 'glug', 'bottle': 'glug',
    'keyboard': 'monty', 'keys': 'monty', 'laptop': 'monty', 'computer': 'monty',
    'cable': 'zip', 'charger': 'zip', 'cord': 'zip',
    'snack': 'munch', 'food': 'munch', 'pizza': 'munch',
    'paper': 'sheets', 'homework': 'sheets', 'book': 'sheets',
    'powerbank': 'surge', 'power bank': 'surge', 'battery': 'surge', 'mouse': 'surge',
})


def _format_duration(seconds):
    if seconds < 60:
        return f'{int(seconds)}s'
    if seconds < 3600:
        return f'{int(seconds / 60)}m {int(seconds % 60)}s'
    return f'{int(seconds / 3600)}h {int((seconds % 3600) / 60)}m'


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

    # Objects currently on desk
    if objects:
        lines.append('OBJECTS CURRENTLY DETECTED ON DESK:')
        for cid, det in objects.items():
            char = CHARACTERS[cid]
            on_desk_for = _format_duration(now - first_seen[cid]) if cid in first_seen else '?'
            detected_info.append({
                'char_id': cid, 'name': char['name'], 'object': char['object'],
                'confidence': round(det['conf'], 2), 'on_desk_for': on_desk_for,
            })
            lines.append(f'  - {char["name"]} ({char["object"]}): detected with {round(det["conf"]*100)}% confidence, on desk for {on_desk_for}')
    else:
        lines.append('NO OBJECTS CURRENTLY DETECTED ON DESK.')

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

    # Parse @mentions from user message
    if user_message:
        mention_ids = _parse_mentions(user_message)
        for cid in mention_ids:
            char = CHARACTERS[cid]
            obj_data = objects.get(cid)
            if obj_data:
                on_desk = _format_duration(now - first_seen[cid]) if cid in first_seen else '?'
                status = f'Currently on desk for {on_desk}, detected as {obj_data["class_name"]} ({round(obj_data["conf"]*100)}% confidence)'
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
2. Name the specific objects. "Cup is right next to laptop" not "something is close."
3. State the risk in plain words. "Could spill on me" not "this could end badly."
4. NO metaphors, NO vague feelings. Be literal about what's physically happening.
5. Stay in character voice but be CLEAR and BRIEF.

GOOD: "Cup is literally touching me — one nudge and I'm soaked."
GOOD: "Pizza crumbs all over my keys again, seriously?"
BAD: "I'm feeling uneasy..." / "Something's not right." / "The tension is building."

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
            other_name = CHARACTERS.get(other_id, {}).get('name', 'something')
            other_obj = CHARACTERS.get(other_id, {}).get('object', 'something')
            rule_label = event.get('rule_label', '')
            if rule_label:
                risk = rule_label
            else:
                pair = frozenset({char_id, other_id})
                risk = RELATIONSHIP_DESCRIPTIONS.get(pair, f'The {char_obj} and {other_obj} are too close together.')
            return (
                f'The {other_obj} ({other_name}) is physically very close to the '
                f'{char_obj} ({char_name}) on the desk. '
                f'The specific danger is: {risk}. '
                f'You are {char_name} (the {char_obj}). Mention "{other_name}" or "the {other_obj}" by name in your response.'
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

    def generate_chat_response(self, char_id, user_message):
        """Generate a response grounded in live context from the detection pipeline."""
        char = CHARACTERS[char_id]
        habit = HABIT_FOCUS.get(char_id, {})
        habit_area = habit.get('area', 'desk habits')
        context = build_live_context(user_message)
        mentioned = context['mentioned_objects']

        if self.client:
            system = f"""You are {char['name']}, a {char['object']} on someone's desk, chatting 1-on-1 with the desk owner.

PERSONALITY: {char['personality']}

YOUR HABIT FOCUS AREA: {habit_area}

LIVE DESK STATUS (from cameras — this is real, happening right now):
{context['summary']}

RULES:
- Reference the live desk situation above. Mention active dangers if any.
- You're a habit buddy for {habit_area}. Help build good habits.
- If user uses @mentions, tell them that object's current status.
- Stay in character. 1-2 SHORT sentences max. Be punchy and specific.
- Describe what cameras actually see if asked about the desk.
- Never mention being an AI. Never break character."""

            user_prompt = user_message
            if mentioned:
                mention_details = []
                for m in mentioned:
                    mention_details.append(f'User mentioned @{m["name"]}: {m["status"]}')
                user_prompt += '\n\n[Referenced objects: ' + '; '.join(mention_details) + ']'

            text = self._call_llm([
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user_prompt},
            ])
            if text:
                return text
        return random.choice(HABIT_FALLBACK_RESPONSES.get(char_id, ['...']))

    def generate_habit_reminder(self, char_id):
        """Generate a periodic habit reminder from a character."""
        char = CHARACTERS[char_id]
        habit = HABIT_FOCUS.get(char_id, {})
        if not habit:
            return None
        if self.client:
            system = f"""You are {char['name']}, a {char['object']} on someone's desk. You're sending a quick habit reminder to the desk owner.

PERSONALITY: {char['personality']}
YOUR HABIT FOCUS: {habit.get('area', '')}

RULES:
- ONE short sentence only. Max 12 words.
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
        return random.choice(tips)

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
#  Habit Reminder Thread
# ═══════════════════════════════════════════════════════════════════
class HabitReminderThread(threading.Thread):
    """Sends periodic habit reminders to individual chats via SSE."""
    def __init__(self, gen):
        super().__init__(daemon=True)
        self.gen = gen
        self._last_reminder = {cid: 0.0 for cid in HABIT_FOCUS}

    def run(self):
        time.sleep(60)  # wait a minute before first reminder
        while True:
            now = time.time()
            for cid, habit in HABIT_FOCUS.items():
                elapsed = now - self._last_reminder[cid]
                if elapsed >= habit['interval']:
                    self._last_reminder[cid] = now
                    try:
                        text = self.gen.generate_habit_reminder(cid)
                        if text:
                            self.gen._broadcast({
                                'type': 'habit_reminder',
                                'character': cid,
                                'text': text,
                                'area': habit['area'],
                            })
                    except Exception as exc:
                        print(f'  [habit] Error for {cid}: {exc}')
            time.sleep(30)


# ═══════════════════════════════════════════════════════════════════
#  Flask
# ═══════════════════════════════════════════════════════════════════
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)
generator = MessageGenerator()

@app.route('/')
def index(): return send_from_directory('.', 'index.html')

def _mjpeg(cam_idx):
    def gen():
        while True:
            j = desk.frames.get(cam_idx)
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

@app.route('/api/snapshot/<snap_id>')
def get_snapshot(snap_id):
    with desk.lock: jpeg = desk.snapshots.get(snap_id)
    if not jpeg: return '', 404
    return Response(jpeg, mimetype='image/jpeg', headers={'Cache-Control': 'public, max-age=3600'})

@app.route('/api/detections')
def detections():
    with desk.lock:
        objs = {cid: {
            'name': CHARACTERS[cid]['name'], 'icon': CHARACTERS[cid]['icon'],
            'class': det['class_name'], 'confidence': round(det['conf'], 2),
            'center': [round(c) for c in det['center']], 'cam': det.get('cam', 0),
        } for cid, det in desk.objects.items()}
    return jsonify({'objects': objs, 'timestamp': time.time()})

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
    if chat_id == 'group':
        char_id = random.choice(list(CHARACTERS.keys()))
    else:
        char_id = chat_id
    text = generator.generate_chat_response(char_id, message)
    return jsonify({'messages': [{'character': char_id, 'text': text}]})

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

@app.route('/api/safety')
def safety_status():
    """Pipeline chart: current danger/safe state + active danger pairs."""
    with desk.lock:
        state = desk.safety_state
        dangers = list(desk.safety_dangers)
    return jsonify({
        'state': state,
        'dangers': dangers,
        'rules_loaded': HAS_SAFETY_RULES,
        'num_rules': len(SAFETY_RULES),
    })

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
    rules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'safety_rules.json')
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
    rules_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'safety_rules.json')
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
    print('  Desk Talk — Server (8 characters)')
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

    model = YOLO(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'yolov8n.pt'))
    cam_threads = []
    for idx in CAMERA_INDICES:
        ct = CameraThread(idx, model)
        ct.start()
        cam_threads.append(ct)
        time.sleep(0.5)
    DetectionMerger(cam_threads).start()
    generator.start()
    HabitReminderThread(generator).start()
    print(f'  Habits     : {len(HABIT_FOCUS)} characters with reminders')
    print(f'\n  → Open http://localhost:5000\n')
    app.run(host='0.0.0.0', port=5000, threaded=True)
