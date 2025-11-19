# Node.js Frontend for Picamera2 MJPEG Stream

A lightweight Express.js proxy that displays your Raspberry Pi camera stream and provides a web UI for recording controls.

## What It Does

- **Proxies the MJPEG stream** from the Python backend (`/stream`)
- **Serves a modern web UI** for stream viewing and recording
- **Forwards recording requests** to the Python backend (`/record`)
- **Handles video downloads** from the Pi

## Setup

### 1. Install dependencies
```bash
cd node-app
npm install
```

### 2. Configure environment
Edit `.env` and set `PYTHON_BACKEND` to point to your Python app:

**On the Raspberry Pi:**
```bash
PYTHON_BACKEND=http://localhost:5000
```

**On a dev machine accessing remote Pi:**
```bash
PYTHON_BACKEND=http://192.168.x.x:5000
```

### 3. Run the app
```bash
npm start
```

Or for development with auto-reload:
```bash
npm run dev
```

The Node.js server will start on port 3000 (or `$PORT` env var).

## Usage

1. Open your browser to `http://localhost:3000` (or the Pi's IP)
2. You should see the live MJPEG stream from the camera
3. Click **Record 10s** to capture a 10-second video
4. After recording finishes, a download link appears

## Architecture

```
Client Browser
    ↓
Node.js (port 3000)
    ├─ Serves web UI
    ├─ Proxies /stream → Python /stream
    ├─ POST /record → Python /record
    ├─ GET /last_recording → Python /last_recording
    └─ GET /recordings/* → Python /recordings/*
    ↓
Python Flask App (port 5000)
    ├─ Authenticates users (login.html)
    ├─ Streams MJPEG from Picamera2
    └─ Handles recording with H.264 encoder
```

## Notes

- The Python backend handles **authentication** — all requests are proxied through as-is
- The Node app is **stateless** — it's purely a UI proxy
- Both the stream and downloads flow through Node, so you access everything from one URL
- For production on Pi: consider running both apps with systemd services or Docker Compose

## Environment Variables

| Var | Default | Notes |
|-----|---------|-------|
| `PORT` | `3000` | Port for Node.js server |
| `PYTHON_BACKEND` | `http://localhost:5000` | URL of Python app |

## Troubleshooting

**MJPEG not loading:**
- Check that Python backend is running on the configured `PYTHON_BACKEND` URL
- Try accessing Python backend directly: `curl http://<python-backend>/stream`

**Recording not working:**
- Ensure Python backend `/record` endpoint is responding
- Check Python app logs for errors

**Slow downloads:**
- Downloads are streamed through Node, which may be slower than direct access to Python
- For faster downloads, access `http://<python-ip>:5000/recordings/<filename>` directly (requires login)
