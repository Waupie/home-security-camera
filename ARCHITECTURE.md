# Project Architecture

The application has been refactored into a modular structure for better organization and maintainability.

## File Structure

```
home-security-camera/
├── app.py              # Main application entry point (routes only)
├── config.py           # Configuration and environment variables
├── auth.py             # Authentication logic (login/logout/User class)
├── camera.py           # Camera operations (streaming, recording, encoding)
├── api.py              # External API interactions (video list)
├── requirements.txt    # Python dependencies
├── .env                # Environment configuration (not in git)
├── .env.example        # Example environment configuration
├── templates/          # HTML templates
│   ├── index.html      # Main camera view
│   └── login.html      # Login page
└── recordings/         # Recorded videos (created automatically)
```

## Module Overview

### `app.py` (Main Entry Point)
- **Purpose**: Application initialization and route definitions
- **Size**: ~90 lines (down from 407 lines!)
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
python3 app.py
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

## Benefits of Modular Structure

1. **Maintainability**: Each module has a single, clear responsibility
2. **Readability**: ~70-200 lines per file vs. 400+ line monolith
3. **Testability**: Easier to unit test individual modules
4. **Reusability**: Modules can be used independently
5. **Collaboration**: Multiple developers can work on different modules
6. **Debugging**: Easier to locate and fix issues

## Backwards Compatibility

The refactored code maintains 100% API compatibility:
- All routes remain the same
- All functionality is preserved
- `.env` configuration is unchanged
- Templates are unmodified

If you need the original monolithic version, it's saved as `app.py.backup`.
