"""
Camera module for the home security camera application.
Handles video streaming, recording, and frame encoding.
"""
from flask import Response, jsonify, send_from_directory
from flask_login import login_required, current_user
from PIL import Image
from io import BytesIO
import threading
import time
import os
from datetime import datetime
import requests
from config import (
    STREAM_WIDTH, STREAM_HEIGHT, TARGET_FPS, JPEG_QUALITY, FRAME_SLEEP,
    RECORD_SECONDS, RECORDINGS_DIR, VIDEO_API_URL, VIDEO_API_KEY
)

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

# Global camera instance
picam2 = None
frame_lock = threading.Lock()

# Movement detection state
movement_lock = threading.Lock()
# When motion is detected, keep the movement state true for this many seconds
MOVEMENT_HOLD_SECONDS = 10.0

# Keep the timestamp (datetime) of the last detected movement and an ISO string
last_movement_dt = None
last_movement = None
_motion_prev = None

# Recording state
recording_lock = threading.Lock()
is_recording = False
last_recording = None

def init_camera(app):
    """Initialize the camera (only on Raspberry Pi)."""
    global picam2
    
    if _picamera2_available:
        picam2 = Picamera2()
        # Configure for higher frame rate
        video_config = picam2.create_video_configuration(
            main={"size": (STREAM_WIDTH, STREAM_HEIGHT), "format": "RGB888"},
            controls={"FrameRate": TARGET_FPS}
        )
        picam2.configure(video_config)
        picam2.start()
        app.logger.info("Picamera2 initialized successfully")
    else:
        app.logger.warning("Picamera2 not available. Running in dev mode with synthetic frames.")

def stop_camera():
    """Stop the camera if running."""
    global picam2
    if picam2 is not None:
        try:
            picam2.stop()
        except Exception:
            pass

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

        # --- Motion detection (cheap, low-res) ---
        try:
            import numpy as np
            global _motion_prev, movement_detected, last_movement

            # Convert to grayscale (try cv2 for speed/accuracy)
            if _cv2_available:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                small = cv2.resize(gray, (0,0), fx=0.25, fy=0.25)
            else:
                # Simple luma approximation and fast downsample by slicing
                gray = (frame[...,0].astype('int') * 0.2989 + frame[...,1].astype('int') * 0.5870 + frame[...,2].astype('int') * 0.1140).astype('uint8')
                small = gray[::4, ::4]

            if _motion_prev is None:
                _motion_prev = small
                detected = False
            else:
                # Compute difference and simple threshold
                diff = (small.astype('int') - _motion_prev.astype('int'))
                mean_diff = float(np.abs(diff).mean())
                # Movement threshold - tuned for downsampled image
                detected = mean_diff > 6.0
                _motion_prev = small

            if detected:
                with movement_lock:
                    # update timestamp of last movement; movement will be reported
                    # as true for MOVEMENT_HOLD_SECONDS after this timestamp
                    last_movement_dt = datetime.utcnow()
                    last_movement = last_movement_dt.isoformat() + 'Z'
        except Exception:
            # Don't let motion detection break the stream
            pass

        jpg = encode_jpeg(frame)

        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")

        # Throttle to target FPS
        time.sleep(FRAME_SLEEP)

def _recorder_thread(duration_seconds, out_path, user_email=None, app_logger=None):
    """Background thread that records video and uploads to API."""
    global is_recording, last_recording
    start_time = time.time()
    
    try:
        if not _picamera2_available or picam2 is None:
            raise RuntimeError('Picamera2 not available; recording disabled')
            
        from picamera2.encoders import H264Encoder
        from picamera2.outputs import FfmpegOutput
        
        # Create H.264 encoder with high bitrate for quality
        encoder = H264Encoder(bitrate=10000000)
        output = FfmpegOutput(out_path)
        
        if app_logger:
            app_logger.info('Recording started: file=%s duration=%ds', os.path.basename(out_path), duration_seconds)
        
        picam2.start_encoder(encoder, output)
        time.sleep(duration_seconds)
        picam2.stop_encoder()
        
        elapsed = time.time() - start_time
        if app_logger:
            app_logger.info('Recording finished: file=%s elapsed=%.2fs', os.path.basename(out_path), elapsed)
        
        # Upload to API (simplified to match curl)
        if VIDEO_API_KEY and VIDEO_API_URL:
            try:
                # Open file and upload - exactly like curl does
                with open(out_path, 'rb') as f:
                    files = {'video': f}
                    data = {'apiKey': VIDEO_API_KEY}
                    response = requests.post(VIDEO_API_URL, files=files, data=data, timeout=30)
                
                if response.status_code in (200, 201):
                    if app_logger:
                        app_logger.info('✓ Video uploaded: %s', response.json())
                else:
                    if app_logger:
                        app_logger.error('✗ Upload failed [%d]: %s', response.status_code, response.text)
            except Exception as e:
                if app_logger:
                    app_logger.error('✗ Upload error: %s', str(e))
            
    except Exception as e:
        if app_logger:
            app_logger.error('Recording failed: %s', e)
            import traceback
            traceback.print_exc()
    finally:
        with recording_lock:
            is_recording = False
            last_recording = os.path.basename(out_path)

