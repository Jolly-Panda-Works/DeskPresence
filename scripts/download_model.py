"""Downloads the face models into assets/ (run before building or running from source).

  face_detection_yunet_2023mar.onnx  OpenCV Zoo YuNet (MIT)        presence + head direction
  face_landmarker.task               Google MediaPipe (Apache 2.0)  eye tracking
"""
import os
import urllib.request

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")
MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
        "face_detection_yunet_2023mar.onnx", 100_000),
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/"
        "face_landmarker.task", 1_000_000),
}

if __name__ == "__main__":
    os.makedirs(ASSETS, exist_ok=True)
    for name, (url, min_size) in MODELS.items():
        dest = os.path.join(ASSETS, name)
        if not os.path.exists(dest):
            urllib.request.urlretrieve(url, dest)
        size = os.path.getsize(dest)
        if size < min_size:
            os.remove(dest)
            raise SystemExit(f"Downloaded {name} looks wrong ({size} bytes)")
        print(f"Model ready: {name} ({size} bytes)")
