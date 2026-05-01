# camera_preview.py
import cv2
import time

def main():
    cam_index = 0  # 如果有多个摄像头可改成 1/2...
    cap = cv2.VideoCapture(cam_index)

    # 尝试提高兼容性（尤其是 Windows）
    # cap = cv2.VideoCapture(cam_index, cv2.CAP_DSHOW)

    if not cap.isOpened():
        raise RuntimeError(f"无法打开摄像头 index={cam_index}。可尝试把 cam_index 改成 1 或 2。")

    # 可选：设置分辨率（不一定每台机器都生效）
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    print("按 q 退出；按 s 截图。")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("读取帧失败，退出。")
            break

        cv2.imshow("Camera Preview", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("s"):
            filename = f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
            cv2.imwrite(filename, frame)
            print(f"已保存 {filename}")

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()