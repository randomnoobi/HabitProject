# Training Guide — Staged Object Detection

This guide walks through training and testing the safety monitoring system in three stages.

---

## Pre-built Model (Quick Start)

The project ships with `yolov8n.pt` — YOLOv8 Nano, pre-trained on the COCO dataset (80 classes). This already detects `cell phone`, `laptop`, `cup`, `bottle`, `keyboard`, `book`, and many more.

**For Stages 1-3 below, you do NOT need to train a custom model.** The pre-trained model handles phone and laptop detection out of the box.

---

## Stage 1: Single Object Detection (Phone)

**Goal:** Detect one object class reliably.

### Setup

Set your `.env` to only target phones:

```ini
PIPELINE_TARGETS=cell phone
PIPELINE_DANGER_PAIRS=
```

### Test

```bash
python main.py
```

Place a phone in front of the camera. You should see:
- Green bounding box around the phone
- Label: `cell phone 85%` (or similar confidence)

### What to Observe
- Does it detect your phone consistently?
- At what angles/distances does detection fail?
- What confidence scores do you see?

### If Detection is Poor
- Try lowering confidence: `PIPELINE_CONFIDENCE=0.3`
- Try better lighting
- Try `yolov8s.pt` (more accurate, slower): set `PIPELINE_MODEL=yolov8s.pt`

---

## Stage 2: Two Object Classes (Phone + Laptop)

**Goal:** Detect both phone and laptop simultaneously.

### Setup

```ini
PIPELINE_TARGETS=cell phone,laptop
PIPELINE_DANGER_PAIRS=cell phone:laptop
```

### Test

```bash
python main.py
```

Place both a phone and a laptop in view. You should see:
- Green box around each object
- Labels for both `cell phone` and `laptop`

### What to Observe
- Are both detected simultaneously?
- Does one interfere with the other?
- What happens when they're far apart vs. close together?

---

## Stage 3: Distance Relationship Testing

**Goal:** Test the full pipeline — detect both objects and measure their distance.

### Setup

```ini
PIPELINE_TARGETS=cell phone,laptop
PIPELINE_DANGER_PAIRS=cell phone:laptop
PIPELINE_DANGER_THRESHOLD=150
```

### Test

```bash
python main.py --threshold 150
```

### Experiment

1. **Start with objects far apart** — the status bar should show green "SAFE"
2. **Slowly move the phone toward the laptop** — watch the distance number decrease
3. **When distance drops below 150px** — status bar turns red "DANGEROUS"
4. **Wait 60 seconds** — an Ollama update should be sent
5. **Move the phone away** — after ~30 frames, returns to "SAFE"

### Tuning the Threshold

The danger threshold depends on your camera setup:

| Camera Distance | Suggested Threshold |
|----------------|-------------------|
| Close (30cm) | 200-300 px |
| Medium (60cm) | 100-200 px |
| Far (1m+) | 50-100 px |

Run the pipeline and observe the distance values displayed on the preview window between the objects. Use those numbers to pick a threshold that makes sense for your setup.

---

## Custom Model Training (Advanced)

If you need to detect objects not in the COCO dataset (e.g., power bank, specific cables), you'll need to train a custom YOLOv8 model.

### Dataset Folder Layout

```
dataset/
├── images/
│   ├── train/
│   │   ├── img_001.jpg
│   │   ├── img_002.jpg
│   │   └── ...
│   └── val/
│       ├── img_050.jpg
│       └── ...
├── labels/
│   ├── train/
│   │   ├── img_001.txt
│   │   ├── img_002.txt
│   │   └── ...
│   └── val/
│       ├── img_050.txt
│       └── ...
└── data.yaml
```

### Label Format

Each `.txt` file has one line per object:

```
class_id  center_x  center_y  width  height
```

All values are normalized (0-1 relative to image size). Example:

```
0 0.45 0.52 0.12 0.08
1 0.71 0.48 0.25 0.18
```

### data.yaml

```yaml
path: ./dataset
train: images/train
val: images/val

names:
  0: phone
  1: laptop
```

### Labeling Tools

- **[Label Studio](https://labelstud.io/)** — web-based, free
- **[Roboflow](https://roboflow.com/)** — web-based, free tier, exports YOLO format
- **[CVAT](https://cvat.ai/)** — open source

### Training Command

```bash
yolo detect train data=dataset/data.yaml model=yolov8n.pt epochs=50 imgsz=640
```

### Using Your Trained Model

```ini
PIPELINE_MODEL=runs/detect/train/weights/best.pt
PIPELINE_TARGETS=phone,laptop
```

### Validation

```bash
yolo detect val data=dataset/data.yaml model=runs/detect/train/weights/best.pt
```

### Inference Demo

```bash
yolo detect predict model=runs/detect/train/weights/best.pt source=test_image.jpg
```

---

## Recommended Dataset Sizes

| Stage | Min Images | Recommended |
|-------|-----------|------------|
| Stage 1 (1 class) | 50 | 200+ |
| Stage 2 (2 classes) | 100 | 500+ |
| Production | 500+ | 2000+ |

---

## Tips

- Collect images from the same camera angle you'll use in production
- Include variety: different lighting, backgrounds, phone models
- Include "hard" examples: partially occluded objects, unusual angles
- Train/val split: 80/20 is standard
- Monitor mAP (mean Average Precision) during training — aim for >0.7
