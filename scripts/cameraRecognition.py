# yolo_webcam_detect.py
import os
import cv2
from ultralytics import YOLO

def main():
    cam_index = 0
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    _rel = os.getenv('YOLO_MODEL', 'weights/yolo26n.pt')
    _path = _rel if os.path.isabs(_rel) else os.path.join(_root, _rel)
    model = YOLO(_path)

    cap = cv2.VideoCapture(cam_index)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera index={cam_index}. Try 1/2...")

    print("Press 'q' to quit.")
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        # 推理（conf 可调：越高越“谨慎”，漏检可能增多）
        results = model.predict(source=frame, conf=0.35, verbose=False)

        # 把框和类别画回图像
        annotated = results[0].plot()

        cv2.imshow("YOLO - Webcam", annotated)
        if (cv2.waitKey(1) & 0xFF) == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()