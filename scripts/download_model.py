"""Downloads the YuNet face detection model into assets/ (run before building)."""
import os
import urllib.request

URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/"
       "face_detection_yunet/face_detection_yunet_2023mar.onnx")
DEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets",
                    "face_detection_yunet_2023mar.onnx")

if __name__ == "__main__":
    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    if not os.path.exists(DEST):
        urllib.request.urlretrieve(URL, DEST)
    size = os.path.getsize(DEST)
    if size < 100_000:
        os.remove(DEST)
        raise SystemExit(f"Downloaded model looks wrong ({size} bytes)")
    print(f"Model ready: {DEST} ({size} bytes)")
