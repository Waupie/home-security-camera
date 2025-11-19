Docker usage for the home-security-camera app
============================================

This document explains how to build and run the minimal MJPEG streaming app in a Docker container on a Raspberry Pi.

Important notes before you start
- The camera stack (libcamera) requires access to hardware devices. The container therefore needs access to host devices and additional privileges.
- The Dockerfile installs system packages (libcamera, python3-picamera2) via apt — this works when your base image's package repositories contain those packages (Raspberry Pi OS). If you use a different OS, package names/availability may vary.

Build the image

From the project root:

```bash
docker build -t home-security-camera:latest .
```

Run the container (quick, single-container run)

```bash
docker run --rm -it \
  --privileged \
  --network host \
  --device /dev/vchiq \
  --device /dev/video0 \
  -v /dev:/dev \
  home-security-camera:latest
```

Recommended: docker-compose (provided)

If you prefer docker-compose, the included `docker-compose.yml` uses host networking and exposes devices. Run:

```bash
docker-compose up --build
```

Open the stream
- Index page: http://<raspberry-pi-ip>:5000/
- Direct MJPEG: http://<raspberry-pi-ip>:5000/stream

Troubleshooting
- If the container fails to import `picamera2` or libcamera fails, ensure you are using Raspberry Pi OS or a distro with libcamera/picamera2 packages available. On some systems you may need to install additional packages on the host or use a different base image.
- If you get permission errors accessing camera devices, ensure `--privileged` and the `/dev` mounts are present.
- For best performance (30 FPS at 1080p) you may need to use the Pi 4/400 family and ensure CPU is not overloaded. Hardware H.264 encoding is the most robust way to guarantee smooth 30fps.

Security note
- Running containers privileged and with /dev mounted is a powerful capability — only do this on trusted networks/hosts.
