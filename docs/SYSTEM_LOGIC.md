# System Logic — Safety Monitoring Pipeline

This document describes the system architecture based on the approved class chart.

---

## Original Chart Flow

```
Image / Footage
  → Object Recognition (real time + detects distance between objects)
    → RT (Real-Time Decision)
      ├─ Branch 1: Distance is DANGEROUS
      │    → Every 1 minute: update and send to Ollama
      │    → Ollama generates message
      │    → Send to Server
      │
      └─ Branch 2: All distance > safe distance (SAFE)
           → Server is informed of safe condition
           → (Chart note: if Ollama does not receive after 1 minute, is safe)
```

---

## Implementation Map

Each stage of the chart maps to a specific module in the codebase:

| Chart Stage | Module | Entry Function |
|-------------|--------|---------------|
| Image / Footage | `pipeline/camera.py` | `Camera.read()` |
| Object Recognition | `pipeline/detection.py` | `Detector.detect(frame)` |
| Distance Detection | `pipeline/distance.py` | `compute_distances(detections)` |
| RT → Danger/Safe | `pipeline/state.py` | `SafetyState.update(is_dangerous)` |
| Ollama Message | `pipeline/messaging.py` | `generate_danger_message(...)` |
| Send to Server | `pipeline/messaging.py` | `notify_server_danger(...)` / `notify_server_safe()` |
| Configuration | `pipeline/config.py` | All thresholds, classes, intervals |
| Full Pipeline | `main.py` | `run_pipeline()` |

---

## Stage-by-Stage Walkthrough

### Stage 1: Image / Footage (`camera.py`)

**What it does:** Reads frames from a webcam, video file, or single image.

**How it works:**
- Opens an OpenCV `VideoCapture` on the configured source
- Returns one BGR frame at a time via `read()`
- Supports live webcam (default), video files, and static images for testing

**Configurable:** `PIPELINE_CAMERA` (webcam index), `PIPELINE_VIDEO` (file path)

### Stage 2: Object Recognition (`detection.py`)

**What it does:** Runs YOLOv8 object detection on each frame, filtered to target classes.

**How it works:**
- Loads the YOLOv8 nano model (`yolov8n.pt`)
- Runs inference on every frame
- Filters results to only the classes we care about (e.g., `cell phone`, `laptop`)
- Returns structured detections with bounding boxes and center points

**Configurable:** `PIPELINE_CONFIDENCE` (detection threshold), `PIPELINE_TARGETS` (class names)

### Stage 3: Distance Detection (`distance.py`)

**What it does:** Computes pairwise pixel distance between monitored object pairs and classifies each as dangerous or safe.

**How it works:**
- Groups detected objects by class
- For each configured danger pair (e.g., phone ↔ laptop), finds all instances
- Computes distance using either center-to-center or edge-to-edge mode
- Compares against the danger threshold
- Returns a list of pair results with distance and dangerous/safe status

**Configurable:** `PIPELINE_DANGER_THRESHOLD` (pixels), `PIPELINE_DANGER_PAIRS` (which pairs to monitor), `PIPELINE_DISTANCE_MODE` (center or edge)

### Stage 4: RT Decision — Danger / Safe Branch (`state.py`)

**What it does:** Implements the state machine from the chart — the branching logic between DANGEROUS and SAFE.

**How it works:**

```
                    any pair < threshold
           ┌──────────────────────────────┐
           │                              ▼
        ┌──────┐                     ┌──────────┐
        │ SAFE │                     │ DANGEROUS │── every 1 min → send update
        └──────┘                     └──────────┘
           ▲                              │
           └──────────────────────────────┘
             all pairs safe for N consecutive frames
```

**Key behaviors:**
- **SAFE → DANGEROUS:** Transitions immediately when any monitored pair distance falls below the threshold.
- **DANGEROUS → SAFE:** Requires `SAFE_CONFIRM_FRAMES` consecutive safe frames to avoid flickering from noisy detection.
- **1-minute updates:** While in DANGEROUS state, `should_send` returns True every `DANGER_UPDATE_INTERVAL` seconds (default: 60). This matches the chart's "every 1 minute update and send to Ollama."
- **Safe inference:** Per the chart note, if Ollama does not receive an update within 1 minute, the condition is implicitly safe.

### Stage 5: Ollama Message Generation (`messaging.py`)

**What it does:** Sends a danger report to Ollama (local LLM) and gets back a human-readable safety alert.

**How it works:**
- Constructs a prompt describing the current danger situation (which objects, how close, what risk)
- Calls Ollama via its OpenAI-compatible API (`localhost:11434/v1`)
- Returns the generated alert text
- Falls back to a simple template if Ollama is unavailable

**Configurable:** `OLLAMA_URL`, `OLLAMA_MODEL`

### Stage 6: Server Notification (`messaging.py`)

**What it does:** Sends the generated message/status to the server.

**How it works:**
- **Danger:** POSTs `{type: "danger_alert", message: "...", pairs: [...]}` to `/api/safety`
- **Safe:** POSTs `{type: "safe_status", message: "All clear"}` to `/api/safety`
- Fails gracefully if the server is not running (pipeline works standalone)

**Configurable:** `PIPELINE_SERVER_URL`

---

## Data Flow Example

A typical danger scenario:

```
Frame 1-100: Phone and laptop both detected, 300px apart → SAFE
Frame 101:   Phone moved closer, now 120px apart → DANGEROUS (transition)
             └─ First update: send to Ollama immediately
             └─ Ollama: "Warning: phone is too close to laptop (120px). Move it."
             └─ POST to server: danger_alert
Frame 102-160: Still dangerous, but < 1 minute passed → no update sent
Frame 161:   1 minute elapsed → second update to Ollama
             └─ Ollama: "Phone still dangerously close to laptop. Please separate."
             └─ POST to server: danger_alert
Frame 200:   Phone moved away, 250px apart → begins safe countdown
Frame 230:   30 consecutive safe frames → SAFE (transition)
             └─ POST to server: safe_status
```

---

## Configuration Summary

All settings are in `.env` or passed as environment variables:

```ini
# What to detect
PIPELINE_TARGETS=cell phone,laptop
PIPELINE_DANGER_PAIRS=cell phone:laptop

# How close is dangerous (pixels)
PIPELINE_DANGER_THRESHOLD=150

# Distance calculation mode
PIPELINE_DISTANCE_MODE=center    # or "edge"

# How often to update Ollama when dangerous (seconds)
PIPELINE_DANGER_INTERVAL=60

# Frames needed to confirm safe (prevents flicker)
PIPELINE_SAFE_FRAMES=30

# Camera
PIPELINE_CAMERA=0
PIPELINE_CONFIDENCE=0.45

# Ollama
OLLAMA_URL=http://localhost:11434/v1
OLLAMA_MODEL=llama3.2

# Server
PIPELINE_SERVER_URL=http://localhost:5000
```

---

## Running the Pipeline

```bash
# Default: webcam + preview window
python main.py

# Custom threshold
python main.py --threshold 200

# From a video file
python main.py --source test_video.mp4

# Headless (no window)
python main.py --no-preview
```
