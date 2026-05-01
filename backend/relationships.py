"""
relationships.py  —  Desk Talk Relationship Detection
=====================================================

Detects spatial relationships between desk objects using bounding boxes
and simple geometry.  Four relationship types:

  1. Edge Proximity      — object too close to desk / frame edge (fall risk)
  2. Danger-Zone         — object enters expanded danger zone of another
  3. Chain Reaction      — indirect risks via mediating objects / crowding
  4. Temporal Change     — objects moving closer over time, repeated intrusions

Risk levels:  0 (safe)  →  4 (critical)

Output format (from analyze()):
    {
      "objects":        [ ... ],
      "relationships":  [ ... ],
      "risk_level":     2,
      "risk_events":    [ ... ],
      "explanations":   [ ... ],
    }

Assumptions:
  - The webcam frame roughly represents the desk surface.
  - YOLO detections arrive as {id: {class_name, bbox, center, conf, ...}}.
  - bbox is (x1, y1, x2, y2) in pixels.
  - Detections may be noisy; thresholds should be forgiving.
"""

import math, time, os, json
from collections import deque, defaultdict

import cv2
import numpy as np

# ════════════════════════════════════════════════════════════════════
#  CONFIGURABLE CONSTANTS  —  edit these to tune sensitivity
# ════════════════════════════════════════════════════════════════════

# --- 1. Edge proximity ---
EDGE_DANGER_PX  = 35      # bbox edge within this many px of frame edge → danger
EDGE_WARN_PX    = 75      # → warning
EDGE_OBJECTS    = {        # which classes are checked for edge risk
    'cup', 'bottle', 'cell phone', 'laptop', 'remote', 'mouse',
}

# --- 2. Danger zones ---
# Each entry: expand the object bbox by `expand` px on every side.
# Overlap alone does NOT alert — only if (target_class, intruder_class) is in the
# semantic "danger" rules below (e.g. liquid + laptop, not book + laptop).
DANGER_ZONES = {
    'laptop':   {'expand': 80,  'label': 'Spill / pressure zone'},
    'keyboard': {'expand': 60,  'label': 'Crumb / debris zone'},
    'book':     {'expand': 45,  'label': 'Stacking zone'},
    'cell phone': {'expand': 35, 'label': 'Screen scratch zone'},
}

# COCO (YOLO) class names that count as *dangerous* intruders for a given target zone.
# Rationale: physics/real risk — liquids near electronics, food near keys/screen,
# water/oil near paper, sharp + phone — not e.g. a book resting near a phone.
_LIQUID = frozenset({'bottle', 'cup', 'wine glass'})
_FOOD = frozenset({
    'banana', 'apple', 'sandwich', 'orange', 'broccoli', 'carrot',
    'hot dog', 'pizza', 'donut', 'cake', 'bowl',
})
_SHARP = frozenset({'scissors', 'knife'})  # COCO: fork is thin, skip unless needed

ZONE_DANGER_INTRUDERS = {
    'laptop': _LIQUID | _FOOD,
    'keyboard': _LIQUID | _FOOD,
    'book': _LIQUID | _FOOD,
    'cell phone': _LIQUID | _SHARP,
}


def is_meaningful_zone_intrusion(target_yolo_class, intruder_yolo_class):
    """True only for semantic risks (e.g. liquid/food on laptop) — not any bbox overlap."""
    if target_yolo_class not in DANGER_ZONES or not intruder_yolo_class:
        return False
    allowed = ZONE_DANGER_INTRUDERS.get(target_yolo_class)
    if not allowed:
        return False
    ic = str(intruder_yolo_class).strip().lower()
    al = {x.lower() for x in allowed}
    return ic in al


# Pairs that commonly sit together on a desk (paper + laptop, etc.) — not a hazard.
def is_benign_proximity_pair(class_a, class_b):
    a = (class_a or '').strip().lower()
    b = (class_b or '').strip().lower()
    if not a or not b:
        return False
    benign = {
        frozenset(('book', 'laptop')),
        frozenset(('book', 'keyboard')),
        frozenset(('book', 'cell phone')),
        frozenset(('book', 'mouse')),
        frozenset(('laptop', 'keyboard')),
        frozenset(('laptop', 'mouse')),
        frozenset(('laptop', 'cell phone')),
        frozenset(('keyboard', 'mouse')),
        frozenset(('keyboard', 'cell phone')),
        frozenset(('tv', 'remote')),
    }
    return frozenset((a, b)) in benign


