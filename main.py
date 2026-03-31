#!/usr/bin/env python3
"""
main.py — Safety Monitoring Pipeline Runner

Implements the full chart flow:

    Image/footage
      → Object Recognition (real time + distance)
        → RT decision
          ├─ DANGEROUS → every 1 min → Ollama → Server
          └─ SAFE → Server informed

User customization is loaded from safety_rules.json (per-pair thresholds).

Usage:
    python main.py                          # webcam + default rules
    python main.py --rules my_rules.json    # custom rules file
    python main.py --source video.mp4       # video file
    python main.py --source photo.jpg       # single image
    python main.py --no-preview             # headless (no window)

Press 'q' in the preview window to quit.
"""

import argparse
import time
import cv2

from pipeline.config import load_rules, print_config, SHOW_PREVIEW, DANGER_UPDATE_INTERVAL
from pipeline.camera import Camera
from pipeline.detection import Detector
from pipeline.distance import compute_distances, any_dangerous, summarize
from pipeline.state import SafetyState, SAFE, DANGEROUS
from pipeline.messaging import (
    generate_danger_message, notify_server_danger, notify_server_safe,
)


def draw_overlay(frame, detections, distance_results, safety_state):
    """Draw detection boxes, distance lines, and status on the frame."""
    # Draw bounding boxes
    for det in detections:
        x1, y1, x2, y2 = [int(v) for v in det['bbox']]
        label = f"{det['class_name']} {det['confidence']:.0%}"
        color = (0, 255, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, label, (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    # Draw distance lines between monitored pairs
    for r in distance_results:
        a_center = tuple(int(v) for v in r['obj_a']['center'])
        b_center = tuple(int(v) for v in r['obj_b']['center'])

        line_color = (0, 0, 255) if r['dangerous'] else (0, 200, 0)
        cv2.line(frame, a_center, b_center, line_color, 2)

        mid_x = (a_center[0] + b_center[0]) // 2
        mid_y = (a_center[1] + b_center[1]) // 2
        dist_label = f"{r['distance_px']:.0f}/{r['threshold_px']}px"
        if r['dangerous']:
            dist_label += ' DANGER'
        cv2.putText(frame, dist_label, (mid_x - 40, mid_y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, line_color, 2)

    # Status bar at top
    state = safety_state.state
    bar_color = (0, 0, 200) if state == DANGEROUS else (0, 160, 0)
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 32), bar_color, -1)
    cv2.putText(frame, safety_state.status_line, (10, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

    return frame


def run_pipeline(rules_path=None, source=None, show_preview=None):
    """
    Main pipeline loop. Reads frames, detects, measures distance,
    decides danger/safe, and sends updates per the chart flow.
    """
    # --- Load user-defined rules ---
    load_rules(rules_path)
    print_config()

    # --- Stage: Image/footage ---
    camera = Camera(source)
    if not camera.open():
        print('ERROR: Could not open camera/video source.')
        return

    # --- Stage: Object Recognition ---
    detector = Detector()

    # --- Stage: RT decision ---
    safety = SafetyState()

    preview = show_preview if show_preview is not None else SHOW_PREVIEW
    frame_count = 0
    fps_time = time.time()

    print('\n  Pipeline running. Press q to quit.\n')

    try:
        while True:
            # --- Read frame ---
            ok, frame = camera.read()
            if not ok:
                print('  [pipeline] End of input or camera error.')
                break

            frame_count += 1

            # --- Object Recognition (real time) ---
            detections = detector.detect(frame)

            # --- Distance computation (per-pair thresholds) ---
            distance_results = compute_distances(detections)

            # --- RT → danger / safe branch ---
            is_danger = any_dangerous(distance_results)
            state_result = safety.update(is_danger)

            # --- Log state transitions ---
            if state_result['transitioned']:
                if state_result['state'] == DANGEROUS:
                    print(f'\n  ⚠️  STATE → DANGEROUS')
                    print(summarize(distance_results, detections))
                else:
                    print(f'\n  ✅  STATE → SAFE — all distances OK')
                    notify_server_safe()

            # --- DANGEROUS branch: every 1 minute → Ollama → Server ---
            if state_result['should_send']:
                summary = summarize(distance_results, detections)
                dangerous_pairs = [r for r in distance_results if r['dangerous']]

                print(f'\n  📤 Sending update #{safety.total_danger_updates + 1} '
                      f'(interval: {DANGER_UPDATE_INTERVAL}s)')
                print(summary)

                # Send to Ollama → get message
                message = generate_danger_message(summary, dangerous_pairs)
                print(f'  💬 Ollama: {message}')

                # Send to Server
                notify_server_danger(message, dangerous_pairs)

                safety.mark_sent()

            # --- Preview window ---
            if preview:
                display = frame.copy()
                draw_overlay(display, detections, distance_results, safety)

                # FPS counter
                if frame_count % 30 == 0:
                    elapsed = time.time() - fps_time
                    fps = 30 / elapsed if elapsed > 0 else 0
                    fps_time = time.time()
                    cv2.putText(display, f'{fps:.0f} FPS',
                                (display.shape[1] - 100, display.shape[0] - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

                cv2.imshow('Safety Monitor', display)
                if (cv2.waitKey(1) & 0xFF) == ord('q'):
                    print('\n  Quit by user.')
                    break
            else:
                time.sleep(0.03)

    except KeyboardInterrupt:
        print('\n  Interrupted.')
    finally:
        camera.release()
        if preview:
            cv2.destroyAllWindows()
        print(f'\n  Pipeline stopped. Processed {frame_count} frames.')
        print(f'  {safety.status_line}')


# ---------------------------------------------------------------------------
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Safety Monitoring Pipeline')
    parser.add_argument('--rules', type=str, default=None,
                        help='Path to safety_rules.json (default: ./safety_rules.json)')
    parser.add_argument('--source', type=str, default=None,
                        help='Video file, image, or camera index (default: webcam)')
    parser.add_argument('--no-preview', action='store_true',
                        help='Run without preview window')
    args = parser.parse_args()

    run_pipeline(
        rules_path=args.rules,
        source=args.source,
        show_preview=not args.no_preview,
    )
