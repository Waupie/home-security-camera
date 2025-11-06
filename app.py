#!/usr/bin/env python3
"""
Simple MJPEG streaming server using Picamera2 and Flask.

View in your browser at:
    http://<raspberry-pi-ip>:5000/
"""
from flask import Flask, Response, render_template
from picamera2 import Picamera2
from PIL import Image
from io import BytesIO
import threading
import time
import os
import numpy as np

# Optional GPIO control for IR illuminator. If you wire an IR LED to a GPIO pin
# (with proper transistor/driver) set the environment variable IR_GPIO_PIN to
# the pin number (BCM). The code will try gpiozero first, then RPi.GPIO.
IR_GPIO_PIN = os.getenv("IR_GPIO_PIN")
_ir_ctrl = None
if IR_GPIO_PIN:
    try:
        from gpiozero import DigitalOutputDevice
        _ir_ctrl = DigitalOutputDevice(int(IR_GPIO_PIN))
    except Exception:
        try:
            import RPi.GPIO as GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(int(IR_GPIO_PIN), GPIO.OUT)
            GPIO.output(int(IR_GPIO_PIN), GPIO.LOW)
            class _RPICtrl:
                def __init__(self, pin):
                    self.pin = pin
                def on(self):
                    GPIO.output(self.pin, GPIO.HIGH)
                def off(self):
                    GPIO.output(self.pin, GPIO.LOW)
            _ir_ctrl = _RPICtrl(int(IR_GPIO_PIN))
        except Exception:
            _ir_ctrl = None

# Night-mode tuning environment variables
NIGHT_BRIGHTNESS_THRESHOLD = float(os.getenv("NIGHT_BRIGHTNESS_THRESHOLD", "40"))
# If set, these will be applied via picam2.set_controls() when night mode is entered.
NIGHT_EXPOSURE_US = os.getenv("NIGHT_EXPOSURE_US")
NIGHT_ANALOG_GAIN = os.getenv("NIGHT_ANALOG_GAIN")
NIGHT_FORCE_GRAYSCALE = os.getenv("NIGHT_FORCE_GRAYSCALE", "1") in ("1", "true", "True")

app = Flask(__name__)

# Configure Picamera2
picam2 = Picamera2()
# Make stream settings configurable via environment variables so you can tune
# performance without editing the script.
STREAM_WIDTH = int(os.getenv("STREAM_WIDTH", "1280"))
STREAM_HEIGHT = int(os.getenv("STREAM_HEIGHT", "720"))
# JPEG quality (1-95); lower => smaller images and less CPU/time to encode
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "70"))
# Small sleep between frames to avoid pegging a single-core CPU. Set to 0 to
# rely on the camera frame timing. Lower -> higher FPS but more CPU.
FRAME_SLEEP = float(os.getenv("FRAME_SLEEP", "0.01"))

video_config = picam2.create_video_configuration(main={"size": (STREAM_WIDTH, STREAM_HEIGHT), "format": "RGB888"})
picam2.configure(video_config)
picam2.start()

# Optionally enable AWB greyworld behaviour if requested via env var. Some
# libcamera tunings expose `awb_auto_is_greyworld` (lower-level) or accept
# different control names — try a few safe attempts and ignore failures.
AWB_AUTO_GREYWORLD = os.getenv("AWB_AUTO_GREYWORLD", "0") in ("1", "true", "True")
if AWB_AUTO_GREYWORLD:
    try:
        # try the common lowercase control name
        picam2.set_controls({"awb_auto_is_greyworld": 1})
    except Exception:
        try:
            # try an alternate camel-case name some setups may expose
            picam2.set_controls({"AwbAutoIsGreyWorld": 1})
        except Exception:
            try:
                # fallback: try setting an AwbMode to a guessed value
                picam2.set_controls({"AwbMode": "greyworld"})
            except Exception:
                # If none of these are supported, silently continue.
                pass

frame_lock = threading.Lock()
controls_lock = threading.Lock()

def generate_mjpeg():
    """
    Generator that yields MJPEG frames (multipart/x-mixed-replace).
    Implements simple day/night auto-switch based on frame brightness. When
    dark, optional IR GPIO is enabled and optional camera controls applied.
    """
    night_mode = False
    while True:
        # Capture an RGB array from the camera
        with frame_lock:
            frame = picam2.capture_array("main")

        # Estimate brightness to decide day/night
        try:
            if hasattr(frame, 'ndim') and frame.ndim == 3 and frame.shape[2] >= 3:
                rgb = frame[..., :3].astype(np.float32)
                lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
                mean_lum = float(lum.mean())
            else:
                mean_lum = float(frame.mean())
        except Exception:
            mean_lum = 255.0

        is_dark = mean_lum < NIGHT_BRIGHTNESS_THRESHOLD
        if is_dark and not night_mode:
            night_mode = True
            if _ir_ctrl:
                try:
                    _ir_ctrl.on()
                except Exception:
                    pass
            night_controls = {}
            if NIGHT_EXPOSURE_US:
                try:
                    night_controls['ExposureTime'] = int(NIGHT_EXPOSURE_US)
                except Exception:
                    pass
            if NIGHT_ANALOG_GAIN:
                try:
                    night_controls['AnalogueGain'] = float(NIGHT_ANALOG_GAIN)
                except Exception:
                    pass
            if night_controls:
                try:
                    with controls_lock:
                        picam2.set_controls(night_controls)
                except Exception:
                    pass
        elif not is_dark and night_mode:
            night_mode = False
            if _ir_ctrl:
                try:
                    _ir_ctrl.off()
                except Exception:
                    pass
            try:
                with controls_lock:
                    picam2.set_controls({})
            except Exception:
                pass

        # Convert numpy array to JPEG bytes via PIL
        # libcamera/Picamera2 can return frames in BGR order even when format is RGB888.
        if hasattr(frame, 'ndim') and frame.ndim == 3 and frame.shape[2] == 3:
            rgb_frame = frame[..., ::-1]
        else:
            rgb_frame = frame

        if night_mode and NIGHT_FORCE_GRAYSCALE:
            try:
                img = Image.fromarray(rgb_frame).convert('L').convert('RGB')
            except Exception:
                img = Image.fromarray(rgb_frame)
        else:
            img = Image.fromarray(rgb_frame)

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY)
        jpg = buf.getvalue()
        # Yield multipart frame
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpg + b'\r\n')

        # small sleep to avoid pegging CPU. Tune FRAME_SLEEP or set to 0 to rely on
        # camera frame timing. You can override via environment variable, e.g.: 
        # FRAME_SLEEP=0.0 python3 app.py
        if FRAME_SLEEP > 0:
            time.sleep(FRAME_SLEEP)

@app.route("/")
def index():
    # Simple page that shows the stream
    return render_template("index.html")

@app.route("/stream")
def stream():
    return Response(generate_mjpeg(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

if __name__ == "__main__":
    try:
        # listen on all interfaces so you can open from other machines
        app.run(host="0.0.0.0", port=5000, threaded=True)
    finally:
        try:
            picam2.stop()
        except Exception:
            pass