# --- 3. Chain reaction ---
CHAIN_PATH_RATIO     = 0.30   # object within 30 % of segment length → "between"
CROWD_RADIUS_PX      = 140    # objects within this radius are "crowded"
CROWD_MIN_OBJECTS    = 3      # minimum cluster size

# Crowding of only "normal" desk items is clutter, not an instability risk.
BENIGN_CROWD_CLASSES = frozenset({
    'book', 'laptop', 'keyboard', 'mouse', 'cell phone', 'remote', 'tv',
})


def is_benign_crowd_yolo_names(class_names):
    if len(class_names) < CROWD_MIN_OBJECTS:
        return False
    return all((c or '').strip().lower() in BENIGN_CROWD_CLASSES for c in class_names)

# --- 4. Temporal tracking ---
HISTORY_LENGTH       = 30     # frames to remember
APPROACH_MIN_FRAMES  = 8      # need this many frames to judge approach
APPROACH_RATE        = 0.12   # 12 % closer over window → approaching
REPEATED_INTRUSION_N = 3      # enter zone this many distinct times → repeated

# --- Risk scoring weights (higher = more severe) ---
RISK_WEIGHTS = {
    'edge_danger':         2,
    'edge_warning':        1,
    'zone_intrusion':      2,
    'chain_reaction':      3,
    'crowd':               1,
    'approaching':         2,
    'repeated_intrusion':  2,
}

# --- Overlay colours (BGR) ---
CLR_DANGER  = (0,   0,   255)    # red
CLR_WARN    = (0,   190, 255)    # orange-yellow
CLR_ZONE_OK = (200, 160, 0)      # teal
CLR_ZONE_HIT= (0,   50,  230)    # dark-red fill
CLR_CHAIN   = (220, 80,  255)    # magenta
CLR_TEMPORAL= (255, 200, 0)      # cyan
CLR_SAFE    = (0,   200, 0)      # green
RISK_COLORS = [                   # indexed by risk level 0-4
    (0, 200, 0),       # 0 green
    (0, 220, 220),     # 1 yellow
    (0, 140, 255),     # 2 orange
    (0, 0, 255),       # 3 red
    (0, 0, 160),       # 4 dark-red
]


# ════════════════════════════════════════════════════════════════════
#  CONFIG LOADER  —  override defaults from safety_rules.json
# ════════════════════════════════════════════════════════════════════

def load_config(path=None):
    """Load relationship config from a JSON file.  Returns the raw dict
    and also patches the module-level constants in-place."""
    if path is None:
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', 'config', 'safety_rules.json'
        )
    if not os.path.isfile(path):
        return {}

    with open(path) as f:
        data = json.load(f)

    global EDGE_DANGER_PX, EDGE_WARN_PX, EDGE_OBJECTS, DANGER_ZONES
    global CROWD_RADIUS_PX, CROWD_MIN_OBJECTS
    global APPROACH_MIN_FRAMES, APPROACH_RATE, REPEATED_INTRUSION_N
    global ZONE_DANGER_INTRUDERS

    ep = data.get('edge_proximity', {})
    if ep:
        EDGE_DANGER_PX  = ep.get('danger_px', EDGE_DANGER_PX)
        EDGE_WARN_PX    = ep.get('warn_px',   EDGE_WARN_PX)
        EDGE_OBJECTS.update(set(ep.get('objects', [])))

    dz = data.get('danger_zones', {})
    if dz:
        DANGER_ZONES.update(dz)

    # Optional: per-target YOLO class list for who may trigger a zone *alert*
    # e.g. { "laptop": ["bottle", "cup", "wine glass", "pizza", ...] }
    zd = data.get('zone_danger_intruders', {})
    if zd and isinstance(zd, dict):
        for t, names in zd.items():
            if isinstance(names, (list, tuple, set)):
                ZONE_DANGER_INTRUDERS[t] = {str(n).lower() for n in names}

    cr = data.get('chain_reaction', {})
    if cr:
        CROWD_RADIUS_PX   = cr.get('crowd_radius_px',  CROWD_RADIUS_PX)
        CROWD_MIN_OBJECTS  = cr.get('crowd_min_objects', CROWD_MIN_OBJECTS)

    tp = data.get('temporal', {})
    if tp:
        APPROACH_MIN_FRAMES  = tp.get('approach_min_frames',        APPROACH_MIN_FRAMES)
        APPROACH_RATE        = tp.get('approach_rate',               APPROACH_RATE)
        REPEATED_INTRUSION_N = tp.get('repeated_intrusion_threshold', REPEATED_INTRUSION_N)

    return data


