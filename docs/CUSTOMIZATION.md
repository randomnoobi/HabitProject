# User Customization Guide

This guide explains how to customize which objects the safety monitoring system watches, which pairs it checks, and what "comfortable distance" means for each pair.

---

## Quick Start

Edit **`config/safety_rules.json`**. The system reads this file at startup (Flask server and standalone `main.py` pipeline).

---

## The Config File: `safety_rules.json`

```json
{
    "objects": [
        "cell phone",
        "laptop",
        "cup"
    ],
    "rules": [
        {
            "object_a": "cell phone",
            "object_b": "laptop",
            "safe_distance": 80,
            "label": "Phone too close to laptop"
        },
        {
            "object_a": "cup",
            "object_b": "laptop",
            "safe_distance": 120,
            "label": "Cup near laptop — spill risk!"
        }
    ],
    "distance_mode": "center"
}
```

### What Each Field Means

| Field | What It Does | Example |
|-------|-------------|---------|
| `objects` | List of object classes to detect | `["cell phone", "laptop", "cup"]` |
| `rules` | List of pair rules with per-pair thresholds | See below |
| `rules[].object_a` | First object in the pair | `"cell phone"` |
| `rules[].object_b` | Second object in the pair | `"laptop"` |
| `rules[].safe_distance` | Pixel distance below which the pair is DANGEROUS | `80` |
| `rules[].label` | Human-readable description (shown in alerts) | `"Phone too close to laptop"` |
| `distance_mode` | How to measure distance: `"center"` or `"edge"` | `"center"` |

---

## What Is "User-Defined Objects"?

The `objects` list tells the detector which things to look for in the camera feed. Only objects in this list are detected — everything else is ignored.

Object names must match **COCO class names** that the YOLO model understands:

| Common Desk Objects | COCO Class Name |
|--------------------|-----------------|
| Phone | `cell phone` |
| Laptop / Computer | `laptop` |
| Cup / Mug | `cup` |
| Water bottle | `bottle` |
| Keyboard | `keyboard` |
| Mouse | `mouse` |
| Book / Paper | `book` |
| Scissors | `scissors` |
| TV / Monitor | `tv` |

Full list of all 80 COCO classes: https://docs.ultralytics.com/datasets/detect/coco/

> **Important:** You can only detect objects that YOLO has been trained on. If you need to detect something not in the COCO dataset (e.g., "power bank"), you'll need to train a custom model. See `docs/TRAINING_GUIDE.md`.

---

## What Is "Comfortable Distance" / Safe Distance?

The `safe_distance` value for each pair is a **pixel-based threshold**.

- If two objects are **closer than this distance** (in pixels) → **DANGEROUS**
- If two objects are **further than this distance** → **SAFE**

### Why Pixels, Not Centimeters?

The camera produces a 2D image. Without calibration, we can only measure distances in pixels. This means:

- The same physical distance (e.g., 10cm) will appear as different pixel distances depending on:
  - How far the camera is from the desk
  - The camera's zoom / focal length
  - Where on the frame the objects are (center vs. edges)

### How to Pick a Good Threshold

1. Run the pipeline: `python main.py`
2. Place the two objects at the distance you consider "just barely safe"
3. Read the pixel distance shown on the preview window between them
4. Use that number (minus a small margin) as your `safe_distance`

### Typical Values

| Camera Setup | Rough Threshold Range |
|-------------|----------------------|
| Camera 30cm from desk | 150–300 px |
| Camera 60cm from desk | 80–200 px |
| Camera 1m+ from desk | 40–100 px |

> **Tip:** A top-down or fixed-angle camera makes thresholds much more consistent across the frame.

---

## How to Add a New Object

1. Check if YOLO supports the object class (see COCO list above)
2. Add the class name to the `"objects"` array in `safety_rules.json`
3. The system will now detect it

Example — adding a keyboard:

```json
"objects": ["cell phone", "laptop", "cup", "keyboard"]
```

---

## How to Add a New Distance Rule

Add a new entry to the `"rules"` array:

```json
{
    "object_a": "keyboard",
    "object_b": "cup",
    "safe_distance": 100,
    "label": "Cup near keyboard — liquid seepage risk"
}
```

The system will now automatically:
- Detect both objects
- Measure their distance every frame
- Flag it as DANGEROUS if distance < 100px
- Include it in Ollama alerts and server notifications

**No code changes needed.**

---

## Distance Modes

### `"center"` (Default)

Measures the straight-line distance between the center points of the two bounding boxes.

```
    ┌──────┐           ┌──────┐
    │  A   │           │  B   │
    │  •───┼───────────┼──•   │
    │      │  distance │      │
    └──────┘           └──────┘
```

Best for: general proximity detection.

### `"edge"`

Measures the minimum distance between the closest edges of the two bounding boxes. Returns 0 if boxes overlap.

```
    ┌──────┐  distance  ┌──────┐
    │  A   ├────────────┤  B   │
    └──────┘            └──────┘
```

Best for: detecting when objects are actually touching or very close.

Set this in `safety_rules.json`:

```json
"distance_mode": "edge"
```

---

## What Happens When a Rule Is Triggered

When a pair's distance drops below its threshold:

1. **State transitions to DANGEROUS** (logged to console)
2. **Preview window** shows a red line between the objects with the distance
3. **After 60 seconds** (configurable), the system:
   - Sends the situation description to **Ollama**
   - Ollama generates a human-readable safety alert
   - The alert is POSTed to the **Server**
4. **If still dangerous after another 60 seconds**, another update is sent
5. **When objects move apart** (for 30+ consecutive frames), state returns to **SAFE**

---

## What Happens When an Object Is Not Detected

If a rule references `cell phone ↔ laptop` but only the laptop is visible:
- The rule is **skipped** for that frame
- A log entry notes: `cell phone ↔ laptop: — (one or both not detected, skipped)`
- This is **not** treated as dangerous or safe — it's simply unevaluable

---

## Using a Custom Rules File

You can have multiple rule files for different setups:

```bash
# Default (uses config/safety_rules.json)
python main.py

# Custom rules file
python main.py --rules my_classroom_rules.json
python main.py --rules configs/strict_rules.json
```

---

## Example: Adding a Complete New Setup

Say you want to monitor a chemistry lab desk:

```json
{
    "objects": ["bottle", "cup", "laptop", "book"],
    "rules": [
        {
            "object_a": "bottle",
            "object_b": "laptop",
            "safe_distance": 150,
            "label": "Chemical bottle near laptop — contamination risk"
        },
        {
            "object_a": "cup",
            "object_b": "book",
            "safe_distance": 80,
            "label": "Liquid near lab notebook — damage risk"
        }
    ],
    "distance_mode": "edge"
}
```

Save as `lab_rules.json`, then:

```bash
python main.py --rules lab_rules.json
```

---

## Limitations

1. **Pixel-based thresholds** — not real-world distances. Must be calibrated per camera setup.
2. **YOLO class support** — can only detect the 80 COCO object classes (or custom-trained classes).
3. **Camera angle matters** — thresholds are most consistent with top-down or fixed-angle cameras.
4. **No depth** — the system can't tell if objects are beside each other vs. stacked.
5. **Detection noise** — objects may flicker in/out of detection, causing brief gaps in rule evaluation.

See `docs/LIMITATIONS.md` for the full analysis.
