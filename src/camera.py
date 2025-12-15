"""
Camera module for the home security camera application.
Handles MJPEG streaming, snapshot, recording and a lightweight motion detector.

Single, clean implementation: motion detection runs in `generate_mjpeg()` and
the developer helper `_toggle_movement_test()` toggles or sets the movement
flag as requested by the `/movement-test` route.
"""
from flask import Response, jsonify, send_from_directory
from flask_login import login_required, current_user
from io import BytesIO
from datetime import datetime
import threading
import time
import os
import logging
import requests

from config import (
    STREAM_WIDTH, STREAM_HEIGHT, TARGET_FPS, JPEG_QUALITY, FRAME_SLEEP,
    RECORD_SECONDS, RECORDINGS_DIR, VIDEO_API_URL, VIDEO_API_KEY
)

# Optional libs
try:
    from picamera2 import Picamera2
    _picamera2_available = True
except Exception:
    Picamera2 = None
    _picamera2_available = False

try:
    import cv2
    _cv2_available = True
except Exception:
    cv2 = None
    _cv2_available = False

try:
    import numpy as np
    _np_available = True
except Exception:
    np = None
    _np_available = False

from PIL import Image

logger = logging.getLogger(__name__)

# Globals
picam2 = None
frame_lock = threading.Lock()

# Movement detection state
movement_lock = threading.Lock()
MOVEMENT_HOLD_SECONDS = 10.0
MOTION_CONSECUTIVE = 8
PIXEL_DIFF_THRESH = 40
MOTION_AREA_RATIO = 0.05

_motion_prev = None
_motion_count = 0
last_movement_dt = None
last_movement = None

# Recording
recording_lock = threading.Lock()
is_recording = False
last_recording = None


def init_camera(app):
    """Initialize Picamera2 if available."""
    global picam2
    if _picamera2_available:
        try:
            picam2 = Picamera2()
            video_config = picam2.create_video_configuration(
                main={"size": (STREAM_WIDTH, STREAM_HEIGHT), "format": "RGB888"},
                controls={"FrameRate": TARGET_FPS}
            )
            picam2.configure(video_config)
            picam2.start()
            app.logger.info('Picamera2 initialized')
        except Exception:
            app.logger.exception('Failed to init Picamera2; running in dev mode')
            picam2 = None
    else:
        try:
            app.logger.warning('Picamera2 not available; dev-mode frames will be used')
        except Exception:
            pass


def stop_camera():
    global picam2
    if picam2 is not None:
        try:
            picam2.stop()
        except Exception:
            pass


def encode_jpeg(frame):
    """Encode a numpy frame to JPEG bytes; prefer OpenCV when available."""
    try:
        if _cv2_available and hasattr(frame, 'ndim') and frame.ndim == 3 and frame.shape[2] == 3:
            ret, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            if ret:
                return buf.tobytes()
    except Exception:
        pass

    # Pillow fallback
    try:
        if hasattr(frame, 'ndim') and frame.ndim == 3 and frame.shape[2] == 3:
            # OpenCV uses BGR ordering; convert to RGB for Pillow
            arr = frame[..., ::-1]
        else:
            arr = frame
        img = Image.fromarray(arr)
        buf = BytesIO()
        img.save(buf, format='JPEG', quality=JPEG_QUALITY)
        return buf.getvalue()
    except Exception:
        # Last-resort: empty jpeg
        return b''


def _generate_placeholder_jpeg():
    if _np_available:
        placeholder = np.zeros((STREAM_HEIGHT, STREAM_WIDTH, 3), dtype=np.uint8)
        for i in range(STREAM_HEIGHT):
            placeholder[i, :] = [i % 256, 100, 150]
        return encode_jpeg(placeholder)
    else:
        # Very small black JPEG
        return encode_jpeg(Image.new('RGB', (STREAM_WIDTH, STREAM_HEIGHT), (0, 0, 0)))


