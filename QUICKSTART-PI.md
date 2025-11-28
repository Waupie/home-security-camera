# Quick Start Guide - Raspberry Pi Native (No Docker)

This guide runs the app directly on your Raspberry Pi without Docker for better performance.

## Prerequisites

- Raspberry Pi 4 or later
- Raspberry Pi OS (Bullseye or later)
- Camera module connected and enabled
- SSH access or direct terminal access

## One-Time Setup

```bash
cd ~/github/home-security-camera
chmod +x setup-pi.sh
./setup-pi.sh
```

This script will:
1. Update system packages
2. Install Python 3 and dependencies
3. Install camera libraries (picamera2, libcamera)
4. Install Node.js
5. Create a Python virtual environment
6. Install all Python/Node dependencies

## Running the App

### Terminal 1: Start Python Backend (Port 5000)

```bash
cd ~/github/home-security-camera
source venv/bin/activate
python3 app.py
```

You should see:
```
 * Running on http://0.0.0.0:5000
```

### Terminal 2: Start Node.js Frontend (Port 9000)

```bash
cd ~/github/home-security-camera/node-app
npm start
```

You should see:
```
🎥 Node.js frontend listening on http://0.0.0.0:3000
📡 Proxying stream from: http://localhost:5000
```

## Access the App

Open your browser to:
```
http://<your-pi-ip>:9000
```

Replace `<your-pi-ip>` with your Raspberry Pi's IP address (e.g., `http://192.168.1.50:9000`)

### Find Your Pi's IP

```bash
hostname -I
```

## Configuration

Edit the `.env` file to customize settings:

```bash
nano .env
```

Key settings:
- `SECRET_KEY` — Change this to something random for production
- `AUTH_API_URL` — Your external authentication API endpoint
- `PYTHON_BACKEND` — Usually `http://localhost:5000` (default)

## Stopping the App

Press `Ctrl+C` in each terminal to stop the services.

## Running as a Service (Optional)

To run on boot automatically, create systemd services:

### Python Backend Service

Create `/etc/systemd/system/camera-python.service`:

```ini
[Unit]
Description=Pi Camera Python Backend
After=network.target

[Service]
Type=simple
User=waup
WorkingDirectory=/home/waup/github/home-security-camera
Environment="PATH=/home/waup/github/home-security-camera/venv/bin"
ExecStart=/home/waup/github/home-security-camera/venv/bin/python3 app.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Node.js Frontend Service

Create `/etc/systemd/system/camera-node.service`:

```ini
[Unit]
Description=Pi Camera Node.js Frontend
After=network.target camera-python.service

[Service]
Type=simple
User=waup
WorkingDirectory=/home/waup/github/home-security-camera/node-app
ExecStart=/usr/bin/npm start
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable camera-python camera-node
sudo systemctl start camera-python camera-node
```

Check status:

```bash
sudo systemctl status camera-python camera-node
```

## Troubleshooting

### Camera not detected

```bash
libcamera-hello --list-cameras
```

### Port already in use

If port 5000 or 9000 is already in use:

1. Find process using the port:
   ```bash
   lsof -i :5000  # or :9000
   ```

2. Kill it:
   ```bash
   kill -9 <PID>
   ```

Or change port in `app.py` or Node.js `.env`:
```bash
PYTHON_BACKEND=http://localhost:5001
PORT=9001
```

### Authentication failing

Check that `AUTH_API_URL` in `.env` is correct:

```bash
curl -X POST https://api.qkeliq.eu/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"your-email@example.com","password":"your-password"}'
```

### No stream showing

1. Check Python backend logs
2. Verify camera is enabled: `raspi-config` → Interface Options → Camera
3. Check camera connection

## Performance Tips

- Run on a Pi 4 or newer (Pi 3 may struggle)
- Use a good power supply (3A+)
- Keep camera resolution at 1920x1080 or lower
- Monitor disk space for recordings

## Next Steps

- Set up the systemd services for auto-start on boot
- Configure a reverse proxy (nginx) for external access
- Set up backups for recordings
- Add SSL/TLS for secure remote access

