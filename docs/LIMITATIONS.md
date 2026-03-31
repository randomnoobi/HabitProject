# Limitations & Assumptions

This document outlines the assumptions, simplifications, and known limitations of the safety monitoring pipeline. These are important for understanding what the system can and cannot do in its current version.

---

## 1. Pixel Distance vs. Real-World Distance

**The system measures pixel distance, not physical distance.**

Two objects that are 150 pixels apart on camera could be 5cm apart or 50cm apart, depending on:
- How far the camera is from the desk
- The camera's focal length and field of view
- Where the objects are in the frame (center vs. edges)

### Why This Matters
- The danger threshold (`PIPELINE_DANGER_THRESHOLD`) must be calibrated for each specific camera setup
- Moving the camera or changing its angle invalidates the threshold

### Future Improvement
- Top-down camera calibration with known reference distances
- Perspective correction using homography transforms
- Depth cameras (Intel RealSense, stereo vision) for true 3D distance

---

## 2. Camera Angle Effects

**A side-angle camera distorts distance perception.**

If the camera views the desk at an angle:
- Objects near the camera appear larger and further apart (in pixels)
- Objects far from the camera appear smaller and closer together
- Vertical distance on the desk may appear compressed

### Current Approach
- The system assumes a roughly overhead or front-facing camera
- Distance calculations use simple 2D pixel coordinates

### Future Improvement
- Camera calibration matrices
- Bird's-eye-view transformation
- Multiple camera fusion

---

## 3. Occlusion

**Objects can be hidden behind other objects.**

If one object is placed behind or on top of another:
- It may not be detected at all
- Its bounding box may be truncated
- Distance calculations may be inaccurate

### Current Behavior
- The system only works with objects it can see
- No detection = no distance calculation = no danger alert
- This is a false negative risk: a truly dangerous situation might not be detected

---

## 4. False Positives / False Negatives

### False Positives (Detecting something that isn't there)
- YOLO may occasionally misidentify objects (e.g., a remote control as a phone)
- Objects in the background may be detected
- Reflections or images of objects on screens may trigger detection

### False Negatives (Missing something that is there)
- Small objects far from the camera
- Objects at unusual angles
- Poor lighting conditions
- Objects partially covered

### Mitigation
- Confidence threshold (`PIPELINE_CONFIDENCE`) filters low-confidence detections
- Safe-state debouncing (`PIPELINE_SAFE_FRAMES`) prevents state flickering
- Future: temporal smoothing (require detection across multiple frames)

---

## 5. Safe-State Inference

**The chart states: "if Ollama does not receive after 1 minute, is safe."**

### Assumptions
- If the system does not send an update for 1+ minutes, the server/observer can infer the desk is safe
- This is an implicit signal, not an explicit one
- The pipeline also sends an explicit `safe_status` notification when transitioning from DANGEROUS → SAFE

### Risk
- If the pipeline crashes or the camera disconnects, no updates are sent — but this does NOT mean safe
- This is a known limitation of absence-based safety inference

### Mitigation
- The explicit `safe_status` POST handles the normal case
- Future: heartbeat mechanism (send periodic "alive + safe" messages)

---

## 6. Single-Frame Distance

**Distance is computed per-frame, not tracked over time.**

- Each frame is evaluated independently
- No object tracking (following the same phone across frames)
- If YOLO detects two phones, it can't tell which is which between frames

### Impact
- Distance may "jump" between frames if detection boxes shift
- No velocity estimation (can't predict if objects are moving toward each other)

### Future Improvement
- Object tracking (DeepSORT, ByteTrack)
- Kalman filtering for smooth distance curves
- Trajectory prediction

---

## 7. Bounding Box Accuracy

**Bounding boxes are approximate, not pixel-perfect.**

- YOLO bounding boxes have some padding and may not tightly fit the object
- Center-point distance measures the box center, not the actual object edge
- Edge distance mode uses box edges, which may not match the physical object edges

### Impact
- Distance measurements have a margin of error (typically ±20-40 pixels)
- Thresholds should account for this margin

---

## 8. Single Camera Perspective

**A single 2D camera cannot measure depth.**

- Objects at different heights on the desk (stacked books vs. flat phone) may appear close in 2D but aren't actually near each other
- The system cannot distinguish between "beside" and "on top of"

---

## 9. Processing Latency

- YOLO inference takes ~20-50ms per frame on modern hardware (CPU)
- Ollama message generation takes 1-10 seconds depending on model and hardware
- Total latency from danger event to server notification: 1-15 seconds

---

## 10. Environment Assumptions

- The camera has a stable, fixed position
- Lighting is adequate for object detection
- The desk surface provides contrast against the objects
- Network is available for Ollama (localhost) and server communication

---

## Summary Table

| Limitation | Severity | Mitigation Available |
|-----------|----------|---------------------|
| Pixel vs. real distance | Medium | Calibration per setup |
| Camera angle distortion | Medium | Top-down camera recommended |
| Occlusion | High | None (fundamental CV limitation) |
| False positives | Low | Confidence threshold |
| False negatives | Medium | Better lighting, lower threshold |
| Safe-state inference gap | Low | Explicit safe notifications |
| No object tracking | Low | Future: DeepSORT |
| Bounding box imprecision | Low | Threshold margin |
| No depth perception | Medium | Future: depth camera |
| Processing latency | Low | Acceptable for 1-min intervals |
