#!/usr/bin/env python3
"""
Home Security Camera - Main Application

Minimal MJPEG streaming server using Picamera2 and Flask.
Streams 1920x1080 at ~30 FPS with recording capabilities.

View in your browser at:
    http://<raspberry-pi-ip>:5000/
"""
from flask import Flask, render_template
from flask_login import login_required

# Import configuration and modules
import config
import auth
import camera
import api

# Create Flask app
app = Flask(__name__)
app.secret_key = config.SECRET_KEY

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

@app.route('/api/videos')
def videos():
    """Fetch video list from API."""
    return api.videos_route(app)

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