def generate_mjpeg():
    """Yield multipart MJPEG frames and run motion detection per frame."""
    global _motion_prev, _motion_count, last_movement_dt, last_movement

    placeholder_jpg = _generate_placeholder_jpeg()

    while True:
        if not _picamera2_available or picam2 is None:
            # Dev-mode: yield the same placeholder frame
            jpg = placeholder_jpg
        else:
            with frame_lock:
                try:
                    frame = picam2.capture_array('main')
                except Exception:
                    frame = None

            if frame is None:
                jpg = placeholder_jpg
            else:
                # Motion detection
                detected = False
                ratio = 0.0
                changed = 0
                total = 0
                try:
                    if _cv2_available:
                        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                        small = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
                        small_blur = cv2.GaussianBlur(small, (7, 7), 0)

                        if _motion_prev is None:
                            _motion_prev = small_blur.copy()
                            detected = False
                        else:
                            diff = cv2.absdiff(small_blur, _motion_prev)
                            _, thresh = cv2.threshold(diff, PIXEL_DIFF_THRESH, 255, cv2.THRESH_BINARY)
                            changed = int(cv2.countNonZero(thresh))
                            total = thresh.size
                            ratio = float(changed) / float(total) if total else 0.0
                            detected = ratio > MOTION_AREA_RATIO
                            _motion_prev = cv2.addWeighted(_motion_prev, 0.6, small_blur, 0.4, 0)
                    elif _np_available:
                        # Simple numpy fallback
                        gray = (frame[..., 0].astype('int') * 0.2989 + frame[..., 1].astype('int') * 0.5870 + frame[..., 2].astype('int') * 0.1140).astype('uint8')
                        small = gray[::2, ::2]
                        if _motion_prev is None:
                            _motion_prev = small.copy()
                            detected = False
                        else:
                            diff = np.abs(small.astype('int') - _motion_prev.astype('int'))
                            changed = int((diff > PIXEL_DIFF_THRESH).sum())
                            total = diff.size
                            ratio = float(changed) / float(total) if total else 0.0
                            detected = ratio > MOTION_AREA_RATIO
                            _motion_prev = ((_motion_prev.astype('float') * 0.6) + (small.astype('float') * 0.4)).astype(_motion_prev.dtype)

                    # debounce and hold-window logic
                    if detected:
                        _motion_count = min(_motion_count + 1, MOTION_CONSECUTIVE)
                    else:
                        _motion_count = max(_motion_count - 1, 0)

                    now = datetime.utcnow()
                    in_window = False
                    if last_movement_dt is not None:
                        try:
                            in_window = (now - last_movement_dt).total_seconds() <= MOVEMENT_HOLD_SECONDS
                        except Exception:
                            in_window = False

                    if _motion_count >= MOTION_CONSECUTIVE and not in_window:
                        with movement_lock:
                            last_movement_dt = now
                            last_movement = last_movement_dt.isoformat() + 'Z'
                            try:
                                logger.info('Motion detected: ratio=%.4f changed=%d total=%d', ratio, changed, total)
                            except Exception:
                                pass
                except Exception:
                    # Do not allow motion detection to stop the stream
                    pass

                jpg = encode_jpeg(frame)

        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")

        time.sleep(FRAME_SLEEP)


@login_required
def stream_route():
    """Return an MJPEG Response for the stream."""
    return Response(generate_mjpeg(), mimetype='multipart/x-mixed-replace; boundary=frame')


@login_required
def snapshot_route(app=None):
    """Return a single JPEG snapshot."""
    if not _picamera2_available or picam2 is None:
        if _np_available:
            frame = np.zeros((STREAM_HEIGHT, STREAM_WIDTH, 3), dtype=np.uint8)
            frame[100:150, 100:150] = [0, 255, 0]
        else:
            img = Image.new('RGB', (STREAM_WIDTH, STREAM_HEIGHT), color=(0, 0, 0))
            return Response(encode_jpeg(img), mimetype='image/jpeg')
    else:
        with frame_lock:
            try:
                frame = picam2.capture_array('main')
            except Exception:
                frame = None

    if frame is None:
        return Response(_generate_placeholder_jpeg(), mimetype='image/jpeg')

    jpg = encode_jpeg(frame)
    try:
        if app is not None:
            app.logger.info('Snapshot produced')
    except Exception:
        pass
    return Response(jpg, mimetype='image/jpeg')


