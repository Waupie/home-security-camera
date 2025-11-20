#!/usr/bin/env python3
"""
Minimal MJPEG streaming server using Picamera2 and Flask.

Hard-coded to stream 1920x1080 at ~30 FPS. No environment toggles, no
day/night logic, no GPIO — exactly what you asked for: a simple, fixed
stream that you don't need to change.

View in your browser at:
    http://<raspberry-pi-ip>:5000/
"""
from flask import Flask, Response, render_template, jsonify, send_from_directory, request, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from PIL import Image
from io import BytesIO
import threading
import time
import os
from datetime import datetime
import zipfile
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Try to import Picamera2 (only available on Raspberry Pi)
try:
    from picamera2 import Picamera2
    _picamera2_available = True
except ImportError:
    _picamera2_available = False

try:
    import cv2
    _cv2_available = True
except Exception:
    _cv2_available = False

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-me-in-production')

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# External auth API configuration
AUTH_API_URL = os.environ.get('AUTH_API_URL', 'https://api.qkeliq.eu/api/auth/login')

# Simple user class for authentication
class User(UserMixin):
    def __init__(self, email, token=None):
        self.id = email
        self.email = email
        self.token = token

@login_manager.user_loader
def load_user(user_id):
    # user_id is the email
    return User(user_id)

# Hard-coded stream parameters
STREAM_WIDTH = 1920
STREAM_HEIGHT = 1080
TARGET_FPS = 30.0
JPEG_QUALITY = 80

# Derived sleep to aim for target FPS. This delays between frames; it cannot
# make the camera or encoding faster than their capabilities, but it will
# throttle the loop to avoid spinning faster than target FPS.
FRAME_SLEEP = 1.0 / TARGET_FPS

# Configure Picamera2 for 1080p RGB (only on Raspberry Pi)
picam2 = None
if _picamera2_available:
    picam2 = Picamera2()
    # Configure for higher frame rate
    video_config = picam2.create_video_configuration(
        main={"size": (STREAM_WIDTH, STREAM_HEIGHT), "format": "RGB888"},
        controls={"FrameRate": TARGET_FPS}
    )
    picam2.configure(video_config)
    picam2.start()
else:
    print("⚠️  WARNING: Picamera2 not available. Running in dev mode with synthetic frames.")

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
    if not _picamera2_available or picam2 is None:
        # Generate a placeholder image if picamera2 is not available
        import numpy as np
        placeholder = np.zeros((STREAM_HEIGHT, STREAM_WIDTH, 3), dtype=np.uint8)
        # Add a simple gradient
        for i in range(STREAM_HEIGHT):
            placeholder[i, :] = [i % 256, 100, 150]
        jpg = encode_jpeg(placeholder)
        while True:
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")
            time.sleep(FRAME_SLEEP)
    
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


@app.route("/login", methods=['GET', 'POST'])
def login():
    """Login page and handler. Authenticates against external API."""
    if request.method == 'POST':
        email = request.form.get('email', '')
        password = request.form.get('password', '')
        
        if not email or not password:
            return render_template('login.html', error='Email and password required')
        
        try:
            # Call external auth API
            resp = requests.post(
                AUTH_API_URL,
                json={'email': email, 'password': password},
                timeout=5
            )
            
            if resp.status_code == 200:
                # Authentication successful
                data = resp.json()
                app.logger.info('Auth API response: %s', data)
                
                # Try multiple token field names
                token = data.get('token') or data.get('access_token') or data.get('data', {}).get('token')
                
                if token:
                    user = User(email, token=token)
                    login_user(user)
                    return redirect(url_for('index'))
                else:
                    # If no token, accept login anyway (useful for development)
                    app.logger.warning('No token in response, logging in without token')
                    user = User(email, token=None)
                    login_user(user)
                    return redirect(url_for('index'))
            else:
                app.logger.warning('Auth API returned %d: %s', resp.status_code, resp.text)
                return render_template('login.html', error='Invalid email or password')
        
        except requests.exceptions.RequestException as e:
            app.logger.error('Auth API error: %s', e)
            return render_template('login.html', error='Authentication service error. Try again later.')
    
    return render_template('login.html')


@app.route("/logout")
@login_required
def logout():
    """Logout and redirect to login page."""
    logout_user()
    return redirect(url_for('login'))


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/stream")
@login_required
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
@login_required
def snapshot():
    """Return a single JPEG snapshot and log the captured frame shape.

    Use this to inspect the actual pixels produced by the camera (helps
    determine whether Picamera2 is cropping/zooming the sensor output).
    """
    if not _picamera2_available or picam2 is None:
        import numpy as np
        frame = np.zeros((STREAM_HEIGHT, STREAM_WIDTH, 3), dtype=np.uint8)
        frame[100:150, 100:150] = [0, 255, 0]  # Green square as placeholder
    else:
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
    Picamera2 feed using hardware H.264 encoding to produce real-time MP4.
    """
    global is_recording, last_recording
    start_time = time.time()
    
    # Use Picamera2's hardware H.264 encoder for efficient, real-time recording.
    # This produces an MP4 file at true 30fps without the speedup issues.
    try:
        if not _picamera2_available or picam2 is None:
            raise RuntimeError('Picamera2 not available; recording disabled')
            
        from picamera2.encoders import H264Encoder
        from picamera2.outputs import FfmpegOutput
        
        # Create H.264 encoder with high bitrate for quality
        encoder = H264Encoder(bitrate=10000000)
        
        # Use FfmpegOutput to wrap the raw H.264 stream into MP4 container
        output = FfmpegOutput(out_path)
        
        app.logger.info('Recording started: file=%s duration=%ds', os.path.basename(out_path), duration_seconds)
        picam2.start_encoder(encoder, output)
        
        # Sleep for the recording duration
        time.sleep(duration_seconds)
        
        # Stop recording
        picam2.stop_encoder()
        elapsed = time.time() - start_time
        app.logger.info('Recording finished: file=%s elapsed=%.2fs', os.path.basename(out_path), elapsed)
    except Exception as e:
        app.logger.error('Recording failed: %s', e)
        import traceback
        traceback.print_exc()
    finally:
        with recording_lock:
            is_recording = False
            last_recording = os.path.basename(out_path)


@app.route('/record', methods=['POST'])
@login_required
def record():
    """Start a 10-second recording in the background. Returns JSON with status."""
    global is_recording, last_recording
    with recording_lock:
        if is_recording:
            return jsonify({'status': 'busy'}), 409
        is_recording = True

    ts = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    filename = f'recording-{ts}.mp4'
    out_path = os.path.join(RECORDINGS_DIR, filename)

    # Start background thread
    t = threading.Thread(target=_recorder_thread, args=(RECORD_SECONDS, out_path), daemon=True)
    t.start()

    return jsonify({'status': 'started', 'duration': RECORD_SECONDS})


@app.route('/last_recording')
@login_required
def get_last_recording():
    """Return the filename of the last completed recording (if any)."""
    if last_recording:
        return jsonify({'filename': last_recording})
    return jsonify({'filename': None})


@app.route('/recordings/<path:filename>')
@login_required
def recordings(filename):
    # Serve file with streaming and mimetype set for MP4 to avoid buffering issues
    return send_from_directory(
        RECORDINGS_DIR, 
        filename, 
        as_attachment=True,
        mimetype='video/mp4',
        download_name=filename
    )


if __name__ == "__main__":
    try:
        # threaded=True allows concurrent requests (stream + download at same time)
        app.run(host="0.0.0.0", port=5000, threaded=True)
    finally:
        try:
            if picam2 is not None:
                picam2.stop()
        except Exception:
            pass


