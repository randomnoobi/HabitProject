"""
pipeline/distance.py — Distance computation and threshold evaluation.

Chart stage: "detects distance between objects"

Computes pairwise distances between detected objects and classifies
each monitored pair as DANGEROUS or SAFE using per-pair thresholds
from the user's safety_rules.json.
"""

import math
from pipeline.config import (
    DANGER_PAIRS, DISTANCE_MODE, get_threshold, get_label,
)


def _center_distance(det_a, det_b):
    """Euclidean distance between center points of two detections."""
    ax, ay = det_a['center']
    bx, by = det_b['center']
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def _edge_distance(det_a, det_b):
    """
    Minimum distance between the edges of two bounding boxes.
    Returns 0 if boxes overlap.
    """
    ax1, ay1, ax2, ay2 = det_a['bbox']
    bx1, by1, bx2, by2 = det_b['bbox']

    dx = max(0, max(ax1 - bx2, bx1 - ax2))
    dy = max(0, max(ay1 - by2, by1 - ay2))
    return math.sqrt(dx ** 2 + dy ** 2)


def compute_distances(detections, mode=None):
    """
    Compute pairwise distances for all monitored object pairs.

    Each pair uses its OWN threshold from safety_rules.json.
    For example, phone↔laptop might be 80px while cup↔laptop is 120px.

    Args:
        detections: list of detection dicts from detection.py
        mode: override for DISTANCE_MODE ("center" or "edge")

    Returns:
        list of dicts, each with:
            - pair: (class_a, class_b)
            - label: human-readable description of the rule
            - obj_a: the detection dict for object A
            - obj_b: the detection dict for object B
            - distance_px: float, pixel distance
            - dangerous: bool, True if distance < this pair's threshold
            - threshold_px: the per-pair threshold used
    """
    dist_mode = mode or DISTANCE_MODE
    dist_fn = _edge_distance if dist_mode == 'edge' else _center_distance

    # Group detections by class for efficient pair lookup
    by_class = {}
    for det in detections:
        by_class.setdefault(det['class_name'], []).append(det)

    results = []
    for pair in DANGER_PAIRS:
        class_a, class_b = pair
        objects_a = by_class.get(class_a, [])
        objects_b = by_class.get(class_b, [])

        # Per-pair threshold from safety_rules.json
        thresh = get_threshold(pair)

        if not objects_a or not objects_b:
            # One or both objects not detected — can't evaluate this rule.
            # This is logged separately; not a danger event.
            continue

        for a in objects_a:
            for b in objects_b:
                d = dist_fn(a, b)
                results.append({
                    'pair': pair,
                    'label': get_label(pair),
                    'obj_a': a,
                    'obj_b': b,
                    'distance_px': round(d, 1),
                    'dangerous': d < thresh,
                    'threshold_px': thresh,
                })

    return results


def any_dangerous(distance_results):
    """Return True if ANY pair is in the dangerous range."""
    return any(r['dangerous'] for r in distance_results)


def missing_pairs(detections):
    """
    Return a list of pair tuples that could not be evaluated because
    one or both objects were not detected in this frame.
    """
    detected_classes = {det['class_name'] for det in detections}
    missing = []
    for class_a, class_b in DANGER_PAIRS:
        if class_a not in detected_classes or class_b not in detected_classes:
            missing.append((class_a, class_b))
    return missing


def summarize(distance_results, detections=None):
    """
    Human-readable summary of all pair distances.
    Used for logging and as context for the Ollama prompt.
    """
    lines = []

    if distance_results:
        for r in distance_results:
            status = 'DANGEROUS' if r['dangerous'] else 'safe'
            lines.append(
                f'  {r["pair"][0]} ↔ {r["pair"][1]}: '
                f'{r["distance_px"]}px (threshold: {r["threshold_px"]}px) → {status}'
            )
    else:
        lines.append('  No monitored object pairs detected in frame.')

    # Log pairs that couldn't be evaluated
    if detections is not None:
        for pair in missing_pairs(detections):
            lines.append(
                f'  {pair[0]} ↔ {pair[1]}: — (one or both not detected, skipped)')

    return '\n'.join(lines)