def _recorder_thread(duration_seconds, out_path, user_email=None, app_logger=None):
    """Background recorder using Picamera2 encoders where available.

    If Picamera2 isn't available the thread logs and returns.
    After writing the file, attempt upload to `VIDEO_API_URL` if configured.
    """
    global is_recording, last_recording
    start_time = time.time()
    try:
        if not _picamera2_available or picam2 is None:
            raise RuntimeError('Picamera2 not available; recording disabled')

        from picamera2.encoders import H264Encoder
        from picamera2.outputs import FfmpegOutput

        encoder = H264Encoder(bitrate=10000000)
        output = FfmpegOutput(out_path)

        if app_logger:
            app_logger.info('Recording started: %s', out_path)

        picam2.start_encoder(encoder, output)
        time.sleep(duration_seconds)
        picam2.stop_encoder()

        elapsed = time.time() - start_time
        if app_logger:
            app_logger.info('Recording finished: %s (%.2fs)', out_path, elapsed)

        # Attempt upload
        if VIDEO_API_KEY and VIDEO_API_URL:
            try:
                with open(out_path, 'rb') as f:
                    files = {'video': f}
                    data = {'apiKey': VIDEO_API_KEY}
                    resp = requests.post(VIDEO_API_URL, files=files, data=data, timeout=30)
                if app_logger:
                    if resp.status_code in (200, 201):
                        app_logger.info('Video uploaded: %s', resp.json())
                    else:
                        app_logger.error('Upload failed [%d]: %s', resp.status_code, resp.text)
            except Exception as e:
                if app_logger:
                    app_logger.exception('Upload error: %s', e)

    except Exception as e:
        if app_logger:
            app_logger.exception('Recording failed: %s', e)
    finally:
        with recording_lock:
            is_recording = False
        # Mark last_recording filename for the UI
        try:
            last_recording = os.path.basename(out_path)
        except Exception:
            last_recording = None


@login_required
def record_route(app=None):
    """Start a background recording and return status JSON."""
    global is_recording
    with recording_lock:
        if is_recording:
            return jsonify({'status': 'busy'}), 409
        is_recording = True

    ts = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    filename = f'recording-{ts}.mp4'
    out_path = os.path.join(RECORDINGS_DIR, filename)

    user_email = getattr(current_user, 'email', None)

    t = threading.Thread(target=_recorder_thread, args=(RECORD_SECONDS, out_path, user_email, app), daemon=True)
    t.start()
    return jsonify({'status': 'started', 'duration': RECORD_SECONDS})


@login_required
def last_recording_route():
    if last_recording:
        return jsonify({'filename': last_recording})
    return jsonify({'filename': None})


@login_required
def recordings_route(filename):
    return send_from_directory(RECORDINGS_DIR, filename, as_attachment=False, mimetype='video/mp4', download_name=filename)


def get_movement_state():
    """Return current movement state as {movement: bool, last_movement: iso}.

    Movement remains true for MOVEMENT_HOLD_SECONDS after last detection.
    """
    with movement_lock:
        now = datetime.utcnow()
        movement = False
        if last_movement_dt is not None:
            try:
                movement = (now - last_movement_dt).total_seconds() <= MOVEMENT_HOLD_SECONDS
            except Exception:
                movement = False
        return {'movement': bool(movement), 'last_movement': last_movement if movement else None}


