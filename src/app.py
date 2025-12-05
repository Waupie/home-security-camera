#!/usr/bin/env python3
"""
Home Security Camera - Main Application

Minimal MJPEG streaming server using Picamera2 and Flask.
Streams 1920x1080 at ~30 FPS with recording capabilities.

View in your browser at:
    http://<raspberry-pi-ip>:5000/
"""
import os
from flask import Flask, render_template, jsonify, request, Response, stream_with_context
import json
import time
from flask_login import login_required

# Import configuration and modules
import config
import auth
import camera
import api

# Get the parent directory (project root) for templates
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Create Flask app with correct template folder
app = Flask(__name__, 
            template_folder=os.path.join(BASE_DIR, 'templates'),
            static_folder=os.path.join(BASE_DIR, 'static'))
app.secret_key = config.VIDEO_API_KEY

# Initialize authentication
auth.init_auth(app)

# Initialize camera
camera.init_camera(app)

# ============================================================================
# ROUTES
# ============================================================================

@app.route("/")
@login_required
def index():
    """Main page - camera stream view."""
    return render_template("index.html")

@app.route("/login", methods=['GET', 'POST'])
def login():
    """Login page and handler."""
    return auth.login_route()

@app.route("/logout")
def logout():
    """Logout and redirect to login."""
    return auth.logout_route()

@app.route("/stream")
def stream():
    """MJPEG video stream."""
    return camera.stream_route()

@app.route('/snapshot')
def snapshot():
    """Single JPEG snapshot."""
    return camera.snapshot_route(app)

@app.route('/record', methods=['POST'])
def record():
    """Start video recording."""
    return camera.record_route(app)

@app.route('/last_recording')
def last_recording():
    """Get last completed recording."""
    return camera.last_recording_route()

@app.route('/recordings/<path:filename>')
def recordings(filename):
    """Serve recorded video files."""
    return camera.recordings_route(filename)

@app.route('/videos')
def videos():
    """Fetch video list from API."""
    return api.videos_route(app)


@app.route('/videos/grouped')
def videos_grouped():
    """Fetch video list grouped by date from API."""
    return api.videos_grouped_route(app)


@app.route('/movement')
def movement():
    """Return current movement detection state from the camera module."""
    return jsonify(camera.get_movement_state())


@app.route('/movement-test')
def movement_test():
    """Dev-only: toggle or set movement state for testing.

    Query params: `set=true|false` to set explicitly.
    """
    set_val = request.args.get('set')
    if set_val is None:
        res = camera._toggle_movement_test()
    else:
        val = set_val.lower() in ('1', 'true', 'yes', 'on')
        res = camera._toggle_movement_test(val)
    return jsonify(res)


    def _movement_sse_generator(poll_interval=0.5):
        """Generator for server-sent events that emits movement state when it changes.

        This polls the in-process movement state and yields an SSE message only
        when the value changes to avoid constant client polling.
        """
        last_state = None
        while True:
            try:
                state = camera.get_movement_state()
                # Only send when state changes
                if state != last_state:
                    last_state = state
                    data = json.dumps(state)
                    yield f"data: {data}\n\n"
            except GeneratorExit:
                break
            except Exception:
                # Ignore transient errors and continue
                pass
            time.sleep(poll_interval)


    @app.route('/movement/stream')
    def movement_stream():
        """Server-sent events endpoint streaming movement state changes."""
        return Response(stream_with_context(_movement_sse_generator()), mimetype='text/event-stream')


# ---------------------------------------------------------------------------
# Error handlers + test route
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def handle_404(err):
    # err may be an HTTPException
    message = getattr(err, 'name', 'Not Found')
    detail = str(err)
    return render_template('error.html', code=404, message=message, detail=detail), 404


@app.errorhandler(500)
def handle_500(err):
    message = 'Server Error'
    detail = str(err)
    return render_template('error.html', code=500, message=message, detail=detail), 500


@app.route('/error-test')
def error_test():
    """Simple route to preview the error page during development."""
    raise RuntimeError('This is a test error for previewing the error page')

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    # Print configuration on startup
    config.print_config()
    
    try:
        # threaded=True allows concurrent requests (stream + download at same time)
        app.run(host="0.0.0.0", port=5000, threaded=True)
    finally:
        camera.stop_camera()

