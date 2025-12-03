"""
API module for the home security camera application.
Handles external API interactions (video list, etc.).
"""
from flask import jsonify
from flask_login import login_required
import requests
from config import VIDEO_API_URL
from collections import defaultdict

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


@login_required
def videos_grouped_route(app):
    """Fetch list of videos and return them grouped by recording date (YYYY-MM-DD).

    Returns a list of groups sorted by date descending:
    [ { "date": "2025-12-03", "videos": [ ... ] }, ... ]
    """
    try:
        if not VIDEO_API_URL:
            return jsonify({'error': 'Video API not configured'}), 500

        response = requests.get(VIDEO_API_URL, timeout=10)

        if response.status_code == 200:
            videos = response.json()
            if not isinstance(videos, list):
                return jsonify({'error': 'Unexpected API response'}), 500

            # Group videos by date extracted from created_at (ISO date assumed)
            groups = defaultdict(list)
            for v in videos:
                created = v.get('created_at', '')
                # Expect ISO8601 like '2025-12-03T14:04:39Z' -> date is first 10 chars
                date_key = created[:10] if created else 'unknown'
                groups[date_key].append(v)

            # Build sorted groups (date desc)
            result = []
            for date_key, vids in groups.items():
                vids.sort(key=lambda vv: vv.get('created_at', ''), reverse=True)
                result.append({'date': date_key, 'videos': vids})

            # Sort groups by date descending, put 'unknown' at the end
            def group_sort_key(g):
                if g['date'] == 'unknown':
                    return ''
                return g['date']

            result.sort(key=group_sort_key, reverse=True)
            return jsonify(result)
        else:
            app.logger.error('Failed to fetch videos: %d %s', response.status_code, response.text)
            return jsonify({'error': 'Failed to fetch videos'}), response.status_code
    except Exception as e:
        app.logger.error('Error fetching videos (grouped): %s', e)
        return jsonify({'error': str(e)}), 500
