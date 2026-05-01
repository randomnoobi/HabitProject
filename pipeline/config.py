"""
pipeline/config.py — Central configuration for the safety monitoring pipeline.

Loads user-customizable rules from safety_rules.json (if it exists),
then falls back to environment variables / .env for everything else.
"""

import os
import json

# ---------------------------------------------------------------------------
#  .env loader (works with or without python-dotenv)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
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

# ---------------------------------------------------------------------------
#  Camera / Input
# ---------------------------------------------------------------------------
CAMERA_INDEX = int(os.getenv('PIPELINE_CAMERA', '0'))
VIDEO_SOURCE = os.getenv('PIPELINE_VIDEO', '')

# ---------------------------------------------------------------------------
#  Object Detection
# ---------------------------------------------------------------------------
MODEL_PATH = os.getenv('PIPELINE_MODEL', 'weights/yolo26n.pt')
CONFIDENCE = float(os.getenv('PIPELINE_CONFIDENCE', '0.45'))

# ---------------------------------------------------------------------------
#  User-Defined Safety Rules (from safety_rules.json)
#
#  This is the customization layer. The JSON file defines:
#    - which objects to detect
#    - which pairs to monitor
#    - per-pair safe distance thresholds
#  If the file is missing, falls back to .env values.
# ---------------------------------------------------------------------------
_RULES_PATH = None          # set by load_rules() or --rules flag
_rules_data = None          # parsed JSON

TARGET_CLASSES = []
DANGER_PAIRS = []
PAIR_THRESHOLDS = {}        # (class_a, class_b) → threshold in px
PAIR_LABELS = {}            # (class_a, class_b) → human-readable label
DANGER_THRESHOLD_PX = 150   # global fallback if a pair has no specific threshold
DISTANCE_MODE = 'center'


def load_rules(path=None):
    """
    Load safety rules from a JSON file. Call this once at startup.

    The JSON file format:
    {
        "objects": ["cell phone", "laptop", "cup"],
        "rules": [
            {"object_a": "cell phone", "object_b": "laptop", "safe_distance": 80, "label": "..."},
            ...
        ],
        "distance_mode": "center"
    }
    """
    global _RULES_PATH, _rules_data
    global TARGET_CLASSES, DANGER_PAIRS, PAIR_THRESHOLDS, PAIR_LABELS
    global DANGER_THRESHOLD_PX, DISTANCE_MODE

    # Find the rules file
    if path:
        rules_path = path
    else:
        rules_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', 'config', 'safety_rules.json'
        )

    if os.path.isfile(rules_path):
        with open(rules_path, 'r') as f:
            _rules_data = json.load(f)
        _RULES_PATH = rules_path
        print(f'  [config] Loaded rules from: {rules_path}')

        # --- Objects ---
        TARGET_CLASSES = _rules_data.get('objects', [])

        # --- Rules (per-pair thresholds) ---
        DANGER_PAIRS = []
        PAIR_THRESHOLDS = {}
        PAIR_LABELS = {}
        for rule in _rules_data.get('rules', []):
            a = rule['object_a']
            b = rule['object_b']
            pair = (a, b)
            DANGER_PAIRS.append(pair)
            PAIR_THRESHOLDS[pair] = rule.get('safe_distance', DANGER_THRESHOLD_PX)
            # Also store the reversed pair so lookup works both ways
            PAIR_THRESHOLDS[(b, a)] = PAIR_THRESHOLDS[pair]
            if 'label' in rule:
                PAIR_LABELS[pair] = rule['label']
                PAIR_LABELS[(b, a)] = rule['label']

        # --- Distance mode ---
        DISTANCE_MODE = _rules_data.get('distance_mode', DISTANCE_MODE)

        print(f'  [config] Objects: {TARGET_CLASSES}')
        print(f'  [config] Rules: {len(DANGER_PAIRS)} pair(s)')
        for pair in DANGER_PAIRS:
            t = PAIR_THRESHOLDS[pair]
            label = PAIR_LABELS.get(pair, '')
            print(f'    {pair[0]} ↔ {pair[1]}: safe_distance={t}px'
                  + (f'  ({label})' if label else ''))

    else:
        # Fallback: load from environment variables (old behavior)
        print(f'  [config] No safety_rules.json found — using .env fallbacks')
        _raw = os.getenv('PIPELINE_TARGETS', 'cell phone,laptop')
        TARGET_CLASSES = [c.strip() for c in _raw.split(',') if c.strip()]

        DANGER_THRESHOLD_PX = int(os.getenv('PIPELINE_DANGER_THRESHOLD', '150'))
        DISTANCE_MODE = os.getenv('PIPELINE_DISTANCE_MODE', 'center')

        _pairs_raw = os.getenv('PIPELINE_DANGER_PAIRS', 'cell phone:laptop')
        DANGER_PAIRS = []
        PAIR_THRESHOLDS = {}
        for _p in _pairs_raw.split(','):
            parts = [s.strip() for s in _p.split(':')]
            if len(parts) == 2:
                pair = tuple(parts)
                DANGER_PAIRS.append(pair)
                PAIR_THRESHOLDS[pair] = DANGER_THRESHOLD_PX
                PAIR_THRESHOLDS[(parts[1], parts[0])] = DANGER_THRESHOLD_PX


