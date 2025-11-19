#!/usr/bin/env node
/**
 * Node.js proxy frontend for the Picamera2 MJPEG stream.
 * 
 * This app:
 * - Proxies the /stream from the Python backend
 * - Serves a web UI for stream viewing and recording controls
 * - Forwards /record requests to Python backend
 * - Downloads recordings from Python backend
 */

const express = require('express');
const { createProxyMiddleware } = require('http-proxy-middleware');
const path = require('path');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;
const PYTHON_BACKEND = process.env.PYTHON_BACKEND || 'http://localhost:5000';

// Middleware
app.use(express.json());
app.use(express.static('public'));

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', backend: PYTHON_BACKEND });
});

// Main page
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

/**
 * Proxy /stream from Python backend.
 * 
 * This streams the live MJPEG from the camera directly through Node.
 * The Python backend handles authentication, so we assume you're already logged in.
 */
app.use(
  '/stream',
  createProxyMiddleware({
    target: PYTHON_BACKEND,
    changeOrigin: true,
    pathRewrite: { '^/stream': '/stream' },
    ws: true,
    logLevel: 'info',
  })
);

/**
 * Proxy /record POST to Python backend.
 * Triggers a 10-second recording on the Pi.
 */
app.post('/record', async (req, res) => {
  try {
    const response = await fetch(`${PYTHON_BACKEND}/record`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    const data = await response.json();
    res.status(response.status).json(data);
  } catch (error) {
    console.error('Error calling /record:', error);
    res.status(500).json({ error: 'Failed to start recording' });
  }
});

/**
 * Proxy /last_recording from Python backend.
 * Gets the filename of the last completed recording.
 */
app.get('/last_recording', async (req, res) => {
  try {
    const response = await fetch(`${PYTHON_BACKEND}/last_recording`);
    const data = await response.json();
    res.json(data);
  } catch (error) {
    console.error('Error calling /last_recording:', error);
    res.status(500).json({ error: 'Failed to fetch last recording' });
  }
});

/**
 * Proxy /recordings/<filename> from Python backend.
 * Downloads a recorded video file.
 */
app.get('/recordings/:filename', async (req, res) => {
  try {
    const { filename } = req.params;
    const response = await fetch(`${PYTHON_BACKEND}/recordings/${encodeURIComponent(filename)}`);
    
    if (!response.ok) {
      return res.status(response.status).send('File not found');
    }

    res.setHeader('Content-Type', 'video/mp4');
    res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
    
    // Stream the response body to the client
    const buffer = await response.arrayBuffer();
    res.send(Buffer.from(buffer));
  } catch (error) {
    console.error('Error downloading recording:', error);
    res.status(500).send('Error downloading file');
  }
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`\n🎥 Node.js frontend listening on http://0.0.0.0:${PORT}`);
  console.log(`📡 Proxying stream from: ${PYTHON_BACKEND}\n`);
});
