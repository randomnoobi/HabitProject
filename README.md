# Desk Talk

**A habit-tracking app that brings your desk objects to life.**

Desk Talk uses cameras to watch your physical desk, detect everyday objects, and turn them into chatty characters inside a mobile chat interface. When a cup wanders too close to your laptop, Monty panics. When a snack appears nearby, crumbs threaten the keyboard. Your desk objects hold each other accountable — and they hold you accountable too.

---

## Concept

Your desk is a small ecosystem. 7 objects — laptop (includes keyboard), cup, snack, paper, cable, power bank, phone — each become a persistent character that lives inside a group chat on your phone. Cameras run YOLOv8 object detection to track where each object is, whether it's being used, and how it interacts with the others.

The result: a living chatroom where your stuff talks to each other — and to you.

---

## Characters

| Character | Object | Icon | Personality |
|-----------|--------|------|-------------|
| **Monty** | Laptop | 💻 | Fragile, anxious, emotional center of the desk. Expresses discomfort through subtle physical metaphors. |
| **Glug** | Cup / Bottle | ☕ | Passive, innocent, completely unaware of its own danger. Insists it's just sitting there. |
| **Munch** | Snack / Food | 🍕 | Hedonistic and unapologetic. Dismisses all concerns. "Life's too short to worry." |
| **Sheets** | Paper / Homework | 📄 | Gentle, anxious, extremely vulnerable. Represents value and deadlines. Loves other papers. |
| **Zip** | Cable / Charger | 🔌 | Chaotic and unpredictable. Causes accidents and denies responsibility. |
| **Surge** | Power Bank | 🔋 | Physically dominant but emotionally clueless. Doesn't realize it's too heavy. |
| **Buzz** | Phone | 📱 | Charismatic, attention-seeking. Reshapes the ecosystem by pulling user attention. |

### Bubble Styles

| Character | Bubble Color | Font Style |
|-----------|-------------|------------|
| Monty | Muted blue | Clean sans-serif |
| Glug | Soft teal, rounded | Bouncy rounded |
| Munch | Warm orange-red | Comic Sans / casual |
| Sheets | Off-white with lines | Monospace, list-formatted |
| Zip | Warm orange, italic | Serif italic |
| Surge | Soft purple, bold | Bold sans-serif |
| Buzz | Pink, modern | Modern sans-serif |

---

## Character Relationships

### Interaction Map

```
                      ┌─────────────┐
            ┌────────→│   LAPTOP    │←────────┐
            │ spill!  │   (Monty)   │ pressure│
            │         └──────┬──────┘         │
            │           ↕ symbiotic            │
     ┌──────┴──────┐                   ┌──────┴──────┐
     │     CUP     │                   │ POWER BANK  │
     │   (Glug)    │                   │   (Surge)   │
     └──────┬──────┘                   └──────┬──────┘
            │           ↑ crumbs!             │
            │    ┌──────┴──────┐              │
            │    │    SNACK    │              │
     knock! │    │   (Munch)   │              │
            │    └─────────────┘              │ crush!
     ┌──────┴──────┐                   ┌──────┴──────┐
     │    CABLE    │                   │    PAPER    │
     │    (Zip)    │←── drag ─────────→│  (Sheets)   │
     └──────┬──────┘                   └─────────────┘
            │ pull!
     ┌──────┴──────┐
     │    PHONE    │
     │   (Buzz)    │ ← distracts everyone
     └─────────────┘
```

### Detailed Relationships

#### Laptop (Monty) — Fragile & Anxious

| Nearby Object | Relationship | Severity |
|---------------|-------------|----------|
| Cup (Glug) | **Existential threat** — liquid spill risk | 🔴 Critical |
| Cable (Zip) | Chain reaction risk — pulling, tugging | 🟡 High |
| Power Bank (Surge) | Pressure and heat risk | 🟡 High |
| Phone (Buzz) | Regulates each other, competes for focus | 🔵 Neutral |
| Snack (Munch) | Crumb contamination on keyboard | 🟡 High |

