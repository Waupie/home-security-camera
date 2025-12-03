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