def _toggle_movement_test(value=None):
    """Developer helper used by `/movement-test`.

    Behavior:
    - If `value` is None: toggle the movement flag (if currently in hold window, clear it; otherwise set it).
    - If `value` is True/False: explicitly set or clear movement.
    Returns the new movement dict.
    """
    global last_movement_dt, last_movement
    with movement_lock:
        now = datetime.utcnow()
        if value is None:
            # toggle
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
                last_movement_dt = now
                last_movement = last_movement_dt.isoformat() + 'Z'
            else:
                last_movement_dt = None
                last_movement = None

        return {'movement': bool(last_movement_dt is not None), 'last_movement': last_movement}


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
import logging
from config import (
    STREAM_WIDTH, STREAM_HEIGHT, TARGET_FPS, JPEG_QUALITY, FRAME_SLEEP,
    RECORD_SECONDS, RECORDINGS_DIR, VIDEO_API_URL, VIDEO_API_KEY
)

# Optional dependencies
try:
    from picamera2 import Picamera2
    _picamera2_available = True
except Exception:
    _picamera2_available = False

try:
    import cv2
    _cv2_available = True
except Exception:
    _cv2_available = False

logger = logging.getLogger(__name__)

# Globals
picam2 = None
frame_lock = threading.Lock()

# Movement detection state
movement_lock = threading.Lock()
# When motion is detected, keep the movement state true for this many seconds
MOVEMENT_HOLD_SECONDS = 10.0
# Detection tuning
MOTION_CONSECUTIVE = 8            # consecutive frames required (increased for stability)
PIXEL_DIFF_THRESH = 40           # per-pixel diff threshold (higher = less sensitive)
MOTION_AREA_RATIO = 0.05        # fraction of downsampled pixels that must change (5%)

# Internal state
_motion_prev = None
_motion_count = 0
last_movement_dt = None
last_movement = None

# Recording state
recording_lock = threading.Lock()
is_recording = False
last_recording = None