> **Example:** "I'm feeling a little tense… something heavy is leaning on me."

#### Cup (Glug) — Innocent but Dangerous

| Nearby Object | Relationship | Severity |
|---------------|-------------|----------|
| Laptop (Monty) | **Critical spill risk** — doesn't understand why everyone panics | 🔴 Critical |
| Paper (Sheets) | Water damage — fragile material | 🟡 High |
| Cable (Zip) | Knock-over trigger! | 🔴 Critical |
| Phone (Buzz) | Distracted placement nearby | 🟠 Medium |
| Snack (Munch) | Attracts hands → instability | 🟠 Medium |

> **Example:** "I'm just sitting here… I don't see the problem."

#### Keyboard (merged into Monty)

| Nearby Object | Relationship | Severity |
|---------------|-------------|----------|
| Snack (Munch) | **Primary enemy** — crumbs everywhere | 🟡 High |
| Cup (Glug) | Liquid seep risk | 🟡 High |
| Laptop (Monty) | Mutual dependence — symbiotic | 🟢 Positive |
| Phone (Buzz) | Causes one-handed typing errors | 🔵 Low |

> **Example:** "Oh great. More crumbs. Just what I needed."

#### Snack (Munch) — Pleasure-Driven Disruptor

| Nearby Object | Relationship | Severity |
|---------------|-------------|----------|
| Laptop (Monty) | Crumb contamination on keyboard | 🟡 High |
| Cup (Glug) | Increases hand movement near liquids | 🟠 Medium |
| Paper (Sheets) | Oil/grease stains | 🟠 Medium |
| Phone (Buzz) | Encourages eating while scrolling | 🔵 Low |

> **Example:** "Life's too short to worry about crumbs."

#### Paper / Homework (Sheets) — Gentle & Vulnerable

| Nearby Object | Relationship | Severity |
|---------------|-------------|----------|
| Cup (Glug) | Terrified of water damage | 🟡 High |
| Power Bank (Surge) | Fears being crushed | 🟡 High |
| Snack (Munch) | Dreads oil stains | 🟠 Medium |
| Cable (Zip) | Dragging risk | 🟠 Medium |

> **Example:** "I'm so bored, where are my friends?"

#### Cable / Charger (Zip) — Chaotic Connector

| Nearby Object | Relationship | Severity |
|---------------|-------------|----------|
| Cup (Glug) | **Knock-over risk** — denies involvement | 🔴 Critical |
| Laptop (Monty) | Sudden tug damage | 🟡 High |
| Phone (Buzz) | Pull-off-desk risk | 🟠 Medium |
| Paper (Sheets) | Dragging items | 🟠 Medium |
| Power Bank (Surge) | Pulling motion risk | 🟠 Medium |

> **Example:** "I didn't touch anything… I just got pulled."

#### Power Bank (Surge) — Dominant but Clueless

| Nearby Object | Relationship | Severity |
|---------------|-------------|----------|
| Laptop (Monty) | **Pressure and heat** — oblivious to the damage | 🟡 High |
| Paper (Sheets) | Crushing risk | 🟡 High |
| Cable (Zip) | Pulling motion — could fall off desk | 🟠 Medium |

> **Example:** "I'm not doing anything."

#### Phone (Buzz) — Attention Magnet

| Nearby Object | Relationship | Severity |
|---------------|-------------|----------|
| Cup (Glug) | Distracted placement near liquids | 🟠 Medium |
| Laptop (Monty) | One-handed typing errors | 🔵 Low |
| Laptop (Monty) | Competes for focus, mutual regulation | 🔵 Low |
| Snack (Munch) | Encourages eating while scrolling | 🔵 Low |
| Cable (Zip) | Pull-off-desk risk | 🟠 Medium |

> **Example:** "Hey, just one more scroll."

---

## Chat Structure

### Group Chat — "The Desk"

All eight characters share a single group thread. Messages appear based on real-time camera detection:

