# Home Security Camera

Home Security Camera is a lightweight, Raspberry Pi-friendly Flask application that provides live MJPEG streaming, hardware-accelerated H.264 recording, snapshot capture, and optional uploads to an external video API. It is designed for easy setup on a Raspberry Pi and straightforward integration with external authentication and video services.

# Project Architecture

The application has been refactored into a modular structure for better organization and maintainability.

## File Structure

```
home-security-camera/
├── src/                # Python source code
│   ├── app.py          # Main application entry point (routes only)
│   ├── config.py       # Configuration and environment variables
│   ├── auth.py         # Authentication logic (login/logout/User class)
│   ├── camera.py       # Camera operations (streaming, recording, encoding)
│   └── api.py          # External API interactions (video list)
├── templates/          # HTML templates
│   ├── index.html      # Main camera view
│   └── login.html      # Login page
├── recordings/         # Recorded videos (created automatically)
├── requirements.txt    # Python dependencies
├── .env                # Environment configuration (not in git)
├── .env.example        # Example environment configuration
├── setup-pi.sh         # Full Raspberry Pi setup script
└── quick-setup-venv.sh # Quick venv setup script
```

## Module Overview

### `app.py` (Main Entry Point)
- **Purpose**: Application initialization and route definitions
- **Responsibilities**:
  - Create Flask app
  - Initialize authentication and camera
  - Define URL routes
  - Start the server

### `config.py` (Configuration)
- **Purpose**: Centralized configuration management
- **Responsibilities**:
  - Load environment variables from `.env`
  - Define constants (stream settings, FPS, quality, etc.)
  - Provide configuration printing for debugging
- **Key Settings**:
  - `AUTH_API_URL` - External authentication API
  - `VIDEO_API_URL` - External video storage API
  - `VIDEO_API_KEY` - API authentication key
  - Camera parameters (resolution, FPS, quality)

### `auth.py` (Authentication)
- **Purpose**: User authentication and session management
- **Responsibilities**:
  - Flask-Login setup
  - User class definition
  - Login/logout route handlers
  - External API authentication

### `camera.py` (Camera Operations)
- **Purpose**: Camera streaming and recording
- **Responsibilities**:
  - Initialize Picamera2
  - MJPEG frame generation
  - JPEG encoding (OpenCV or Pillow)
  - H.264 hardware-accelerated recording
  - Video upload to external API
  - Snapshot capture
- **Key Functions**:
  - `init_camera()` - Setup Picamera2
  - `generate_mjpeg()` - Stream generator
  - `encode_jpeg()` - Frame encoding
  - `_recorder_thread()` - Background recording + upload
  - Route handlers for stream/snapshot/record

### `api.py` (External API)
- **Purpose**: Communication with external video API
- **Responsibilities**:
  - Fetch video list from API
  - Sort videos by creation date
  - Error handling for API failures

## Running the Application

### Standard Run
```bash
source venv/bin/activate
python3 src/app.py
```

### First-Time Setup (Raspberry Pi)
```bash
# Full system setup
./setup-pi.sh

# Or quick venv setup (if dependencies already installed)
./quick-setup-venv.sh
```

## Environment Configuration

Required variables in `.env`:
```properties
# Flask
SECRET_KEY=your-secret-key-here

# Authentication API
AUTH_API_URL=https://api.qkeliq.eu/api/auth/login

# Video API
VIDEO_API_URL=https://api.qkeliq.eu/api/videos
VIDEO_API_KEY=your-api-key-here
```