def get_threshold(pair):
    """
    Get the safe distance threshold for a specific (class_a, class_b) pair.
    Falls back to the global DANGER_THRESHOLD_PX if no specific rule exists.
    """
    return PAIR_THRESHOLDS.get(pair, DANGER_THRESHOLD_PX)


def get_label(pair):
    """Get the human-readable label for a pair, or a generic one."""
    return PAIR_LABELS.get(pair, f'{pair[0]} ↔ {pair[1]}')


# ---------------------------------------------------------------------------
#  State Machine Timing
# ---------------------------------------------------------------------------
DANGER_UPDATE_INTERVAL = int(os.getenv('PIPELINE_DANGER_INTERVAL', '60'))
SAFE_CONFIRM_FRAMES = int(os.getenv('PIPELINE_SAFE_FRAMES', '30'))

# ---------------------------------------------------------------------------
#  Ollama / LLM
# ---------------------------------------------------------------------------
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://localhost:11434/v1')
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama3.2')

# ---------------------------------------------------------------------------
#  Server Notification
# ---------------------------------------------------------------------------
SERVER_URL = os.getenv('PIPELINE_SERVER_URL', 'http://localhost:5000')

# ---------------------------------------------------------------------------
#  Display
# ---------------------------------------------------------------------------
SHOW_PREVIEW = os.getenv('PIPELINE_SHOW_PREVIEW', '1') == '1'

# ---------------------------------------------------------------------------
#  Summary (for logging)
# ---------------------------------------------------------------------------
def print_config():
    """Print current config to console for verification."""
    print()
    print('=' * 56)
    print('  Safety Monitoring Pipeline — Configuration')
    print('=' * 56)
    print(f'  Camera          : {VIDEO_SOURCE or f"webcam index {CAMERA_INDEX}"}')
    print(f'  Model           : {MODEL_PATH}')
    print(f'  Confidence      : {CONFIDENCE}')
    print(f'  Rules file      : {_RULES_PATH or "(env fallback)"}')
    print(f'  Target classes  : {TARGET_CLASSES}')
    print(f'  Monitored pairs : {len(DANGER_PAIRS)}')
    for pair in DANGER_PAIRS:
        t = PAIR_THRESHOLDS.get(pair, DANGER_THRESHOLD_PX)
        label = PAIR_LABELS.get(pair, '')
        print(f'    {pair[0]} ↔ {pair[1]}: {t}px'
              + (f'  — {label}' if label else ''))
    print(f'  Distance mode   : {DISTANCE_MODE}')
    print(f'  Update interval : {DANGER_UPDATE_INTERVAL}s')
    print(f'  Ollama          : {OLLAMA_URL} ({OLLAMA_MODEL})')
    print(f'  Server          : {SERVER_URL}')
    print(f'  Preview window  : {SHOW_PREVIEW}')
    print('=' * 56)
    print()
