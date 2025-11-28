"""
API module for the home security camera application.
Handles external API interactions (video list, etc.).
"""
from flask import jsonify
from flask_login import login_required
import requests
from config import VIDEO_API_URL

@login_required
def videos_route(app):
    """Fetch list of videos from the API (newest first)."""
    try:
        if not VIDEO_API_URL:
            return jsonify({'error': 'Video API not configured'}), 500
        
        response = requests.get(VIDEO_API_URL, timeout=10)
        
        if response.status_code == 200:
            videos = response.json()
            # Sort by created_at descending (newest first)
            if isinstance(videos, list):
                videos.sort(key=lambda v: v.get('created_at', ''), reverse=True)
            return jsonify(videos)
        else:
            app.logger.error('Failed to fetch videos: %d %s', response.status_code, response.text)
            return jsonify({'error': 'Failed to fetch videos'}), response.status_code
    except Exception as e:
        app.logger.error('Error fetching videos: %s', e)
        return jsonify({'error': str(e)}), 500
