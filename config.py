"""
Configuration module for the home security camera application.
Loads environment variables and defines application constants.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Flask configuration
SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-in-production')

# External auth API configuration
AUTH_API_URL = os.environ.get('AUTH_API_URL', 'https://api.qkeliq.eu/api/auth/login')

# Video API configuration
VIDEO_API_URL = os.environ.get('VIDEO_API_URL', 'https://api.qkeliq.eu/api/videos')
VIDEO_API_KEY = os.environ.get('VIDEO_API_KEY', '')

# Hard-coded stream parameters
STREAM_WIDTH = 1920
STREAM_HEIGHT = 1080
TARGET_FPS = 30.0
JPEG_QUALITY = 80

# Derived sleep to aim for target FPS
FRAME_SLEEP = 1.0 / TARGET_FPS

# Recording configuration
RECORD_SECONDS = 10
RECORDINGS_DIR = os.path.join(os.getcwd(), 'recordings')

# Ensure recordings directory exists
os.makedirs(RECORDINGS_DIR, exist_ok=True)

def print_config():
    """Print configuration on startup for debugging."""
    print("=" * 60)
    print("Configuration:")
    print(f"  AUTH_API_URL: {AUTH_API_URL}")
    print(f"  VIDEO_API_URL: {VIDEO_API_URL}")
    print(f"  VIDEO_API_KEY: {'*' * len(VIDEO_API_KEY) if VIDEO_API_KEY else '(not set)'}")
    print("=" * 60)
