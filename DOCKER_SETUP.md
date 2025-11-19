# Docker Setup Guide

This guide explains how to run both the Python Flask backend and Node.js frontend using Docker and Docker Compose.

## Architecture

```
┌─────────────────────────────────────────┐
│          Your Browser                   │
│     http://localhost:3000               │
└────────────────┬────────────────────────┘
                 │
         ┌───────▼────────┐
         │ Node.js (port  │
         │ 3000)          │
         │ Frontend Proxy │
         └───────┬────────┘
                 │ (http://python-backend:5000)
         ┌───────▼────────────────┐
         │ Python Flask (port 5000)│
         │ Picamera2 Stream       │
         │ Recording              │
         └────────────────────────┘
```

Both services run in the same Docker network and communicate internally.

## Prerequisites

- Docker and Docker Compose installed
- (For Raspberry Pi) Docker Desktop or Docker installed on Pi OS

## Quick Start

### 1. Configuration

Copy the example environment file:
```bash
cp .env.example .env
```

Edit `.env` to customize (optional):
```bash
SECRET_KEY=your-production-secret-key
AUTH_API_URL=https://api.qkeliq.eu/api/auth/login
```

### 2. Build and Run (Mac/Linux development)

```bash
docker-compose up --build
```

This will:
- Build the Python backend (with `SKIP_PI_PACKAGES=1` for non-Pi systems)
- Build the Node.js frontend
- Start both services
- Python backend runs on port 5000 (internal), exposed on localhost:5000
- Node.js frontend runs on port 3000, exposed on localhost:3000

Open your browser to: **http://localhost:3000**

### 3. Build and Run (Raspberry Pi)

On the Raspberry Pi, use the Pi-specific compose override:

```bash
docker-compose -f docker-compose.yml -f docker-compose.pi.yml up --build
```

This will:
- Build the Python backend WITH Raspberry Pi packages (`SKIP_PI_PACKAGES=0`)
- Mount `/dev/video0` (camera device) and `/dev/vchiq` (GPU access)
- Start both services with proper permissions

Open your browser to: **http://<raspberry-pi-ip>:3000**

## Running in Background

```bash
# Detached mode (runs in background)
docker-compose up -d --build

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

## Directory Structure

```
.
├── app.py                    # Python Flask app
├── requirements.txt          # Python dependencies
├── templates/                # Flask templates
│   ├── index.html           # Main UI (deprecated, Node serves its own)
│   └── login.html           # Login page
├── node-app/                # Node.js app
│   ├── app.js              # Express server
│   ├── package.json        # Node dependencies
│   └── public/
│       └── index.html      # Node UI
├── recordings/              # Shared volume for recorded videos
├── Dockerfile.python        # Python Flask Dockerfile
├── Dockerfile.node          # Node.js Dockerfile
├── docker-compose.yml       # Main compose file (dev + Pi)
├── docker-compose.pi.yml    # Pi-specific overrides
└── .env                     # Configuration (create from .env.example)
```

## Ports

| Service | Port | URL |
|---------|------|-----|
| Node.js Frontend | 3000 | http://localhost:3000 |
| Python Backend | 5000 | http://localhost:5000 (internal to Node) |

## Volumes

| Path | Purpose |
|------|---------|
| `./recordings` | Shared between containers; stores MP4 recordings |

## Environment Variables

### Python Backend (.env)
```
SECRET_KEY=your-secret-key
AUTH_API_URL=https://api.qkeliq.eu/api/auth/login
```

### Node.js Frontend (set in docker-compose.yml)
```
PYTHON_BACKEND=http://python-backend:5000  # Internal Docker network
PORT=3000
```

## Troubleshooting

### Backend not starting
```bash
docker-compose logs python-backend
```

Check for:
- Camera device not found on Pi (use `ls /dev/video*` to verify)
- Missing Python dependencies

### Node frontend can't reach backend
```bash
docker-compose logs node-frontend
```

Ensure:
- `PYTHON_BACKEND=http://python-backend:5000` is set in docker-compose.yml
- Both services are on the same network (`camera-network`)

### Stream not loading
1. Verify Python backend is healthy: `curl http://localhost:5000/stream`
2. Check browser console for CORS/proxy errors
3. On Pi, verify camera is accessible: `libcamera-hello --list-cameras`

### Raspberry Pi camera not detected
Ensure:
- Camera ribbon cable is properly connected
- Pi camera is enabled in raspi-config
- Docker has access to camera device (`/dev/video0`)

Use Pi-specific compose with:
```bash
docker-compose -f docker-compose.yml -f docker-compose.pi.yml up --build
```

### Rebuild without cache
```bash
docker-compose build --no-cache
docker-compose up
```

## Production Deployment

For production on Raspberry Pi:

1. **Use specific image versions** in Dockerfiles instead of `latest`
2. **Set proper `SECRET_KEY`** in `.env` (generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`)
3. **Enable health checks** — both Dockerfiles include health checks
4. **Use restart policies** — `restart: unless-stopped` is set
5. **Monitor logs** — use `docker-compose logs -f` or a log aggregator
6. **Backup recordings** — the `./recordings` volume should be backed up regularly

## Useful Commands

```bash
# View running containers
docker-compose ps

# View logs
docker-compose logs -f node-frontend
docker-compose logs -f python-backend

# Execute command in container
docker-compose exec python-backend python app.py --help

# Stop all services
docker-compose down

# Remove all volumes (careful!)
docker-compose down -v

# Rebuild everything
docker-compose build --no-cache && docker-compose up
```

## Notes

- **Internal networking:** Both services communicate via Docker's internal network (`camera-network`). The Node.js frontend proxies requests to the Python backend using the service name `http://python-backend:5000`.
- **Shared volume:** Recordings are stored in `./recordings` which both containers can access.
- **No Docker on the Pi?** You can still run `app.py` and `node-app/app.js` directly with `python3 app.py` and `node node-app/app.js`.
