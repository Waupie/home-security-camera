#!/usr/bin/env python3
"""
Minimal MJPEG streaming server using Picamera2 and Flask.

Hard-coded to stream 1920x1080 at ~30 FPS. No environment toggles, no
day/night logic, no GPIO — exactly what you asked for: a simple, fixed
stream that you don't need to change.

View in your browser at:
    http://<raspberry-pi-ip>:5000/
"""
from flask import Flask, Response, render_template
from picamera2 import Picamera2
from PIL import Image
from io import BytesIO
import threading
import time
try:
    import cv2
    _cv2_available = True
except Exception:
    _cv2_available = False

app = Flask(__name__)

# Hard-coded stream parameters
STREAM_WIDTH = 1920
STREAM_HEIGHT = 1080
TARGET_FPS = 30.0
JPEG_QUALITY = 80

# Derived sleep to aim for target FPS. This delays between frames; it cannot
# make the camera or encoding faster than their capabilities, but it will
# throttle the loop to avoid spinning faster than 30fps.
FRAME_SLEEP = 1.0 / TARGET_FPS

# Configure Picamera2 for 1080p RGB
picam2 = Picamera2()
video_config = picam2.create_video_configuration(main={"size": (STREAM_WIDTH, STREAM_HEIGHT), "format": "RGB888"})
picam2.configure(video_config)
picam2.start()

frame_lock = threading.Lock()


def generate_mjpeg():
    """Yield multipart MJPEG frames forever.

    This generator captures from Picamera2, converts to RGB if needed,
    encodes JPEG with Pillow, and yields the multipart frame. It sleeps
    FRAME_SLEEP between frames to aim for TARGET_FPS.
    """
    while True:
        with frame_lock:
            frame = picam2.capture_array("main")

        # Prefer OpenCV's C-based JPEG encoder when available (faster). Picamera2
        # often returns BGR-ordered arrays; cv2.imencode expects BGR, so pass
        # the raw frame directly. If OpenCV isn't available or encoding fails,
        # fall back to Pillow (convert BGR->RGB for correct colors).
        jpg = None
        if _cv2_available and hasattr(frame, "ndim") and frame.ndim == 3 and frame.shape[2] == 3:
            try:
                # cv2.imencode returns (retval, buffer)
                ret, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                if ret:
                    jpg = buf.tobytes()
            except Exception:
                jpg = None

        if jpg is None:
            # Pillow path: convert to RGB then encode
            if hasattr(frame, "ndim") and frame.ndim == 3 and frame.shape[2] == 3:
                rgb_frame = frame[..., ::-1]
            else:
                rgb_frame = frame
            img = Image.fromarray(rgb_frame)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=JPEG_QUALITY)
            jpg = buf.getvalue()

        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")

        # Throttle to target FPS
        time.sleep(FRAME_SLEEP)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/stream")
def stream():
    return Response(generate_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=5000, threaded=True)
    finally:
        try:
            picam2.stop()
        except Exception:
            pass


