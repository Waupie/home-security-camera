"""
Authentication module for the home security camera application.
Handles user login/logout and Flask-Login integration.
"""
from flask import request, render_template, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
import requests
from config import AUTH_API_URL

# Flask-Login setup
login_manager = LoginManager()
login_manager.login_view = 'login'

class User(UserMixin):
    """Simple user class for authentication."""
    def __init__(self, email, token=None):
        self.id = email
        self.email = email
        self.token = token

@login_manager.user_loader
def load_user(user_id):
    """Load user by ID (email)."""
    return User(user_id)

def init_auth(app):
    """Initialize authentication with Flask app."""
    login_manager.init_app(app)

def login_route():
    """Login page and handler. Authenticates against external API."""
    if request.method == 'POST':
        email = request.form.get('email', '')
        password = request.form.get('password', '')
        
        if not email or not password:
            return render_template('login.html', error='Email and password required')
        
        try:
            # Call external auth API
            resp = requests.post(
                AUTH_API_URL,
                json={'email': email, 'password': password},
                timeout=5
            )
            
            if resp.status_code == 200:
                # Authentication successful
                data = resp.json()
                
                # Try multiple token field names
                token = data.get('token') or data.get('access_token') or data.get('data', {}).get('token')
                
                if token:
                    user = User(email, token=token)
                    login_user(user)
                    return redirect(url_for('index'))
                else:
                    # If no token, accept login anyway (useful for development)
                    user = User(email, token=None)
                    login_user(user)
                    return redirect(url_for('index'))
            else:
                return render_template('login.html', error='Invalid email or password')
        
        except requests.exceptions.RequestException as e:
            return render_template('login.html', error='Authentication service error. Try again later.')
    
    return render_template('login.html')

def logout_route():
    """Logout and redirect to login page."""
    logout_user()
    return redirect(url_for('login'))
