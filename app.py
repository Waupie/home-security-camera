#!/usr/bin/env python3
"""
Minimal MJPEG streaming server using Picamera2 and Flask.

Hard-coded to stream 1920x1080 at ~30 FPS. No environment toggles, no
day/night logic, no GPIO — exactly what you asked for: a simple, fixed
stream that you don't need to change.

View in your browser at:
    http://<raspberry-pi-ip>:5000/
"""
from flask import Flask, Response, render_template, jsonify, send_from_directory, request
from picamera2 import Picamera2
from PIL import Image
from io import BytesIO
import threading
import time
import os
from datetime import datetime
import zipfile
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

# Recording state
recording_lock = threading.Lock()
is_recording = False
last_recording = None
RECORD_SECONDS = 10
RECORDINGS_DIR = os.path.join(os.getcwd(), 'recordings')
os.makedirs(RECORDINGS_DIR, exist_ok=True)


def generate_mjpeg():
    """Yield multipart MJPEG frames forever.

    This generator captures from Picamera2, converts to RGB if needed,
    encodes JPEG with Pillow, and yields the multipart frame. It sleeps
    FRAME_SLEEP between frames to aim for TARGET_FPS.
    """
    while True:
        with frame_lock:
            frame = picam2.capture_array("main")

        # Encode the captured frame to JPEG. Prefer OpenCV for speed, fall back
        # to Pillow for portability. The encoding logic is also used by the
        # /snapshot endpoint below so it's extracted to a small helper.
        jpg = encode_jpeg(frame)

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


def encode_jpeg(frame):
    """Encode a single camera frame (numpy array) to JPEG bytes.

    Prefer OpenCV's encoder when available; otherwise convert to RGB and
    encode with Pillow.
    """
    # Try OpenCV C encoder first (expects BGR ordering)
    if _cv2_available and hasattr(frame, "ndim") and getattr(frame, "ndim", 0) == 3 and frame.shape[2] == 3:
        try:
            ret, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            if ret:
                return buf.tobytes()
        except Exception:
            pass

    # Pillow path: convert BGR->RGB if needed and save to BytesIO
    if hasattr(frame, "ndim") and getattr(frame, "ndim", 0) == 3 and frame.shape[2] == 3:
        rgb_frame = frame[..., ::-1]
    else:
        rgb_frame = frame
    img = Image.fromarray(rgb_frame)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()


@app.route('/snapshot')
def snapshot():
    """Return a single JPEG snapshot and log the captured frame shape.

    Use this to inspect the actual pixels produced by the camera (helps
    determine whether Picamera2 is cropping/zooming the sensor output).
    """
    with frame_lock:
        frame = picam2.capture_array('main')

    # Log shape to help diagnose cropping/zoom (e.g. (height, width, channels))
    try:
        app.logger.info('Snapshot frame shape: %s', getattr(frame, 'shape', 'unknown'))
    except Exception:
        print('Snapshot captured, shape unknown')

    jpg = encode_jpeg(frame)
    return Response(jpg, mimetype='image/jpeg')


def _recorder_thread(duration_seconds, out_path):
    """Background thread that records `duration_seconds` seconds from the
    Picamera2 feed and writes to out_path. Uses OpenCV VideoWriter when
    available, otherwise saves sequential JPEGs and leaves them in a folder.
    """
    global is_recording, last_recording
    end_time = time.time() + duration_seconds

    if _cv2_available:
        # Warm up a few frames to estimate actual camera FPS so the resulting
        # MP4 uses a frame rate that matches the capture rate (avoids speedup).
        warm_frames = []
        warm_times = []
        warm_start = time.time()
        # collect up to 10 warm frames but for at least 0.5s to get a stable sample
        while (time.time() - warm_start) < 0.5 and len(warm_frames) < 10 and time.time() < end_time:
            with frame_lock:
                f = picam2.capture_array('main')
            try:
                warm_frames.append(f.copy())
            except Exception:
                warm_frames.append(f)
            warm_times.append(time.time())

        if len(warm_times) >= 2:
            elapsed = warm_times[-1] - warm_times[0]
            elapsed = max(elapsed, 0.5)
            fps_est = len(warm_frames) / elapsed
        else:
            fps_est = TARGET_FPS

        # Don't overestimate beyond TARGET_FPS (avoid producing too-short files)
        fps_est = max(1.0, min(fps_est, TARGET_FPS))

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        # OpenCV expects (width, height)
        writer = cv2.VideoWriter(out_path, fourcc, float(fps_est), (STREAM_WIDTH, STREAM_HEIGHT))
        # Write warm frames first
        for wf in warm_frames:
            try:
                writer.write(wf)
            except Exception:
                pass
    else:
        # create directory for JPEGs
        jpeg_dir = out_path + '_frames'
        os.makedirs(jpeg_dir, exist_ok=True)
        writer = None
        frame_idx = 0

    try:
        while time.time() < end_time:
            with frame_lock:
                f = picam2.capture_array('main')
            if _cv2_available and writer is not None:
                try:
                    writer.write(f)
                except Exception:
                    pass
            else:
                # save jpeg
                try:
                    img = Image.fromarray(f[..., ::-1])
                    fname = os.path.join(jpeg_dir, f'frame_{frame_idx:05d}.jpg')
                    img.save(fname, format='JPEG', quality=JPEG_QUALITY)
                    frame_idx += 1
                except Exception:
                    pass
            # sleep a small amount to avoid oversampling and to roughly align with
            # the target FPS (capture_array itself may block and dominate timing)
            time.sleep(max(0, FRAME_SLEEP * 0.9))
    finally:
        if writer is not None:
            try:
                writer.release()
            except Exception:
                pass
        else:
            # Package frames into a zip archive for easy download
            try:
                with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                    for root, _, files in os.walk(jpeg_dir):
                        for fname in sorted(files):
                            path = os.path.join(root, fname)
                            arcname = os.path.relpath(path, jpeg_dir)
                            zf.write(path, arcname=arcname)
                # Optionally remove the frames directory
                for root, _, files in os.walk(jpeg_dir, topdown=False):
                    for fname in files:
                        try:
                            os.remove(os.path.join(root, fname))
                        except Exception:
                            pass
                    try:
                        os.rmdir(root)
                    except Exception:
                        pass
            except Exception:
                pass
        with recording_lock:
            is_recording = False
            last_recording = os.path.basename(out_path)


@app.route('/record', methods=['POST'])
def record():
    """Start a 10-second recording in the background. Returns JSON with status."""
    global is_recording, last_recording
    with recording_lock:
        if is_recording:
            return jsonify({'status': 'busy'}), 409
        is_recording = True

    ts = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    filename = f'recording-{ts}.mp4' if _cv2_available else f'recording-{ts}.zip'
    out_path = os.path.join(RECORDINGS_DIR, filename)

    # Start background thread
    t = threading.Thread(target=_recorder_thread, args=(RECORD_SECONDS, out_path), daemon=True)
    t.start()

    return jsonify({'status': 'started', 'duration': RECORD_SECONDS})


@app.route('/last_recording')
def get_last_recording():
    """Return the filename of the last completed recording (if any)."""
    if last_recording:
        return jsonify({'filename': last_recording})
    return jsonify({'filename': None})


@app.route('/recordings/<path:filename>')
def recordings(filename):
    return send_from_directory(RECORDINGS_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=5000, threaded=True)
    finally:
        try:
            picam2.stop()
        except Exception:
            pass