# ════════════════════════════════════════════════════════════════════
#  STEP 2 — GEOMETRY HELPERS
# ════════════════════════════════════════════════════════════════════

def bbox_center(bbox):
    """Return (cx, cy) of an (x1, y1, x2, y2) bounding box."""
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def bbox_area(bbox):
    """Area in px² of an (x1, y1, x2, y2) bbox."""
    return max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])


def dist(p1, p2):
    """Euclidean distance between two (x, y) points."""
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def edge_distances(bbox, fw, fh):
    """Distance from each bbox side to the corresponding frame side.
    Returns dict with keys: left, top, right, bottom."""
    return {
        'left':   bbox[0],
        'top':    bbox[1],
        'right':  fw - bbox[2],
        'bottom': fh - bbox[3],
    }


def nearest_edge(bbox, fw, fh):
    """Return (min_distance, side_name) for the closest frame edge."""
    d = edge_distances(bbox, fw, fh)
    side = min(d, key=d.get)
    return d[side], side


def expand_bbox(bbox, px):
    """Grow a bbox by `px` pixels on every side."""
    return (bbox[0] - px, bbox[1] - px, bbox[2] + px, bbox[3] + px)


def bboxes_overlap(a, b):
    """True if two (x1,y1,x2,y2) boxes intersect (touching counts)."""
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def overlap_rect(a, b):
    """Return the intersection rectangle, or None if no overlap."""
    x1 = max(a[0], b[0]);  y1 = max(a[1], b[1])
    x2 = min(a[2], b[2]);  y2 = min(a[3], b[3])
    if x2 > x1 and y2 > y1:
        return (x1, y1, x2, y2)
    return None


def intrusion_depth(intruder_bbox, zone_bbox):
    """How many pixels the intruder penetrates into the zone.
    Returns 0 when there is no overlap."""
    r = overlap_rect(intruder_bbox, zone_bbox)
    if r is None:
        return 0.0
    return min(r[2] - r[0], r[3] - r[1])


def point_to_segment_dist(px, py, ax, ay, bx, by):
    """Shortest distance from point (px,py) to segment (ax,ay)→(bx,by)."""
    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


# ════════════════════════════════════════════════════════════════════
#  DRAWING HELPERS  —  dashed lines, labels, arrows
# ════════════════════════════════════════════════════════════════════

def _dashed_line(img, x1, y1, x2, y2, color, thickness=1, dash=10, gap=6):
    """Draw a dashed line from (x1,y1) to (x2,y2)."""
    length = math.hypot(x2 - x1, y2 - y1)
    if length < 1:
        return
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    pos, draw = 0.0, True
    while pos < length:
        step = dash if draw else gap
        end = min(pos + step, length)
        if draw:
            cv2.line(img,
                     (int(x1 + ux * pos), int(y1 + uy * pos)),
                     (int(x1 + ux * end), int(y1 + uy * end)),
                     color, thickness, cv2.LINE_AA)
        pos = end
        draw = not draw


def _dashed_rect(img, x1, y1, x2, y2, color, thickness=1, dash=10, gap=6):
    """Draw a dashed rectangle."""
    for ax, ay, bx, by in [(x1,y1,x2,y1), (x2,y1,x2,y2),
                            (x2,y2,x1,y2), (x1,y2,x1,y1)]:
        _dashed_line(img, ax, ay, bx, by, color, thickness, dash, gap)


def _label(img, text, x, y, bg, fg=(255,255,255), scale=0.42, thick=1):
    """Draw text at (x, y) with a filled background rectangle."""
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
    cv2.rectangle(img, (x - 3, y - th - 5), (x + tw + 3, y + 4), bg, -1)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                scale, fg, thick, cv2.LINE_AA)