@login_required
def stream_route():
    """Stream MJPEG video."""
    return Response(generate_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")

@login_required
def snapshot_route(app):
    """Return a single JPEG snapshot and log the captured frame shape."""
    if not _picamera2_available or picam2 is None:
        import numpy as np
        frame = np.zeros((STREAM_HEIGHT, STREAM_WIDTH, 3), dtype=np.uint8)
        frame[100:150, 100:150] = [0, 255, 0]  # Green square as placeholder
    else:
        with frame_lock:
            frame = picam2.capture_array('main')

    try:
        app.logger.info('Snapshot frame shape: %s', getattr(frame, 'shape', 'unknown'))
    except Exception:
        print('Snapshot captured, shape unknown')

    jpg = encode_jpeg(frame)
    return Response(jpg, mimetype='image/jpeg')

@login_required
def record_route(app):
    """Start a 10-second recording in the background."""
    global is_recording
    
    with recording_lock:
        if is_recording:
            return jsonify({'status': 'busy'}), 409
        is_recording = True

    ts = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    filename = f'recording-{ts}.mp4'
    out_path = os.path.join(RECORDINGS_DIR, filename)

    # Get user email before starting thread
    user_email = current_user.email if hasattr(current_user, 'email') else None

    # Start background thread
    t = threading.Thread(
        target=_recorder_thread, 
        args=(RECORD_SECONDS, out_path, user_email, app.logger), 
        daemon=True
    )
    t.start()

    return jsonify({'status': 'started', 'duration': RECORD_SECONDS})

@login_required
def last_recording_route():
    """Return the filename of the last completed recording."""
    if last_recording:
        return jsonify({'filename': last_recording})
    return jsonify({'filename': None})

@login_required
def recordings_route(filename):
    """Serve recorded video files."""
    return send_from_directory(
        RECORDINGS_DIR, 
        filename, 
        as_attachment=False,
        mimetype='video/mp4',
        download_name=filename
    )


def get_movement_state():
    """Return current movement detection state as a dict.

    Example: { 'movement': True, 'last_movement': '2025-12-05T12:34:56Z' }
    """
    with movement_lock:
        now = datetime.utcnow()
        movement = False
        if last_movement_dt is not None:
            try:
                delta = (now - last_movement_dt).total_seconds()
                movement = delta <= MOVEMENT_HOLD_SECONDS
            except Exception:
                movement = False

        return {
            'movement': bool(movement),
            'last_movement': last_movement if movement else None
        }


def _toggle_movement_test(value=None):
    """Developer helper to flip or set the movement flag (not route-protected).

    Passing `value` as True/False sets the flag; None toggles it.
    """
    global last_movement_dt, last_movement
    with movement_lock:
        if value is None:
            # toggle behavior: if currently within hold window, clear it; otherwise set now
            now = datetime.utcnow()
            in_window = False
            if last_movement_dt is not None:
                try:
                    in_window = (now - last_movement_dt).total_seconds() <= MOVEMENT_HOLD_SECONDS
                except Exception:
                    in_window = False
            if in_window:
                last_movement_dt = None
                last_movement = None
            else:
                last_movement_dt = now
                last_movement = last_movement_dt.isoformat() + 'Z'
        else:
            if bool(value):
                last_movement_dt = datetime.utcnow()
                last_movement = last_movement_dt.isoformat() + 'Z'
            else:
                last_movement_dt = None
                last_movement = None

        return {'movement': bool(last_movement_dt is not None), 'last_movement': last_movement}
