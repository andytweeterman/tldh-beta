import json
import time
import requests
import streamlit as st
import secrets
import logging
import os
from urllib.parse import urlencode

# Configure logging for this module
logger = logging.getLogger(__name__)

TOKEN_FILE = "whoop_tokens.json"

# Load credentials from Streamlit secrets
CLIENT_ID = st.secrets["WHOOP_CLIENT_ID"]
CLIENT_SECRET = st.secrets["WHOOP_CLIENT_SECRET"]
REDIRECT_URI = st.secrets["WHOOP_REDIRECT_URI"]

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"

def get_authorization_url(oauth_state=None):
    """Generates the Whoop login URL with a dynamic state for CSRF protection."""
    if not oauth_state:
        if "oauth_state" not in st.session_state:
            st.session_state.oauth_state = secrets.token_urlsafe(16)
        oauth_state = st.session_state.oauth_state
        
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "offline read:recovery read:cycles read:sleep read:workout",
        "state": oauth_state
    }
    return f"{AUTH_URL}?{urlencode(params)}"

def get_access_token(auth_code):
    """Exchanges auth code for tokens with a strict network timeout."""
    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
    }
    try:
        response = requests.post(TOKEN_URL, data=data, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Token exchange failed: {e}")
        return None

@st.cache_data(ttl=300)
def fetch_whoop_recovery(token):
    """Pulls V2 Cycle, Recovery, and Sleep metrics from all required endpoints."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        # BUGFIX: Querying all three distinct Whoop v2 endpoints
        cycle_res = requests.get("https://api.prod.whoop.com/developer/v2/cycle", headers=headers, timeout=10)
        sleep_res = requests.get("https://api.prod.whoop.com/developer/v2/activity/sleep", headers=headers, timeout=10)
        rec_res = requests.get("https://api.prod.whoop.com/developer/v2/recovery", headers=headers, timeout=10)

        if cycle_res.status_code == 200:
            cycle_recs = cycle_res.json().get('records', [])
            sleep_recs = sleep_res.json().get('records', []) if sleep_res.status_code == 200 else []
            rec_recs = rec_res.json().get('records', []) if rec_res.status_code == 200 else []

            latest_cycle = cycle_recs[0] if cycle_recs else {}
            latest_sleep = sleep_recs[0] if sleep_recs else {}
            latest_rec = rec_recs[0] if rec_recs else {}

            recovery_score_obj = latest_rec.get('score', {})
            strain_obj = latest_cycle.get('score', {})
            sleep_score_obj = latest_sleep.get('score', {})

            # Consolidate standard keys for app.py and logic.py consumption
            return {
                "score": {
                    "recovery_score": recovery_score_obj.get('recovery_score', 0),
                    "hrv_rmssd_milli": recovery_score_obj.get('hrv_rmssd_milli', 0.0),
                    "resting_heart_rate": recovery_score_obj.get('resting_heart_rate', 0),
                    "strain": strain_obj.get('strain', 0.0),
                    "day_strain": strain_obj.get('strain', 0.0), # Fallback mapping
                    "sleep_performance_percentage": sleep_score_obj.get('sleep_performance_percentage', 0)
                }
            }
        return None
    except Exception as e:
        logger.error(f"Whoop data fetch failed: {e}")
        return None

def save_tokens(token_data):
    """Calculates expiration time and saves tokens to session state and local vault."""
    token_data['expires_at'] = time.time() + token_data.get('expires_in', 3600)
    st.session_state.whoop_token = token_data.get("access_token")
    
    try:
        with open(TOKEN_FILE, 'w') as f:
            json.dump(token_data, f)
    except Exception as e:
        logger.error(f"Failed to save tokens locally: {e}")

def load_tokens():
    """Retrieves tokens from the local JSON vault."""
    try:
        with open(TOKEN_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None

def refresh_access_token(refresh_token):
    """Trades a refresh token for a fresh access token if credentials are near expiry."""
    try:
        response = requests.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        }, timeout=10)
        
        if response.status_code == 200:
            new_tokens = response.json()
            save_tokens(new_tokens)
            return new_tokens['access_token']
    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
    return None

def get_valid_access_token():
    """Master controller for retrieving a usable token, handling refresh if necessary."""
    if "whoop_token" in st.session_state and st.session_state.whoop_token:
        return st.session_state.whoop_token
        
    tokens = load_tokens()
    if not tokens:
        return None
    
    if time.time() > tokens.get('expires_at', 0) - 300:
        return refresh_access_token(tokens.get('refresh_token'))
    
    return tokens.get('access_token')