- **Object placed on desk** — the character announces itself
- **Object removed** — the character reacts
- **Two objects near each other** — the threatened object speaks up, sends a cropped proof screenshot
- **Symbiotic pair detected** — positive messages (Phone near Laptop)
- **@user mentions** — any character can tag you directly for habit reminders

### Individual Chats

Each character has a 1-on-1 thread with you for personal conversations.

### Proof Screenshots

When a concerning interaction is detected (e.g., cup near laptop), the speaking character sends a **cropped screenshot** zoomed into the area of the interaction. This "proof" only appears for confirmed proximity interactions — not for simple appear/disappear events.

---

## UI Design

### Philosophy

Minimalistic. The interface feels like a standard messaging app — familiar, lightweight, no learning curve. Personality lives in the chat bubbles, not in heavy UI chrome. Each character's identity comes from their bubble shape, color, and font.

### Key Screens

1. **Chat List** — 9 rows: group chat + 8 individual character chats
2. **Group Chat** — "The Desk" — all characters talk, colored bubbles, proof screenshots
3. **Individual Chat** — 1-on-1 with any character, habit tracking, progress cards
4. **Camera Feed** — Live YOLO-annotated video from all connected cameras with detection status

---

## Detection System

Cameras monitor the desk using **YOLOv8** for real-time object detection.

### YOLO Class Mappings

| Character | YOLO Classes | Notes |
|-----------|-------------|-------|
| Monty | `laptop`, `tv` | Direct match |
| Glug | `bottle`, `cup`, `wine glass` | Direct match |
| Monty | `keyboard` | Also detected as Laptop |
| Munch | `banana`, `apple`, `sandwich`, `orange`, `pizza`, `donut`, `cake`, etc. | Food items |
| Sheets | `book` | Best proxy for papers/homework |
| Zip | `remote`, `tie` | Proxy — elongated objects |
| Surge | `mouse` | Proxy — similar size/shape on desk |
| Buzz | `cell phone` | Direct match |

> **Note:** Cable, Power Bank use proxy classes. For best accuracy, train a custom YOLO model on your specific desk objects.

### Interaction Rules

All proximity interactions are **data-driven** — defined as pairs with severity levels and threshold multipliers:

| Severity | Threshold | Description |
|----------|-----------|-------------|
| 🔴 Critical | 1.5× | Triggers from further away (cup near laptop, cable near cup) |
| 🟡 High | 1.0–1.3× | Standard proximity (snack near laptop, power bank on paper) |
| 🟠 Medium | 0.9–1.0× | Moderate distance (cable near paper, snack near cup) |
| 🔵 Low | 0.7–0.8× | Only when very close (phone near laptop, snack near phone) |

### Temporal Smoothing

To avoid false positives from shaky detection:
- Objects must be seen for **10 consecutive frames** (`APPEAR_FRAMES`) to confirm "appeared"
- Objects must be missing for **40 consecutive frames** (`DISAPPEAR_FRAMES`) to confirm "disappeared"

### LLM Integration

Messages are generated by an LLM (Gemini or OpenAI) that receives:
- The full relationship chart as context
- The current desk state (which objects are detected)
- The specific event (which pair triggered, severity)
- The speaking character's personality

The LLM generates 1-2 sentences that are 100% in-character. Templates serve as a minimal fallback if no LLM is configured.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Object Detection | YOLOv8 (ultralytics) via webcams |
| Backend | Flask (Python) — camera threads, event engine, LLM proxy |
| Frontend | Vanilla HTML/CSS/JS — mobile chat simulation |
| LLM | Google Gemini (free tier) or OpenAI GPT — via OpenAI SDK |
| Real-time | SSE (Server-Sent Events) for messages, MJPEG for video |
| Detection | Temporal smoothing, spatial proximity analysis |

---

## Project Structure