def _arrow(img, pt1, pt2, color, thickness=2, tip=12):
    """Draw a line with an arrowhead at pt2."""
    cv2.arrowedLine(img, pt1, pt2, color, thickness, cv2.LINE_AA, tipLength=0.15)


def _transparent_rect(img, x1, y1, x2, y2, color, alpha=0.20):
    """Draw a semi-transparent filled rectangle."""
    overlay = img.copy()
    cv2.rectangle(overlay, (int(x1), int(y1)), (int(x2), int(y2)), color, -1)
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)


# ════════════════════════════════════════════════════════════════════
#  STEP 3 + 4 + 5 — RELATIONSHIP ANALYZER
# ════════════════════════════════════════════════════════════════════

class RelationshipAnalyzer:
    """Stateful analyzer — call analyze() each frame (or periodically).
    Stores temporal history internally.  Thread-safe if only one thread
    calls analyze()."""

    def __init__(self, frame_w=640, frame_h=480):
        self.frame_w = frame_w
        self.frame_h = frame_h

        # Temporal state
        self.history = deque(maxlen=HISTORY_LENGTH)
        self.intrusion_state = {}               # (intruder_id, target_id) → bool
        self.intrusion_enter_log = defaultdict(list)  # → [timestamp, ...]

        # Latest result (used by draw_overlays between analyze calls)
        self.latest_result = None

    # ── public API ──────────────────────────────────────────────

    def update_frame_size(self, w, h):
        self.frame_w, self.frame_h = w, h

    def analyze(self, detections):
        """Run all four detectors.  *detections* maps an id string to a
        dict with at least {class_name, bbox, center, conf}."""
        now = time.time()
        result = {
            'timestamp': now,
            'objects': [],
            'relationships': [],
            'risk_events': [],
            'explanations': [],
            'risk_level': 0,
        }

        for cid, det in detections.items():
            result['objects'].append({
                'id': cid,
                'class': det['class_name'],
                'center': [round(c, 1) for c in det['center']],
                'bbox': [round(v, 1) for v in det['bbox']],
            })

        self._edge_proximity(detections, result)
        self._danger_zone_intrusion(detections, result, now)
        self._chain_reaction(detections, result)
        self._temporal_changes(detections, result, now)

        result['risk_level'] = self._compute_risk(result['risk_events'])

        # Record frame for temporal tracking
        self.history.append({
            'time': now,
            'objects': {
                cid: {'center': tuple(det['center']),
                       'bbox':   tuple(det['bbox']),
                       'class':  det['class_name']}
                for cid, det in detections.items()
            },
        })

        self.latest_result = result
        return result

    def draw_overlays(self, frame, detections, char_names=None):
        """Draw all relationship diagrams on *frame*.
        *char_names*: optional {id: 'Monty'} for nicer labels."""
        result = self.latest_result
        if not result:
            return

        def name(cid):
            if char_names and cid in char_names:
                return char_names[cid]
            if cid in detections:
                return detections[cid]['class_name']
            return cid

        self._draw_edges(frame, detections, result, name)
        self._draw_zones(frame, detections, result, name)
        self._draw_chains(frame, detections, result, name)
        self._draw_temporal(frame, detections, result, name)
        self._draw_risk_badge(frame, result)

    # ── 1. Edge Proximity ───────────────────────────────────────

    def _edge_proximity(self, dets, result):
        fw, fh = self.frame_w, self.frame_h
        for cid, det in dets.items():
            if det['class_name'] not in EDGE_OBJECTS:
                continue
            min_d, side = nearest_edge(det['bbox'], fw, fh)

            # Laptop/keyboard often fill the top of the frame — "0px to top" is camera framing, not a fall risk.
            if (
                det['class_name'] in ('laptop', 'keyboard', 'tv')
                and (side or '').lower() == 'top'
                and min_d < 20
            ):
                continue

            if min_d < EDGE_DANGER_PX:
                severity = 'danger'
                result['risk_events'].append({
                    'type': 'edge_danger', 'object': cid,
                    'class': det['class_name'], 'edge': side,
                    'distance_px': round(min_d, 1),
                })
                result['explanations'].append(
                    f"{det['class_name']} only {int(min_d)}px from {side} edge — fall risk!")
            elif min_d < EDGE_WARN_PX:
                severity = 'warning'
                result['risk_events'].append({
                    'type': 'edge_warning', 'object': cid,
                    'class': det['class_name'], 'edge': side,
                    'distance_px': round(min_d, 1),
                })
            else:
                continue

            result['relationships'].append({
                'type': 'edge_proximity', 'severity': severity,
                'object': cid, 'edge': side,
                'distance_px': round(min_d, 1),
            })

    # ── 2. Danger-Zone Intrusion ────────────────────────────────

    def _danger_zone_intrusion(self, dets, result, now):
        for cid_t, det_t in dets.items():
            cls = det_t['class_name']
            if cls not in DANGER_ZONES:
                continue
            zcfg = DANGER_ZONES[cls]
            zone = expand_bbox(det_t['bbox'], zcfg['expand'])

            for cid_i, det_i in dets.items():
                if cid_i == cid_t:
                    continue
                depth = intrusion_depth(det_i['bbox'], zone)
                pair = (cid_i, cid_t)
                intruder_cls = det_i['class_name']
                meaningful = (
                    depth > 0
                    and is_meaningful_zone_intrusion(cls, intruder_cls)
                )

                was_in = self.intrusion_state.get(pair, False)
                is_in = meaningful
                if is_in and not was_in:
                    self.intrusion_enter_log[pair].append(now)
                self.intrusion_state[pair] = is_in

                if not meaningful:
                    continue

                d_center = dist(det_i['center'], det_t['center'])
                result['risk_events'].append({
                    'type': 'zone_intrusion',
                    'intruder': cid_i,
                    'intruder_class': intruder_cls,
                    'target': cid_t,
                    'target_class': cls,
                    'zone_label': zcfg['label'],
                    'depth_px': round(depth, 1),
                    'center_dist_px': round(d_center, 1),
                    'zone_expand': zcfg['expand'],
                })
                result['explanations'].append(
                    f"{intruder_cls} (hazard) in {cls}'s "
                    f"{zcfg['label']} — {int(depth)}px")
                result['relationships'].append({
                    'type': 'danger_zone', 'severity': 'danger',
                    'intruder': cid_i, 'target': cid_t,
                    'depth_px': round(depth, 1),
                    'zone_label': zcfg['label'],
                })

    # ── 3. Chain Reaction ───────────────────────────────────────

    def _chain_reaction(self, dets, result):
        ids = list(dets.keys())
        centers = {cid: det['center'] for cid, det in dets.items()}

        # 3a. Mediating objects — C lies on the path between intruder A
        #     and target B (from zone intrusions detected above)
        danger_pairs = set()
        for ev in result['risk_events']:
            if ev['type'] == 'zone_intrusion':
                danger_pairs.add((ev['intruder'], ev['target']))

        seen_chains = set()
        for (a, b) in danger_pairs:
            if a not in centers or b not in centers:
                continue
            ca, cb = centers[a], centers[b]
            seg_len = dist(ca, cb)
            if seg_len < 1:
                continue
            for c in ids:
                if c == a or c == b:
                    continue
                cc = centers[c]
                d = point_to_segment_dist(cc[0], cc[1],
                                          ca[0], ca[1], cb[0], cb[1])
                if d < seg_len * CHAIN_PATH_RATIO:
                    chain_key = tuple(sorted([a, b, c]))
                    if chain_key in seen_chains:
                        continue
                    seen_chains.add(chain_key)
                    result['risk_events'].append({
                        'type': 'chain_reaction',
                        'chain': [a, c, b],
                        'mediator': c,
                        'mediator_class': dets[c]['class_name'],
                        'endpoints': [dets[a]['class_name'],
                                      dets[b]['class_name']],
                        'distance_to_path': round(d, 1),
                    })
                    result['explanations'].append(
                        f"{dets[c]['class_name']} lies between "
                        f"{dets[a]['class_name']} and {dets[b]['class_name']} "
                        f"— chain reaction risk")
                    result['relationships'].append({
                        'type': 'chain_reaction', 'severity': 'high',
                        'chain': [a, c, b],
                    })

        # 3b. Crowding — cluster of objects in a tight area
        seen_clusters = set()
        for i, cid_a in enumerate(ids):
            nearby = [cid_b for cid_b in ids
                      if cid_b != cid_a
                      and dist(centers[cid_a], centers[cid_b]) < CROWD_RADIUS_PX]
            if len(nearby) + 1 >= CROWD_MIN_OBJECTS:
                cluster = tuple(sorted([cid_a] + nearby))
                if cluster in seen_clusters:
                    continue
                seen_clusters.add(cluster)
                names = [dets[c]['class_name'] for c in cluster]
                if is_benign_crowd_yolo_names(names):
                    continue
                result['risk_events'].append({
                    'type': 'crowd', 'cluster': list(cluster),
                    'count': len(cluster),
                })
                result['explanations'].append(
                    f"{len(cluster)} objects crowded together "
                    f"({', '.join(names)}) — instability risk")
                result['relationships'].append({
                    'type': 'crowd', 'severity': 'warning',
                    'cluster': list(cluster),
                })

    # ── 4. Temporal Changes ─────────────────────────────────────

    def _temporal_changes(self, dets, result, now):
        # 4a. Approach detection — are two objects getting closer?
        if len(self.history) >= APPROACH_MIN_FRAMES:
            old = self.history[-APPROACH_MIN_FRAMES]['objects']
            cur_ids = list(dets.keys())
            for i, a in enumerate(cur_ids):
                for b in cur_ids[i + 1:]:
                    if a not in old or b not in old:
                        continue
                    d_old = dist(old[a]['center'], old[b]['center'])
                    d_new = dist(dets[a]['center'], dets[b]['center'])
                    if d_old < 1:
                        continue
                    rate = (d_old - d_new) / d_old
                    if rate > APPROACH_RATE:
                        if is_benign_proximity_pair(
                                dets[a]['class_name'], dets[b]['class_name']):
                            continue
                        result['risk_events'].append({
                            'type': 'approaching',
                            'object_a': a, 'object_b': b,
                            'old_dist': round(d_old, 1),
                            'new_dist': round(d_new, 1),
                            'rate_pct': round(rate * 100, 1),
                        })
                        result['explanations'].append(
                            f"{dets[a]['class_name']} moving toward "
                            f"{dets[b]['class_name']} "
                            f"({int(rate * 100)}% closer in "
                            f"{APPROACH_MIN_FRAMES} frames)")
                        result['relationships'].append({
                            'type': 'approaching', 'severity': 'warning',
                            'from': a, 'to': b,
                            'rate_pct': round(rate * 100, 1),
                        })

        # 4b. Repeated zone intrusion — object enters, leaves, enters again
        for pair, timestamps in list(self.intrusion_enter_log.items()):
            recent = [t for t in timestamps if now - t < 60]
            self.intrusion_enter_log[pair] = recent
            if len(recent) >= REPEATED_INTRUSION_N:
                intruder, target = pair
                if intruder not in dets or target not in dets:
                    continue
                already = any(e.get('type') == 'repeated_intrusion'
                              and e.get('intruder') == intruder
                              and e.get('target') == target
                              for e in result['risk_events'])
                if not already:
                    result['risk_events'].append({
                        'type': 'repeated_intrusion',
                        'intruder': intruder, 'target': target,
                        'count': len(recent),
                    })
                    result['explanations'].append(
                        f"{dets[intruder]['class_name']} entered "
                        f"{dets[target]['class_name']}'s zone "
                        f"{len(recent)} times in the last 60 s")
                    result['relationships'].append({
                        'type': 'repeated_intrusion', 'severity': 'high',
                        'intruder': intruder, 'target': target,
                        'count': len(recent),
                    })

    # ── Risk Scoring ────────────────────────────────────────────

    @staticmethod
    def _compute_risk(events):
        """Map accumulated event weights to a 0-4 integer risk level."""
        score = sum(RISK_WEIGHTS.get(ev['type'], 1) for ev in events)
        if score == 0: return 0
        if score <= 2: return 1
        if score <= 5: return 2
        if score <= 9: return 3
        return 4

    # ════════════════════════════════════════════════════════════
    #  OVERLAY DRAWING
    # ════════════════════════════════════════════════════════════

    # -- 1. Edge Proximity overlays --

    def _draw_edges(self, frame, dets, result, name):
        h, w = frame.shape[:2]

        # Draw frame-edge margin lines
        _dashed_rect(frame,
                     EDGE_DANGER_PX, EDGE_DANGER_PX,
                     w - EDGE_DANGER_PX, h - EDGE_DANGER_PX,
                     CLR_DANGER, 1, 8, 8)

        for rel in result['relationships']:
            if rel['type'] != 'edge_proximity':
                continue
            cid = rel['object']
            if cid not in dets:
                continue
            bbox = dets[cid]['bbox']
            d_px = rel['distance_px']
            side = rel['edge']
            clr = CLR_DANGER if rel['severity'] == 'danger' else CLR_WARN

            # Highlight the object bbox
            cv2.rectangle(frame,
                          (int(bbox[0]), int(bbox[1])),
                          (int(bbox[2]), int(bbox[3])),
                          clr, 2, cv2.LINE_AA)

            # Draw measurement line from bbox edge to frame edge
            if side == 'left':
                a, b = (int(bbox[0]), int((bbox[1]+bbox[3])//2)), (0, int((bbox[1]+bbox[3])//2))
            elif side == 'right':
                a, b = (int(bbox[2]), int((bbox[1]+bbox[3])//2)), (w, int((bbox[1]+bbox[3])//2))
            elif side == 'top':
                a, b = (int((bbox[0]+bbox[2])//2), int(bbox[1])), (int((bbox[0]+bbox[2])//2), 0)
            else:
                a, b = (int((bbox[0]+bbox[2])//2), int(bbox[3])), (int((bbox[0]+bbox[2])//2), h)

            _arrow(frame, a, b, clr, 2)
            mx, my = (a[0] + b[0]) // 2, (a[1] + b[1]) // 2
            _label(frame, f"{int(d_px)}px to {side}", mx, my, clr)

    # -- 2. Danger-Zone overlays --

    def _draw_zones(self, frame, dets, result, name):
        # Draw every configured zone (even when not intruded)
        for cid, det in dets.items():
            cls = det['class_name']
            if cls not in DANGER_ZONES:
                continue
            zcfg = DANGER_ZONES[cls]
            zone = expand_bbox(det['bbox'], zcfg['expand'])

            # Dashed zone boundary
            _dashed_rect(frame,
                         int(zone[0]), int(zone[1]),
                         int(zone[2]), int(zone[3]),
                         CLR_ZONE_OK, 1, 8, 6)

            # Zone label (small)
            _label(frame, zcfg['label'],
                   int(zone[0]) + 4, int(zone[1]) + 14,
                   (60, 60, 60), (180, 180, 180), 0.35)

        # Draw intrusions
        for rel in result['relationships']:
            if rel['type'] != 'danger_zone':
                continue
            cid_i, cid_t = rel['intruder'], rel['target']
            if cid_i not in dets or cid_t not in dets:
                continue
            det_i, det_t = dets[cid_i], dets[cid_t]
            zcfg = DANGER_ZONES.get(det_t['class_name'], {})
            zone = expand_bbox(det_t['bbox'], zcfg.get('expand', 50))

            # Fill the overlap region
            orect = overlap_rect(det_i['bbox'], zone)
            if orect:
                _transparent_rect(frame, *orect, CLR_ZONE_HIT, 0.30)

            # Red zone boundary
            cv2.rectangle(frame,
                          (int(zone[0]), int(zone[1])),
                          (int(zone[2]), int(zone[3])),
                          CLR_DANGER, 2, cv2.LINE_AA)

            # Line from intruder center → target center
            pi = (int(det_i['center'][0]), int(det_i['center'][1]))
            pt = (int(det_t['center'][0]), int(det_t['center'][1]))
            cv2.line(frame, pi, pt, CLR_DANGER, 2, cv2.LINE_AA)

            # Depth label at midpoint
            mx, my = (pi[0] + pt[0]) // 2, (pi[1] + pt[1]) // 2
            _label(frame,
                   f"INTRUSION {int(rel['depth_px'])}px",
                   mx - 40, my, CLR_DANGER)

    # -- 3. Chain Reaction overlays --

    def _draw_chains(self, frame, dets, result, name):
        for rel in result['relationships']:
            if rel['type'] != 'chain_reaction':
                continue
            chain = rel['chain']  # [A, C, B]
            if not all(c in dets for c in chain):
                continue
            pts = [(int(dets[c]['center'][0]), int(dets[c]['center'][1]))
                   for c in chain]

            # Dashed path A → C → B
            _dashed_line(frame, pts[0][0], pts[0][1],
                         pts[1][0], pts[1][1], CLR_CHAIN, 2, 8, 5)
            _dashed_line(frame, pts[1][0], pts[1][1],
                         pts[2][0], pts[2][1], CLR_CHAIN, 2, 8, 5)

            # Highlight mediator with a circle
            cv2.circle(frame, pts[1], 16, CLR_CHAIN, 2, cv2.LINE_AA)
            cv2.circle(frame, pts[1], 18, (255, 255, 255), 1, cv2.LINE_AA)

            # Label at mediator
            _label(frame, f"chain: {name(chain[0])}->{name(chain[1])}->{name(chain[2])}",
                   pts[1][0] - 60, pts[1][1] - 26, CLR_CHAIN, scale=0.35)

        # Crowding circles
        for rel in result['relationships']:
            if rel['type'] != 'crowd':
                continue
            cluster = rel['cluster']
            visible = [c for c in cluster if c in dets]
            if len(visible) < 2:
                continue
            xs = [dets[c]['center'][0] for c in visible]
            ys = [dets[c]['center'][1] for c in visible]
            cx, cy = int(sum(xs) / len(xs)), int(sum(ys) / len(ys))
            _transparent_rect(frame,
                              cx - CROWD_RADIUS_PX, cy - CROWD_RADIUS_PX,
                              cx + CROWD_RADIUS_PX, cy + CROWD_RADIUS_PX,
                              CLR_WARN, 0.10)
            _label(frame, f"{len(visible)} crowded",
                   cx - 30, cy - CROWD_RADIUS_PX + 14, CLR_WARN, scale=0.4)

    # -- 4. Temporal overlays --

    def _draw_temporal(self, frame, dets, result, name):
        # Motion trails — draw recent positions as fading dots
        if len(self.history) >= 3:
            trail_frames = list(self.history)[-6:]
            for cid in dets:
                pts = []
                for hf in trail_frames:
                    obj = hf['objects'].get(cid)
                    if obj:
                        pts.append((int(obj['center'][0]),
                                    int(obj['center'][1])))
                if len(pts) >= 2:
                    for k, p in enumerate(pts[:-1]):
                        alpha = int(80 + 120 * k / len(pts))
                        r = max(2, 4 - k)
                        cv2.circle(frame, p, r, (alpha, alpha, alpha),
                                   -1, cv2.LINE_AA)

        # Approach arrows
        for rel in result['relationships']:
            if rel['type'] != 'approaching':
                continue
            a, b = rel['from'], rel['to']
            if a not in dets or b not in dets:
                continue
            pa = (int(dets[a]['center'][0]), int(dets[a]['center'][1]))
            pb = (int(dets[b]['center'][0]), int(dets[b]['center'][1]))
            _arrow(frame, pa, pb, CLR_TEMPORAL, 2)
            mx, my = (pa[0] + pb[0]) // 2, (pa[1] + pb[1]) // 2
            _label(frame, f"approaching {int(rel['rate_pct'])}%",
                   mx - 40, my - 14, CLR_TEMPORAL, scale=0.38)

        # Repeated intrusion badges
        for rel in result['relationships']:
            if rel['type'] != 'repeated_intrusion':
                continue
            cid = rel['intruder']
            if cid not in dets:
                continue
            bx = int(dets[cid]['bbox'][2]) + 4
            by = int(dets[cid]['bbox'][1])
            cv2.circle(frame, (bx + 10, by + 10), 14, CLR_DANGER, -1)
            cv2.putText(frame, str(rel['count']),
                        (bx + 4, by + 16), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (255, 255, 255), 2, cv2.LINE_AA)

    # -- Risk badge (top-left corner) --

    def _draw_risk_badge(self, frame, result):
        level = result['risk_level']
        clr = RISK_COLORS[min(level, 4)]
        n_events = len(result['risk_events'])

        cv2.rectangle(frame, (8, 8), (160, 52), (0, 0, 0), -1)
        cv2.rectangle(frame, (8, 8), (160, 52), clr, 2)
        cv2.putText(frame, f"RISK {level}/4",
                    (16, 38), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, clr, 2, cv2.LINE_AA)
        cv2.putText(frame, f"{n_events} events",
                    (100, 38), cv2.FONT_HERSHEY_SIMPLEX,
                    0.35, (180, 180, 180), 1, cv2.LINE_AA)