def init_camera(app):
    """Initialize the camera (only on Raspberry Pi)."""
    global picam2
    if _picamera2_available:
        picam2 = Picamera2()
        video_config = picam2.create_video_configuration(
            main={"size": (STREAM_WIDTH, STREAM_HEIGHT), "format": "RGB888"},
            controls={"FrameRate": TARGET_FPS}
        )
        picam2.configure(video_config)
        picam2.start()
        try:
            app.logger.info("Picamera2 initialized successfully")
        except Exception:
            pass
    else:
        try:
            app.logger.warning("Picamera2 not available. Running in dev mode with synthetic frames.")
        except Exception:
            pass


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
    encodes JPEG with Pillow/OpenCV, and yields the multipart frame. It
    sleeps FRAME_SLEEP between frames to aim for TARGET_FPS.
    """
    # Dev placeholder when camera hardware isn't present
    if not _picamera2_available or picam2 is None:
        try:
            import numpy as np
            placeholder = np.zeros((STREAM_HEIGHT, STREAM_WIDTH, 3), dtype=np.uint8)
            for i in range(STREAM_HEIGHT):
                placeholder[i, :] = [i % 256, 100, 150]
            jpg = encode_jpeg(placeholder)
            while True:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")
                time.sleep(FRAME_SLEEP)


            @login_required
            def stream_route():
                """Stream MJPEG video (route wrapper)."""
                return Response(generate_mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


            @login_required
            def snapshot_route(app):
                """Return a single JPEG snapshot and log the captured frame shape."""
                if not _picamera2_available or picam2 is None:
                    try:
                        import numpy as np
                        frame = np.zeros((STREAM_HEIGHT, STREAM_WIDTH, 3), dtype=np.uint8)
                        frame[100:150, 100:150] = [0, 255, 0]
                    except Exception:
                        # Fallback minimal image
                        frame = Image.new('RGB', (STREAM_WIDTH, STREAM_HEIGHT), color=(0, 0, 0))
                else:
                    with frame_lock:
                        frame = picam2.capture_array('main')

                try:
                    # app may not be available here; guard the logging
                    try:
                        app.logger.info('Snapshot frame shape: %s', getattr(frame, 'shape', 'unknown'))
                    except Exception:
                        logging.getLogger('camera').info('Snapshot frame shape: %s', getattr(frame, 'shape', 'unknown'))
                except Exception:
                    pass

                jpg = encode_jpeg(frame)
                return Response(jpg, mimetype='image/jpeg')
        except Exception:
            # If numpy not available, just spin (unlikely)
            while True:
                time.sleep(FRAME_SLEEP)

    # Main streaming loop
    while True:
        with frame_lock:
            frame = picam2.capture_array("main")

        # Motion detection: produce a debounced 'detected' when a sufficient
        # fraction of downsampled pixels changes beyond a pixel threshold.
        detected = False
        ratio = 0.0
        changed = 0
        total = 0
        try:
            if _cv2_available:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                # Reduce downsampling so we include more pixels in the analysis
                small = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
                # Slightly stronger blur to remove sensor speckle
                small_blur = cv2.GaussianBlur(small, (7, 7), 0)

                if _motion_prev is None:
                    _motion_prev = small_blur.copy()
                    detected = False
                else:
                    diff = cv2.absdiff(small_blur, _motion_prev)
                    _, thresh = cv2.threshold(diff, PIXEL_DIFF_THRESH, 255, cv2.THRESH_BINARY)
                    changed = int(cv2.countNonZero(thresh))
                    total = thresh.size
                    ratio = float(changed) / float(total) if total else 0.0
                    detected = ratio > MOTION_AREA_RATIO
                    _motion_prev = cv2.addWeighted(_motion_prev, 0.6, small_blur, 0.4, 0)
            else:
                import numpy as np
                gray = (frame[..., 0].astype('int') * 0.2989 + frame[..., 1].astype('int') * 0.5870 + frame[..., 2].astype('int') * 0.1140).astype('uint8')
                # Downsample less aggressively (use every 2nd pixel instead of every 4th)
                small = gray[::2, ::2]
                if _motion_prev is None:
                    _motion_prev = small.copy()
                    detected = False
                else:
                    diff = np.abs(small.astype('int') - _motion_prev.astype('int'))
                    changed = int((diff > PIXEL_DIFF_THRESH).sum())
                    total = diff.size
                    ratio = float(changed) / float(total) if total else 0.0
                    detected = ratio > MOTION_AREA_RATIO
                    _motion_prev = ((_motion_prev.astype('float') * 0.6) + (small.astype('float') * 0.4)).astype(_motion_prev.dtype)

            # debounce
            global _motion_count, last_movement_dt, last_movement
            if detected:
                _motion_count = min(_motion_count + 1, MOTION_CONSECUTIVE)
            else:
                _motion_count = max(_motion_count - 1, 0)

            # Trigger movement only when consecutive count reached and not currently in hold window
            now = datetime.utcnow()
            in_window = False
            if last_movement_dt is not None:
                try:
                    in_window = (now - last_movement_dt).total_seconds() <= MOVEMENT_HOLD_SECONDS
                except Exception:
                    in_window = False

            if _motion_count >= MOTION_CONSECUTIVE and not in_window:
                with movement_lock:
                    last_movement_dt = now
                    last_movement = last_movement_dt.isoformat() + 'Z'
                    try:
                        logger.info('Motion detected: ratio=%.4f changed=%d total=%d', ratio, changed, total)
                    except Exception:
                        pass
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

        # Upload to API
        if VIDEO_API_KEY and VIDEO_API_URL:
            try:
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
        with movement_lock:
            now = datetime.utcnow()
            if value is None:
                # Explicitly set movement true for the hold window when no param provided
                last_movement_dt = now
                last_movement = last_movement_dt.isoformat() + 'Z'
            else:
                if bool(value):
                    last_movement_dt = now
                    last_movement = last_movement_dt.isoformat() + 'Z'
                else:
                    last_movement_dt = None
                    last_movement = None

            return {'movement': bool(last_movement_dt is not None), 'last_movement': last_movement}

    try:
        # app may not be available here; guard the logging
        logging.getLogger('camera').info('Snapshot frame shape: %s', getattr(frame, 'shape', 'unknown'))
    except Exception:
        pass

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

    user_email = current_user.email if hasattr(current_user, 'email') else None

    t = threading.Thread(
        target=_recorder_thread,
        args=(RECORD_SECONDS, out_path, user_email, None),
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