```
Habit Project/
├── README.md
├── server.py                 # Entry: runs backend/server.py from repo root
├── main.py                   # Standalone safety pipeline (CLI)
├── requirements.txt
├── .env.example
├── app/                      # Web UI (Flask static + open locally)
│   ├── index.html
│   ├── style.css
│   └── app.js
├── backend/
│   ├── server.py             # Flask API, cameras, LLM, detection
│   └── relationships.py      # Spatial relationship engine
├── config/
│   └── safety_rules.json     # Per-pair thresholds + zone config
├── pipeline/                 # Chart-flow pipeline modules (main.py)
├── scripts/
│   ├── cameraOpen.py         # Camera preview + snapshot
│   └── cameraRecognition.py  # YOLO webcam preview
├── website/                  # Marketing site (GitHub Pages)
│   ├── assets/scenes/        # Scene illustrations
│   └── assets/flows/         # “How it works” flow diagrams
├── weights/                    # YOLO weights (local; *.pt gitignored)
└── docs/                     # Design notes
```

---

## Getting Started

### Prerequisites

- Python 3.8+
- A webcam (or two for full functionality)
- (Optional) A Gemini API key (free tier available) or OpenAI API key

### Installation

```bash
pip install -r requirements.txt
```

### Quick Start — Full App (Camera + LLM + Web UI)

```bash
# 1. Copy and edit the config
cp .env.example .env
# Add your GEMINI_API_KEY or OPENAI_API_KEY to .env

# 2. Start the server
python server.py

# 3. Open http://localhost:5000 in your browser
```

The server:
- Captures your webcam feed(s) and runs YOLOv8 object detection
- Maps detected objects to 8 characters with temporal smoothing
- Analyzes spatial relationships using data-driven proximity rules
- Generates in-character messages via LLM with full relationship context
- Sends cropped proof screenshots for confirmed interactions
- Streams annotated camera feed to the web UI via MJPEG
- Pushes real-time events to the frontend via Server-Sent Events

### Quick Start — Demo Mode (No Server)

Just open `app/index.html` directly in your browser. The app runs a built-in simulation with all 8 characters. No camera or server needed.

### Standalone Camera Tools

```bash
# Camera preview (press s to snapshot, q to quit)
python scripts/cameraOpen.py

# YOLO detection preview (press q to quit)
python scripts/cameraRecognition.py
```

---

## Configuration (.env)

```ini
# LLM (pick ONE — first match wins)
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-2.0-flash-lite

OPENAI_API_KEY=your-key-here
LLM_MODEL=gpt-4o-mini

# Camera indices (comma-separated for multiple)
CAMERA_INDICES=0,1

# Detection tuning
CONFIDENCE=0.45
EVENT_COOLDOWN=25
APPEAR_FRAMES=10
DISAPPEAR_FRAMES=40
```

---

## Design Principles

1. **Familiar over novel** — It's a chat app. Everyone knows how to use a chat app.
2. **Personality through typography** — Each character's identity comes from their bubble shape, color, and font.
3. **Relationship-driven** — Every interaction is grounded in the character relationship chart. The LLM uses these relationships to generate contextually appropriate messages.
4. **Ambient awareness** — Notifications are gentle. The app nudges, it doesn't nag.
5. **Camera stays invisible** — The detection system runs quietly. Users interact with characters, not with CV output.
6. **Local-first** — Everything runs on your desk, your cameras, your device.

---

## GitHub Pages (portfolio site + app demo)

Pushing to **`main`** runs [`.github/workflows/deploy-pages.yml`](.github/workflows/deploy-pages.yml), which publishes the **`app/`** UI at the site root and **`website/`** under **`/website/`**, with links to switch between them.

1. Create a new repository on GitHub and push this project (`main`).
2. On GitHub: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Open the **Actions** tab and confirm the **Deploy site to GitHub Pages** workflow succeeds.
4. Your site URL will be `https://<username>.github.io/<repo>/` (unless you use a custom domain).

Model weights (`*.pt`) are gitignored by default. Put them in **`weights/`** (defaults: `weights/yolo26n.pt`) or set `YOLO_MODEL` / `PIPELINE_MODEL` to another path.

---

## License

TBD
