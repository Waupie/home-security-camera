#!/usr/bin/env python3
"""
Simple MJPEG streaming server using Picamera2 and Flask.

View in your browser at:
    http://<raspberry-pi-ip>:5000/
"""
from flask import Flask, Response, render_template
from picamera2 import Picamera2
from PIL import Image
from io import BytesIO
import threading
import time

app = Flask(__name__)

# Configure Picamera2
picam2 = Picamera2()
video_config = picam2.create_video_configuration(main={"size": (1920, 1080), "format": "RGB888"})
picam2.configure(video_config)
picam2.start()

frame_lock = threading.Lock()

def generate_mjpeg():
    """
    Generator that yields MJPEG frames (multipart/x-mixed-replace).
    """
    while True:
        # Capture an RGB array from the camera
        with frame_lock:
            frame = picam2.capture_array("main")
        # Convert numpy array to JPEG bytes via PIL
        # libcamera/Picamera2 can return frames in BGR order even when format is RGB888.
        # That will make the image appear purplish (red/blue swapped). Ensure we pass
        # an RGB-ordered array to PIL by swapping channels when necessary.
        if hasattr(frame, 'ndim') and frame.ndim == 3 and frame.shape[2] == 3:
            # Swap BGR -> RGB
            rgb_frame = frame[..., ::-1]
        else:
            rgb_frame = frame

        img = Image.fromarray(rgb_frame)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=80)
        jpg = buf.getvalue()
        # Yield multipart frame
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpg + b'\r\n')
        # small sleep to avoid pegging CPU, adjust for desired FPS
        time.sleep(0.03)

@app.route("/")
def index():
    # Simple page that shows the stream
    return render_template("index.html")

@app.route("/stream")
def stream():
    return Response(generate_mjpeg(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    try:
        # listen on all interfaces so you can open from other machines
        app.run(host="0.0.0.0", port=5000, threaded=True)
    finally:
        try:
            picam2.stop()
        except Exception:
            pass
