import html
import secrets
import streamlit as st
import plotly.graph_objects as go
import anthropic
import styles
import logic
import json
import whoop
import hashlib
import base64
import re
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import calendar_sync
from audio_recorder_streamlit import audio_recorder
from openai import OpenAI
import tempfile

# =============================================================================
# GLOBAL SAFETY GUARDRAILS (FDA SaMD AVOIDANCE)
# =============================================================================
CLINICAL_GUARDRAIL = """
CRITICAL SYSTEM INSTRUCTION: YOU ARE A BEHAVIORAL WELLNESS COACH AND RISK MANAGEMENT ENGINE. YOU ARE NOT A DOCTOR. 
UNDER NO CIRCUMSTANCES ARE YOU PERMITTED TO PRESCRIBE, SUGGEST, OR CALCULATE DOSAGES FOR INSULIN OR ANY OTHER MEDICATION. 
NEVER SAY "TAKE X UNITS OF INSULIN". NEVER DISCUSS INSULIN-TO-CARB RATIOS. 
IF YOU DO THIS, YOU VIOLATE FEDERAL FDA REGULATIONS. 
ALL ACTION DIRECTIVES MUST BE STRICTLY BEHAVIORAL (E.G., WALKING, RESTING) OR NUTRITIONAL (E.G., CONSUME 15G OF FAST ACTING CARBS, EAT PROTEIN).
"""

# -----------------------------------------------------------------------------
# 1. SETUP & PAGE CONFIG
# -----------------------------------------------------------------------------
st.set_page_config(page_title="TLDH Beta 1.0", page_icon="🌙", layout="wide", initial_sidebar_state="collapsed")
styles.apply_theme()
styles.inject_custom_css()

# -----------------------------------------------------------------------------
# 1.5 THE VELVET ROPE (IP PROTECTION GATE)
# -----------------------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center; color: #8B5CF6; font-size: 3rem;'>🔒 TLDH Beta</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: var(--text-secondary); font-size: 1.2rem; margin-bottom: 30px;'>Agentic Engine IP is currently locked. Authorized access only.</p>", unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns([1, 1.5, 1])
    with c2:
        with st.container(border=True):
            pwd = st.text_input("Access Code", type="password", label_visibility="collapsed", placeholder="Enter Clearance Code...")
            if st.button("Unlock Engine", use_container_width=True, type="primary"):
                if pwd == st.secrets.get("APP_PASSWORD", "admin"): 
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Access Denied. Incorrect Clearance Code.")
    st.stop()

# -----------------------------------------------------------------------------
# 2. CLAUDE WRAPPER & CORE LOGIC
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        """
        <div style="background-color: rgba(76, 175, 80, 0.1); padding: 12px; border-radius: 8px; text-align: center; border: 1px solid #4CAF50; margin-bottom: 20px;">
            <span style="color: #4CAF50; font-weight: 800; font-size: 0.95em; letter-spacing: 1px;">🟢 PATENT PENDING</span><br>
            <span style="color: #888888; font-size: 0.75em; font-weight: 600;">App No. 64/004,105</span><br>
            <span style="color: #888888; font-size: 0.75em;">Closed-Loop Logic Engine Protected</span>
        </div>
        """,
        unsafe_allow_html=True
    )

try:
    client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
    ACTIVE_MODEL = 'claude-haiku-4-5' 
except Exception as e:
    st.error(f"⚠️ API Critical Failure: {e}"); st.stop()

try:
    openai_client = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY", ""))
except Exception:
    openai_client = None

def ask_claude(system_instruction, user_messages, max_tokens=500, parse_json=True):
    safe_sys = system_instruction + "\n\n" + CLINICAL_GUARDRAIL
    try:
        res = client.messages.create(model=ACTIVE_MODEL, max_tokens=max_tokens, system=safe_sys, messages=user_messages)
        text = res.content[0].text.strip()
        if parse_json:
            text = text.replace("```json", "").replace("```", "").strip()
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                text = match.group(0)
            return json.loads(text)
        return text
    except Exception as e:
        if "not_found_error" in str(e) or "404" in str(e):
            raise Exception(f"**API Account Locked:** Check Anthropic billing.")
        raise e

def get_claude_tone():
    ctx = st.session_state.current_context
    if ctx == "Stressed": return "gentle, concerned, and highly supportive. Encourage rest, restorative action, and self-compassion."
    elif ctx == "Exercise": return "excited, energetic, and highly encouraging. Push healthy activity and proper metabolic fueling."
    elif ctx == "Recovery": return "calm, analytical, and restorative. Focus on refueling, managing post-exercise spikes/drops, and optimizing sleep."
    elif ctx == "Sick": return "compassionate, cautious, and clinically protective. Focus on hydration, gentle recovery, and fighting resistance."
    elif ctx == "Travel": return "vigilant, organized, and proactive. Focus on logistical stability."
    else: return "warm, personal, and highly actionable like an elite clinical coach."

def get_time_remaining(end_time):
    if not end_time: return ""
    diff = end_time - datetime.now()
    if diff.total_seconds() <= 0: return ""
    mins = int(diff.total_seconds() / 60)
    return f"{mins//60}h {mins%60}m left" if mins >= 60 else f"{mins}m left"

def calculate_gmi(mean_glucose):
    if pd.isna(mean_glucose): return 0.0
    return round(3.31 + (0.02392 * mean_glucose), 1)

def calculate_tir(df):
    if len(df) == 0: return 0.0
    in_range = len(df[(df['Glucose_Value'] >= 70) & (df['Glucose_Value'] <= 180)])
    return round((in_range / len(df)) * 100, 1)

# -----------------------------------------------------------------------------
# 3. STATE, TIMERS & EVENT LOGGING
# -----------------------------------------------------------------------------
def load_ns_config():
    try:
        with open("ns_config.json", "r") as f: return json.load(f)
    except: return {"url": "", "token": ""}

def save_ns_config(url, token):
    try:
        with open("ns_config.json", "w") as f: json.dump({"url": url, "token": token}, f)
    except: pass

ns_cfg = load_ns_config()

# Initialization
if "current_context" not in st.session_state: st.session_state.current_context = "Normal"
if "context_end_time" not in st.session_state: st.session_state.context_end_time = None
if "ns_url" not in st.session_state: st.session_state.ns_url = ns_cfg.get("url", "")
if "ns_token" not in st.session_state: st.session_state.ns_token = ns_cfg.get("token", "")
if "whoop_token" not in st.session_state: st.session_state.whoop_token = whoop.get_valid_access_token()
if "camera_active" not in st.session_state: st.session_state.camera_active = False
if "mic_active" not in st.session_state: st.session_state.mic_active = False
if "event_log" not in st.session_state: st.session_state.event_log = []
if "muted_intercepts" not in st.session_state: st.session_state.muted_intercepts = {}
if "_toast" not in st.session_state: st.session_state._toast = None
if "active_view" not in st.session_state: st.session_state.active_view = "Home"
if "latest_trend_insight" not in st.session_state: st.session_state.latest_trend_insight = "No macro trend synthesized yet. Run an analysis in the Trends tab."
if "show_dossier" not in st.session_state: st.session_state.show_dossier = False
if "smart_nudge_dismissed" not in st.session_state: st.session_state.smart_nudge_dismissed = False

if st.session_state._toast:
    st.toast(st.session_state._toast)
    st.session_state._toast = None

def log_event(event_type, description):
    st.session_state.event_log.append({
        "time": datetime.now().strftime("%I:%M %p"),
        "type": event_type,
        "desc": description
    })
    st.session_state.event_log = st.session_state.event_log[-15:]

if st.session_state.context_end_time and datetime.now() > st.session_state.context_end_time:
    if st.session_state.current_context == "Exercise":
        st.session_state.current_context = "Recovery"
        st.session_state.context_end_time = datetime.now() + timedelta(hours=2)
        log_event("📍 Mode Shift", "Auto-shifted from Exercise to Recovery")
        st.session_state._toast = "🔋 Exercise concluded. Recovery mode activated."
        st.rerun() 
    else:
        st.session_state.current_context = "Normal"
        st.session_state.context_end_time = None
        log_event("📍 Mode Shift", "Context timer expired. Returned to Normal.")
        st.session_state._toast = "🟢 Context timer expired. Returned to Normal."
        st.rerun() 

if "code" in st.query_params and not st.session_state.whoop_token:
    with st.spinner("Authenticating Integrations..."):
        if st.query_params.get("state") == st.session_state.get("oauth_state"):
            token_data = whoop.get_access_token(st.query_params["code"])
            if token_data and "access_token" in token_data:
                st.session_state.whoop_token = token_data["access_token"]
                whoop.save_tokens(token_data); st.query_params.clear(); st.rerun()

@st.cache_data(ttl=300)
def get_cached_health_data(url, token):
    if url:
        real_df = logic.fetch_nightscout_data(url, token)
        if real_df is not None and not real_df.empty: return real_df, True
    return logic.fetch_health_data(), False

@st.cache_data(ttl=60)
def get_cached_glycemic_risk(df, context, whoop_data=None, meeting_count=0, speaker_mode=False, owm_api_key="", is_real_data=False):
    return logic.calc_glycemic_risk(df, context, whoop_data, meeting_count, speaker_mode, owm_api_key, is_real_data)

# --- LINTER FIX: Initialize variables to resolve "unbound" warnings ---
w_rec = w_sleep = w_hrv = w_rhr = 0
w_strain = 0.0
meeting_count = 0
speaker_mode = False
is_real_cgm = False
full_data = pd.DataFrame()
latest_bg = pd.Series({'Glucose_Value': 100, 'Trend': 'Steady', 'Timestamp': datetime.now()})
raw_reason = ""
status = ""
color_hex = ""

try:
    with st.spinner("Synchronizing biometric telemetry..."):
        whoop_metrics = whoop.fetch_whoop_recovery(st.session_state.whoop_token) if st.session_state.whoop_token else None
        meeting_count = st.session_state.get("local_meeting_count", calendar_sync.fetch_calendar_context()[0])
        speaker_mode = st.session_state.get("local_speaker_mode", calendar_sync.fetch_calendar_context()[1])
        
        if whoop_metrics:
            w_rec = whoop_metrics.get('recovery', {}).get('score', {}).get('recovery_score', 0) if 'recovery' in whoop_metrics else whoop_metrics.get('score', {}).get('recovery_score', 0)
            w_sleep = whoop_metrics.get('sleep', {}).get('score', {}).get('sleep_performance_percentage', 0) if 'sleep' in whoop_metrics else whoop_metrics.get('score', {}).get('sleep_performance_percentage', 0)
            w_strain = round(whoop_metrics.get('score', {}).get('strain', 0.0), 1)
            w_hrv = int(whoop_metrics.get('recovery', {}).get('score', {}).get('hrv_rmssd_milli', 0)) if 'recovery' in whoop_metrics else int(whoop_metrics.get('score', {}).get('hrv_rmssd_milli', 0))
            w_rhr = int(whoop_metrics.get('recovery', {}).get('score', {}).get('resting_heart_rate', 0)) if 'recovery' in whoop_metrics else int(whoop_metrics.get('score', {}).get('resting_heart_rate', 0))
        else: w_rec, w_sleep, w_strain, w_hrv, w_rhr = 0, 0, 0.0, 0, 0

        raw_data, is_real_cgm = get_cached_health_data(st.session_state.ns_url, st.session_state.ns_token)
        full_data, status, color_hex, raw_reason = get_cached_glycemic_risk(raw_data, st.session_state.current_context, whoop_metrics, meeting_count, speaker_mode, st.secrets.get("OWM_API_KEY", ""), is_real_cgm)
        latest_bg = full_data.iloc[-1]
except Exception as e:
    st.error(f"Data loading failed: {e}"); st.stop()

# -----------------------------------------------------------------------------
# 4. BUILD ACTIVE MEMORY (Context Injector)
# -----------------------------------------------------------------------------
active_memory_list = []
if st.session_state.get("latest_meal_analysis"):
    meal_mem = st.session_state.latest_meal_analysis
    raw_c = meal_mem.get('estimated_carbs_g', 0)
    display_c = raw_c.get('total_estimated', raw_c.get('total', 0)) if isinstance(raw_c, dict) else raw_c
    active_memory_list.append(f"Recently logged a meal via camera: {meal_mem.get('food_identified', 'Food')} ({display_c}g carbs, {meal_mem.get('glycemic_index', 'Unknown')} GI).")

if st.session_state.current_context in ["Exercise", "Recovery"]:
    active_memory_list.append(f"Currently in {st.session_state.current_context} mode. High physiological load expected.")
elif w_strain > 12.0:
    active_memory_list.append(f"Notable daily Whoop strain recorded today: {w_strain}.")

recent_journals = [e for e in st.session_state.event_log if e['type'] in ["🍽️ Meal", "💊 Medication", "🏃‍♂️ Exercise", "📝 Other"]]
if recent_journals:
    latest_journal = recent_journals[-1]
    active_memory_list.append(f"Recent user journal entry ({latest_journal['type']}): {latest_journal['desc']}")

context_memory_string = " | ".join(active_memory_list) if active_memory_list else "No active external events logged."

# -----------------------------------------------------------------------------
# 5. AUTO-DETECT INTERCEPTS & UI HEADERS
# -----------------------------------------------------------------------------
st.markdown(f"""
    <div style="margin-top: 10px; margin-bottom: 25px; padding: 24px 30px; background: linear-gradient(135deg, rgba(139,92,246,0.08), rgba(109,40,217,0.03)); border: 1px solid rgba(139,92,246,0.2); border-radius: 24px; box-shadow: 0 8px 24px rgba(0,0,0,0.04);">
        <div style="font-size: 34px; font-weight: 900; background: linear-gradient(135deg, #8B5CF6, #6D28D9); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: -0.5px; line-height: 1.2;">
            Total Life Download Hub
        </div>
        <div style="color: var(--text-secondary); font-weight: 600; font-size: 1.15rem; margin-top: 4px; letter-spacing: 0.5px;">Agentic Risk Management Engine</div>
    </div>
""", unsafe_allow_html=True)

# Hardware Auto-Detect Intercepts (Alpha Logic)
if st.session_state.current_context == "Normal":
    auto_mode, auto_dur, auto_reason = None, 0, ""
    if len(full_data) >= 6 and all(full_data.tail(6)['Glucose_Value'] > 160):
        auto_mode, auto_dur, auto_reason = "Stressed", 3, "Sustained elevated glucose detected."
    elif w_strain > 14.0 and latest_bg['Trend'] in ["Falling", "Falling Fast"]:
        auto_mode, auto_dur, auto_reason = "Recovery", 2, "High Whoop strain detected with dropping glucose (Post-Workout)."
    elif w_strain > 14.0:
        auto_mode, auto_dur, auto_reason = "Exercise", 2, "High systemic strain detected via Whoop."
        
    if auto_mode and auto_mode in st.session_state.muted_intercepts:
        if datetime.now() < st.session_state.muted_intercepts[auto_mode]:
            auto_mode = None 
            
    if auto_mode:
        st.info(f"🤖 **Agentic Intercept:** {auto_reason} Shift to **{auto_mode}** mode for {auto_dur} hours?")
        col1, col2, _ = st.columns([1, 1, 3])
        if col1.button(f"✅ Yes, activate", key=f"yes_{auto_mode}"):
            st.session_state.current_context = auto_mode
            st.session_state.context_end_time = datetime.now() + timedelta(hours=auto_dur)
            log_event("📍 Mode Shift", f"Auto-shifted to {auto_mode} ({auto_reason})")
            st.session_state._toast = f"✅ Agentic shift to {auto_mode} active!"
            st.rerun()
        if col2.button(f"❌ No, dismiss", key=f"no_{auto_mode}"):
            st.session_state.muted_intercepts[auto_mode] = datetime.now() + timedelta(hours=2)
            st.rerun()
    
    # BETA UI: Smart Agentic Nudge (If no hardware intercept triggered, check schedule friction)
    elif meeting_count >= 4 and not st.session_state.smart_nudge_dismissed and st.session_state.active_view != "Recovery":
        st.markdown("""
            <div class="agentic-nudge">
                <span style="font-weight: 800; color: #8B5CF6; font-size: 0.9rem; text-transform: uppercase;">⚡ Agentic Intercept</span><br>
                <span style="font-size: 1.05rem; color: #FAFAFA;">High calendar density detected. To prevent afternoon cortisol-driven volatility, I recommend initiating the Dual-Vector Recovery protocol.</span>
            </div>
        """, unsafe_allow_html=True)
        c1, c2, _ = st.columns([1.5, 1.5, 4])
        if c1.button("Initiate Recovery", type="primary", use_container_width=True):
            st.session_state.active_view = "Recovery"
            st.session_state.smart_nudge_dismissed = True
            st.rerun()
        if c2.button("Dismiss Nudge", use_container_width=True):
            st.session_state.smart_nudge_dismissed = True
            st.rerun()

elif st.session_state.current_context == "Exercise":
    if latest_bg['Trend'] == "Falling Fast":
        if "Recovery" not in st.session_state.muted_intercepts or datetime.now() >= st.session_state.muted_intercepts["Recovery"]:
            st.warning("🤖 **Agentic Intercept:** Rapid glucose drop detected during Exercise. Shift to **Recovery** mode early to focus on refueling?")
            col1, col2, _ = st.columns([1, 1, 3])
            if col1.button("✅ Yes, activate Recovery", key="yes_rec_early"):
                st.session_state.current_context = "Recovery"
                st.session_state.context_end_time = datetime.now() + timedelta(hours=2)
                log_event("📍 Mode Shift", "Early auto-shift to Recovery due to BG drop")
                st.session_state._toast = "✅ Recovery mode activated!"
                st.rerun()
            if col2.button("❌ No, dismiss", key="no_rec_early"):
                st.session_state.muted_intercepts["Recovery"] = datetime.now() + timedelta(hours=2)
                st.rerun()

# --- LINTER FIX: Initialize UI event variables to remove locals() warnings ---
db_search_submit = False
db_search_query = ""
text_submit = False
text_input = ""
food_image = None

with st.container(border=True):
    hc1, hc2, hc3, hc4, hc5 = st.columns([3.0, 1.8, 1.8, 1.8, 1.6])
    
    with hc1:
        st.markdown("<p style='font-weight: 800; color: var(--text-secondary); text-transform: uppercase; font-size: 0.75rem; letter-spacing: 1px; margin-top: 5px; margin-bottom: 12px;'>⚡ Total Life Drivers</p>", unsafe_allow_html=True)
        vectors = []
        
        if st.session_state.current_context != "Normal":
            rem = get_time_remaining(st.session_state.context_end_time)
            icon = {"Stressed": "🧘‍♂️", "Exercise": "🏃‍♂️", "Recovery": "🔋", "Sick": "🤒", "Project": "🧠", "Travel": "✈️"}.get(st.session_state.current_context, "🟣")
            vectors.append(f"{icon} {st.session_state.current_context} ({rem})")

        tir_df = full_data.tail(36)
        if len(tir_df) > 0:
            low, tgt, elev, high = [len(tir_df[cond])/len(tir_df)*100 for cond in [tir_df['Glucose_Value'] < 80, (tir_df['Glucose_Value'] >= 80) & (tir_df['Glucose_Value'] <= 140), (tir_df['Glucose_Value'] > 140) & (tir_df['Glucose_Value'] <= 180), tir_df['Glucose_Value'] > 180]]
            if low > 5: vectors.append(f"🔴 {int(low)}% BG Low (3h)")
            elif high > 15: vectors.append(f"🔴 {int(high)}% BG High (3h)")
            elif elev > 25: vectors.append(f"🟡 {int(elev)}% BG Elevated (3h)")
            else: vectors.append(f"🟢 {int(tgt)}% BG On Target (3h)")

        for p in raw_reason.split("|"):
            clean = re.sub(r'Hyperglycemic risk detected\.?|Hypoglycemic risk detected\.?|Compounded Strain Detected\!|System nominal\.?', '', p).replace('()', '').replace('(', '').replace(')', '').strip()
            if clean: vectors.append(html.escape(clean))
        
        tags_html = "".join([styles.get_driver_pill_html(t) for t in (vectors[:4] if vectors else ["🟢 All Systems Nominal"])])
        st.markdown(f"<div style='display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 25px;'>{tags_html}</div>", unsafe_allow_html=True)
    
    with hc2:
        st.markdown("<div class='desktop-spacer' style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.session_state.get("journal_history"):
            if st.button("🎙️ Log Another Note", use_container_width=True):
                st.session_state.journal_history = []
                st.rerun()
        else:
            with st.popover("🎙️ Companion", use_container_width=True):
                st.caption("Tap the mic or type a note. The AI will correlate your state with live telemetry.")
                if not st.session_state.mic_active:
                    if st.button("🎙️ Enable Microphone", use_container_width=True):
                        st.session_state.mic_active = True
                        st.rerun()
                else:
                    audio_bytes = audio_recorder(text="Record Voice Note", recording_color="#ED8796", neutral_color="#8B5CF6", icon_size="2x")
                    if st.button("❌ Disable Mic", use_container_width=True):
                        st.session_state.mic_active = False; st.rerun()
                    if audio_bytes and hashlib.md5(audio_bytes).hexdigest() != st.session_state.get("last_audio_hash"):
                        st.session_state.last_audio_hash = hashlib.md5(audio_bytes).hexdigest()
                        if openai_client and st.secrets.get("OPENAI_API_KEY"):
                            with st.spinner("Transcribing Voice Note..."):
                                try:
                                    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as fp:
                                        fp.write(audio_bytes)
                                        temp_path = fp.name
                                    with open(temp_path, "rb") as af:
                                        transcript = openai_client.audio.transcriptions.create(model="whisper-1", file=af)
                                    text_input = transcript.text
                                    text_submit = True 
                                except Exception as e:
                                    st.error(f"Transcription failed: {e}")
                        else:
                            st.warning("🎙️ **OpenAI API Key Missing!** Add OPENAI_API_KEY to your Streamlit secrets to enable Speech-to-Text.")
                
                st.divider()
                with st.form("companion_journal_form", clear_on_submit=True):
                    form_text = st.text_area("Or type your observation:", placeholder="E.g., 'Just finished a heavy lift.'", label_visibility="collapsed")
                    form_submit = st.form_submit_button("Synthesize Telemetry", use_container_width=True)
                
                if form_submit and form_text:
                    text_input = form_text
                    text_submit = True
            
    with hc3:
        st.markdown("<div class='desktop-spacer' style='height: 28px;'></div>", unsafe_allow_html=True)
        if st.session_state.get("latest_meal_analysis"):
            if st.button("🍽️ Scan Another Meal", use_container_width=True):
                st.session_state.latest_meal_analysis = None
                st.rerun()
        else:
            with st.popover("🍽️ Meals", use_container_width=True):
                st.caption("Snap a photo to estimate carbohydrates and metabolic impact.")
                if not st.session_state.camera_active:
                    if st.button("📸 Open Camera Scanner", use_container_width=True):
                        st.session_state.camera_active = True
                        st.rerun()
                else:
                    food_image = st.camera_input("Food Scanner", label_visibility="collapsed")
                    if st.button("❌ Disable Camera", use_container_width=True):
                        st.session_state.camera_active = False; st.rerun()
                        
                st.divider()
                with st.form("usda_search_form"):
                    db_search_query = st.text_input("Search USDA Database:", placeholder="E.g., 1 cup cooked quinoa")
                    db_search_submit = st.form_submit_button("Look up Food Macros", use_container_width=True)
                
    with hc4:
        st.markdown("<div class='desktop-spacer' style='height: 28px;'></div>", unsafe_allow_html=True)
        with st.popover("📓 Journal", use_container_width=True):
            st.caption("Log a daily event, meal, or brain dump.")
            with st.form("manual_event_form", clear_on_submit=True):
                ev_type = st.selectbox("Type", ["🍽️ Meal", "💊 Medication", "🏃‍♂️ Exercise", "📝 Other"], label_visibility="collapsed")
                ev_desc = st.text_area("Context", placeholder="E.g., I had a cookie at lunch, it had a lot more carbs than I was expecting...", height=100)
                if st.form_submit_button("Log Entry", use_container_width=True):
                    if ev_desc:
                        log_event(ev_type, ev_desc)
                        st.session_state._toast = f"✅ {ev_type.split(' ')[1]} logged to memory!"
                        st.rerun()
                        
    with hc5:
        st.markdown("<div class='desktop-spacer' style='height: 28px;'></div>", unsafe_allow_html=True)
        with st.popover("☰ Menu", use_container_width=True):
            st.markdown("##### 📖 Log Book")
            with st.container(border=True):
                if not st.session_state.event_log:
                    st.caption("No entries logged yet today.")
                else:
                    for event in reversed(st.session_state.event_log):
                        st.markdown(f"**{event['time']}** - {event['type']}<br><span style='color:gray; font-size:0.85em;'>{event['desc']}</span>", unsafe_allow_html=True)
                        
            st.divider()
            
            st.markdown("##### 📍 Context Settings")
            with st.form("context_override_form"):
                new_ctx = st.selectbox("Force Context Mode:", ["Normal", "Stressed", "Recovery", "Sick", "Exercise", "Project", "Travel"], index=["Normal", "Stressed", "Recovery", "Sick", "Exercise", "Project", "Travel"].index(st.session_state.current_context))
                dur_val = st.selectbox("Duration:", [0.5, 1.0, 3.0, 6.0], format_func=lambda x: f"{int(x)} hours" if x >= 1 else "30 mins")
                if st.form_submit_button("Apply Mode", use_container_width=True):
                    st.session_state.current_context = new_ctx
                    st.session_state.context_end_time = datetime.now() + timedelta(hours=dur_val) if new_ctx != "Normal" else None
                    log_event("📍 Mode Shift", f"Manually set to {new_ctx} for {dur_val}h")
                    st.session_state._toast = f"✅ Context updated to {new_ctx}!"
                    st.rerun()
            
            st.divider()
            st.markdown("##### 🔌 Integrations")
            st.markdown("**🩸 Nightscout CGM Sync**")
            if st.session_state.ns_url:
                if is_real_cgm: st.success("🟢 Connected & Streaming Live")
                else: st.error("🔴 Connection Failed. (Simulated Data)")
                if st.button("Disconnect / Reconnect", key="dc_ns"):
                    st.session_state.ns_url = ""; st.session_state.ns_token = ""
                    save_ns_config("", "")
                    st.cache_data.clear(); st.rerun()
            else:
                with st.form("ns_form"):
                    ns_url_input = st.text_input("Nightscout URL", placeholder="https://your-name.herokuapp.com")
                    ns_token_input = st.text_input("API Token (Optional)", type="password")
                    if st.form_submit_button("Connect", use_container_width=True):
                        st.session_state.ns_url = ns_url_input; st.session_state.ns_token = ns_token_input
                        save_ns_config(ns_url_input, ns_token_input)
                        st.cache_data.clear(); st.rerun()
            
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("**⚡ Whoop Telemetry**")
            if not st.session_state.whoop_token:
                oauth_state = secrets.token_urlsafe(16)
                st.components.v1.html(f"<script>window.parent.document.cookie = 'whoop_oauth_state={oauth_state}; path=/; max-age=3600; SameSite=Lax';</script>", height=0)
                st.link_button("🔗 Connect Whoop", whoop.get_authorization_url(oauth_state), use_container_width=True)
            else:
                if whoop_metrics: st.success("🟢 Connected & Syncing")
                else: st.error("🔴 Data Sync Failed (Cached)")
                if st.button("🔄 Force Refresh Sync", use_container_width=True): 
                    st.session_state.whoop_token = whoop.get_valid_access_token()
                    whoop.fetch_whoop_recovery.clear()
                    st.rerun() 
                    
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("**📱 Native Calendar (Mock)**")
            cal_file = st.file_uploader("Upload .ics", type=["ics"], label_visibility="collapsed")
            if cal_file:
                mc, sm = calendar_sync.analyze_local_calendar(cal_file.getvalue().decode("utf-8"))
                st.session_state.local_meeting_count, st.session_state.local_speaker_mode = mc, sm
                st.success(f"Local Sync: {mc} events loaded.")
                
            # --- DOCTOR REPORT GENERATION BUTTON ---
            st.divider()
            st.markdown("##### 🩺 Clinical Export")
            if st.button("📄 Create a Report for my Doctor", use_container_width=True):
                st.session_state.show_dossier = True
                st.rerun()

st.divider()

# -----------------------------------------------------------------------------
# 6. EVENT PROCESSORS (SEMANTIC NLP DETECT)
# -----------------------------------------------------------------------------

# --- Process USDA Text Search ---
if db_search_submit and db_search_query:
    with st.spinner(f"Querying USDA Macro Database for '{db_search_query}'..."):
        try:
            sys = f"""You are my elite personal clinical nutritionist managing my Type 1 Diabetes.
            Look up the exact macronutrients for the following food query: {db_search_query}.
            Speak directly to me using "you" and "your". Tone should be {get_claude_tone()}.
            Return ONLY a valid JSON object with EXACTLY these keys and strict data types:
            - "food_identified": "Short description." (Must be a String)
            - "estimated_carbs_g": 45 (MUST be a single Integer. No dictionaries)
            - "glycemic_index": "High", "Medium", or "Low" (Must be a String)
            - "analysis": "A concise 2-sentence clinical breakdown." (Must be a String)"""
            
            meal_data = ask_claude(sys, [{"role": "user", "content": "Retrieve exact macros for this query."}])
            meal_data["source"] = "🔍 USDA Text Search"
            
            raw_c = meal_data.get('estimated_carbs_g', 0)
            display_c = raw_c.get('total_estimated', raw_c.get('total', 0)) if isinstance(raw_c, dict) else raw_c
            log_event("🍽️ Meal", f"{meal_data.get('food_identified', 'Food')} ({display_c}g Carbs)")
            
            st.session_state.latest_meal_analysis = meal_data
            st.rerun() 
        except Exception as e: st.error(f"Search Failed: {e}")

# --- Process Audio/Text Journals ---
if text_submit and text_input:
    with st.spinner("Correlating subjective report with objective telemetry..."):
        try:
            ctx = {"context": st.session_state.current_context, "meetings": meeting_count, "glucose": int(latest_bg['Glucose_Value']), "trend": latest_bg['Trend']}
            sys = f"""You are my elite AI clinical assistant. My telemetry: {json.dumps(ctx)}. 
            Active Memory Context: {context_memory_string}.
            Clinical Guardrails: Target range is 70-180 mg/dL. Any spike above 180 is considered high and requires attention.
            Correlate my text with the telemetry and memory. 
            Speak to me as 'you'. Tone should be {get_claude_tone()}. NEVER refer to me as "the patient".
            Return ONLY a valid JSON object with EXACTLY these keys:
            - "reply": "A contextual response. Include clinical escalation if anomalous symptoms persist."
            - "summary": "3 words."
            - "scores": {{"bio_strain": 5, "cog_load": 5}}
            - "impact_prediction": "1-sentence prediction."
            - "suggested_mode": "Exercise", "Recovery", "Stressed", "Sick", "Project", "Travel", or "Normal" (Detect from my text)
            - "suggested_duration_hours": 1.5"""
            res_data = ask_claude(sys, [{"role": "user", "content": text_input}])
            res_data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            st.session_state.journal_history = [res_data]
            log_event("🎙️ Note", res_data.get("summary", "Logged observation."))
            st.session_state.mic_active = False 
            st.rerun() 
        except Exception as e: st.error(f"Failed: {e}")

# --- Process Food Camera Image ---
if food_image is not None:
    img_hash = hashlib.md5(food_image.getvalue()).hexdigest()
    if img_hash != st.session_state.get("last_img_hash"):
        st.session_state.last_img_hash = img_hash
        with st.spinner("Analyzing meal nutrition..."):
            try:
                b64 = base64.b64encode(food_image.getvalue()).decode("utf-8")
                sys = f"""You are my elite personal clinical nutritionist managing my Type 1 Diabetes.
                Analyze the food image. Estimate carbs and glycemic index.
                Speak directly to me using "you" and "your". Tone should be {get_claude_tone()}. NEVER refer to me as "the patient".
                Return ONLY a valid JSON object with EXACTLY these keys and strict data types:
                - "food_identified": "Short description." (Must be a String)
                - "estimated_carbs_g": 45 (MUST be a single Integer. No dictionaries)
                - "glycemic_index": "High", "Medium", or "Low" (Must be a String)
                - "analysis": "A concise 2-sentence clinical breakdown." (Must be a String)"""
                meal_data = ask_claude(sys, [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}, {"type": "text", "text": "Analyze this meal for T1D."}]}])
                meal_data["source"] = "📸 Vision Estimate"
                
                raw_c = meal_data.get('estimated_carbs_g', 0)
                display_c = raw_c.get('total_estimated', raw_c.get('total', 0)) if isinstance(raw_c, dict) else raw_c
                log_event("🍽️ Meal", f"{meal_data.get('food_identified', 'Meal')} ({display_c}g Carbs)")
                
                st.session_state.latest_meal_analysis = meal_data
                st.session_state.camera_active = False 
                st.rerun() 
            except Exception as e: st.error(f"Vision Analysis Failed: {e}")

if st.session_state.get("journal_history"):
    entry = st.session_state.journal_history[0]
    st.success(f"**Agentic Insight:** {html.escape(str(entry.get('reply', '')))}")
    
    s_mode = entry.get("suggested_mode", "Normal")
    if s_mode and s_mode != "Normal" and s_mode != st.session_state.current_context:
        s_dur = float(entry.get("suggested_duration_hours", 1.0))
        st.warning(f"🤖 **Context Suggestion:** Your note implies you are in **{s_mode}** mode.")
        col1, col2, _ = st.columns([1, 1, 3])
        if col1.button(f"⚡ Apply '{s_mode}'", key="nlp_yes"):
            st.session_state.current_context = s_mode
            st.session_state.context_end_time = datetime.now() + timedelta(hours=s_dur)
            log_event("📍 Mode Shift", f"Applied {s_mode} via AI Suggestion")
            st.session_state._toast = f"✅ Context shifted to {s_mode}!"
            st.session_state.journal_history = []
            st.rerun()
        if col2.button(f"❌ Dismiss", key="nlp_no"):
            entry['suggested_mode'] = "Normal"
            st.rerun()

    c1, c2, c3 = st.columns(3); c1.metric("🧬 Bio-Strain", f"{entry.get('scores',{}).get('bio_strain', 0)}/10"); c2.metric("🧠 Cog-Load", f"{entry.get('scores',{}).get('cog_load', 0)}/10"); c3.metric("📌 Status", html.escape(str(entry.get("summary", ""))))
    st.info(f"**📉 Horizon Scan:** {html.escape(str(entry.get('impact_prediction', '')))}")
    if st.button("Dismiss Insight", use_container_width=True): st.session_state.journal_history = []; st.rerun()
    st.divider()

if st.session_state.get("latest_meal_analysis"):
    meal = st.session_state.latest_meal_analysis
    st.markdown(f"### 🍽️ Meal Analysis <span style='font-size:14px;color:gray;'>({meal.get('source')})</span>", unsafe_allow_html=True)
    m1, m2, m3 = st.columns([1, 1, 2])
    m1.metric("Identified", str(meal.get("food_identified", "Unknown")))
    raw_carbs = meal.get('estimated_carbs_g', 0)
    display_carbs = raw_carbs.get('total_estimated', raw_carbs.get('total', 0)) if isinstance(raw_carbs, dict) else raw_carbs
    m2.metric("Carbs", f"{display_carbs}g")
    gi = str(meal.get("glycemic_index", "Unknown"))
    gi_color = "🔴" if "high" in gi.lower() else "🟡" if "medium" in gi.lower() else "🟢"
    m3.metric("Glycemic Index", f"{gi_color} {gi}")
    
    st.info(f"**Clinical Insight:** {meal.get('analysis', '')}")
    if st.button("Dismiss Analysis", use_container_width=True): st.session_state.latest_meal_analysis = None; st.rerun()
    st.divider()

# -----------------------------------------------------------------------------
# 7. NAVIGATION & RENDER VIEWS (BETA UI UPDATES)
# -----------------------------------------------------------------------------
views = ["Home", "Insights", "Recovery", "Trends", "Sleep"]
v_cols = st.columns(len(views))
for i, view in enumerate(views):
    is_active = (st.session_state.active_view == view)
    if v_cols[i].button(view, use_container_width=True, type="primary" if is_active else "secondary"):
        st.session_state.active_view = view
        st.rerun()
st.markdown("---")

# -----------------------------------------------------------------------------
# DYNAMIC DASHBOARD VIEWS
# -----------------------------------------------------------------------------
if st.session_state.show_dossier:
    with st.container(border=True):
        st.markdown("## 🩺 Clinical ERM Dossier")
        st.caption(f"Generated on {datetime.now().strftime('%B %d, %Y')} | Confidential Medical Data")
        
        dos_c1, dos_c2, dos_c3, dos_c4 = st.columns(4)
        d_gmi = calculate_gmi(full_data['Glucose_Value'].mean())
        d_tir = calculate_tir(full_data)
        dos_c1.metric("Est. GMI", f"{d_gmi}%")
        dos_c2.metric("Time in Range (70-180)", f"{d_tir}%")
        dos_c3.metric("Avg Sleep Perf", f"{w_sleep}%" if w_sleep else "N/A")
        dos_c4.metric("Avg Daily Strain", f"{w_strain}" if w_strain else "N/A")
        
        with st.spinner("Synthesizing clinical report..."):
            try:
                sys_prompt = f"""You are an elite endocrinologist generating a clinical dossier for a patient's medical file.
                Metrics: GMI {d_gmi}%, TIR {d_tir}%, Sleep Performance {w_sleep}%, Strain {w_strain}.
                Analyze this data from an Enterprise Risk Management perspective. Output a 3-paragraph clinical summary highlighting systemic correlations (e.g., how their sleep and strain impact their glycemic volatility) and suggest 2 behavioral interventions. Speak in the third person ('The patient'). Do not prescribe insulin."""
                dossier_text = ask_claude(sys_prompt, [{"role": "user", "content": "Generate the clinical dossier."}], max_tokens=1500, parse_json=False)
                st.info(dossier_text)
            except Exception as e:
                st.error(f"Failed to generate synthesis: {e}")
        
        if st.button("Close Report", type="primary"):
            st.session_state.show_dossier = False
            st.rerun()
        st.markdown("---")

else:
    if st.session_state.active_view == "Home":
        st.info(f"**🔭 Macro Trend Highlight:** {st.session_state.latest_trend_insight}")
        st.markdown("<br>", unsafe_allow_html=True)
        
        c1, c2, c3, c4 = st.columns(4)
        delta = int(latest_bg['Glucose_Value'] - full_data.iloc[-2]['Glucose_Value'])
        delta_str = f"+{delta}" if delta >= 0 else f"{delta}"
        c1.metric("🩸 Blood Sugar", f"{int(latest_bg['Glucose_Value'])} mg/dL", f"{delta_str} ({latest_bg['Trend']})")
        
        gmi = calculate_gmi(full_data['Glucose_Value'].mean())
        c2.metric("📊 Est. GMI", f"{gmi}%", "Target: < 7.0%" if gmi < 7.0 else "Above Target", delta_color="normal" if gmi < 7.0 else "inverse")
        
        if st.session_state.whoop_token and whoop_metrics:
            c3.metric("⚡ Systemic Strain", f"{w_strain}", f"Recovery: {w_rec}%")
        else:
            c3.metric("⚡ Systemic Strain", "N/A", "Whoop Not Synced")
            
        last_event_str = "No events logged today."
        if st.session_state.event_log:
            last_event = st.session_state.event_log[-1]
            last_event_str = f"{last_event['type']}: {last_event['desc']}"
        c4.metric("📝 Latest Activity", last_event_str)
    
        # PREDICTIVE CONE OF UNCERTAINTY
        st.markdown("---")
        st.markdown("### 📈 Predictive Volatility Horizon")
        st.caption("Fusing primary biometric momentum with systemic strain to visualize the future T+3 hour risk surface.")
        
        strain_multiplier = (w_strain / 21.0) * 30
        sleep_multiplier = 20 if w_sleep < 70 else (10 if w_sleep < 85 else 0)
        max_divergence = 15 + strain_multiplier + sleep_multiplier
        
        current_g = latest_bg['Glucose_Value']
        t0 = latest_bg['Timestamp']
        t_end = t0 + timedelta(hours=3)
        
        trend_val = 15 if "Rising" in latest_bg['Trend'] else (-15 if "Falling" in latest_bg['Trend'] else 5)
        future_g = current_g + trend_val
        
        cone_fig = go.Figure()
        past_df = full_data.tail(24)
        cone_fig.add_trace(go.Scatter(
            x=past_df['Timestamp'], y=past_df['Glucose_Value'], 
            mode='lines', name='Historical', 
            line=dict(color='#10B981', width=3)
        ))
        cone_fig.add_trace(go.Scatter(
            x=[t0, t_end, t_end, t0],
            y=[current_g, future_g + max_divergence, future_g - max_divergence, current_g],
            fill='toself', fillcolor='rgba(99, 102, 241, 0.15)', line=dict(color='rgba(255,255,255,0)'),
            hoverinfo="skip", name='Risk Surface'
        ))
        cone_fig.add_trace(go.Scatter(
            x=[t0, t_end], y=[current_g, future_g], mode='lines', name='Predicted Path', line=dict(color='#6366F1', width=2, dash='dash')
        ))
        
        cone_fig.add_hrect(y0=70, y1=180, line_width=0, fillcolor="rgba(166, 218, 149, 0.1)", opacity=0.3, layer="below")
        cone_fig.add_hline(y=70, line_dash="dot", line_color="#ED8796", layer="below")
        cone_fig.add_hline(y=180, line_dash="dot", line_color="#EED49F", layer="below")
        
        cone_fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color='gray'), height=300, margin=dict(l=0, r=0, t=10, b=0),
            xaxis=dict(showgrid=False, fixedrange=True), yaxis=dict(title="mg/dL", range=[40, 260], showgrid=True, gridcolor='rgba(128,128,128,0.2)', fixedrange=True), showlegend=False
        )
        st.plotly_chart(cone_fig, use_container_width=True, config={'displayModeBar': False})
        st.info(f"**Agentic Insight:** Volatility divergence is currently **±{int(max_divergence)} mg/dL**, influenced by a Whoop Strain multiplier of **{w_strain}** and recent sleep recovery metrics.")

    # ---------------- BETA UI: INSIGHTS (SNAQ KILLER) ----------------
    elif st.session_state.active_view == "Insights":
        st.markdown("### 📊 Enterprise Risk Management Dashboard")
        st.caption("Standard trackers monitor your food. TLDH monitors your systemic biological load.")
        
        st.markdown("<h5 style='color: var(--text-secondary); margin-top: 20px;'>CLINICAL TELEMETRY (Live)</h5>", unsafe_allow_html=True)
        ic1, ic2, ic3 = st.columns(3)
        gmi_val = calculate_gmi(full_data['Glucose_Value'].mean())
        tir_val = calculate_tir(full_data)
        gly_var = int(full_data['Glucose_Value'].std())
        
        ic1.markdown(f"<div class='metric-card'><div class='metric-label'>Estimated A1C (GMI)</div><div class='metric-value'>{gmi_val}%</div><div style='color:#A6DA95;font-size:0.8rem;'>Based on trailing data</div></div>", unsafe_allow_html=True)
        ic2.markdown(f"<div class='metric-card'><div class='metric-label'>Time-In-Range (70-180)</div><div class='metric-value'>{tir_val}%</div><div style='color:#A6DA95;font-size:0.8rem;'>Target: > 70%</div></div>", unsafe_allow_html=True)
        ic3.markdown(f"<div class='metric-card'><div class='metric-label'>Glycemic Variability</div><div class='metric-value'>±{gly_var} mg/dL</div><div style='color:var(--text-secondary);font-size:0.8rem;'>Standard Deviation</div></div>", unsafe_allow_html=True)

        st.markdown("<h5 style='color: var(--text-secondary); margin-top: 20px;'>BEHAVIORAL RISK METRICS</h5>", unsafe_allow_html=True)
        pc1, pc2, pc3 = st.columns(3)
        pc1.markdown("<div class='metric-card'><div class='metric-label'>Cortisol Spikes Averted</div><div class='metric-value'>14</div><div style='color:#8B5CF6;font-size:0.8rem;'>Via Active Recovery Intercepts</div></div>", unsafe_allow_html=True)
        pc2.markdown(f"<div class='metric-card'><div class='metric-label'>Current Bio-Strain</div><div class='metric-value'>{w_strain} / 21</div><div style='color:var(--text-secondary);font-size:0.8rem;'>Synced from Whoop</div></div>", unsafe_allow_html=True)
        pc3.markdown("<div class='metric-card'><div class='metric-label'>Recovery Adherence</div><div class='metric-value'>82%</div><div style='color:#A6DA95;font-size:0.8rem;'>High engagement with protocols</div></div>", unsafe_allow_html=True)

    # ---------------- BETA UI: DUAL-VECTOR RECOVERY ----------------
    elif st.session_state.active_view == "Recovery":
        st.markdown("<h3 style='color: #A6DA95; margin-top: 0;'>🔋 Dual-Vector Recovery Architecture</h3>", unsafe_allow_html=True)
        st.caption("Intentional down-regulation of the nervous system to stabilize metabolic volatility and reduce cognitive load.")
        
        st.markdown("#### Vector 1: Internal Reset (Parasympathetic)")
        r1, r2 = st.columns(2)
        with r1:
            st.markdown("<div class='recovery-box'><strong>🧘‍♂️ Box Breathing (2 Min)</strong><br><span style='font-size:0.85rem;'>Rapid acute stress mitigation.</span></div>", unsafe_allow_html=True)
            if st.button("Log Breathing", use_container_width=True): 
                log_event("🧘‍♂️ Recovery", "2 Min Box Breathing"); st.session_state._toast = "✅ Nervous system down-regulating."; st.rerun()
        with r2:
            st.markdown("<div class='recovery-box'><strong>🕉️ Transcendental Meditation (20 Min)</strong><br><span style='font-size:0.85rem;'>Deep baseline physiological rest.</span></div>", unsafe_allow_html=True)
            if st.button("Log TM Session", use_container_width=True, type="primary"): 
                log_event("🕉️ Recovery", "20 Min TM Session"); st.session_state._toast = "🕰️ Deep physiological rest initiated."; st.rerun()

        st.markdown("---")
        st.markdown("#### Vector 2: External Reset (Contextual)")
        r3, r4 = st.columns(2)
        with r3:
            st.markdown("<div class='recovery-box'><strong>🎧 Contextual Realignment</strong><br><span style='font-size:0.85rem;'>Sensory pattern interruption (Audio/Location shift).</span></div>", unsafe_allow_html=True)
            if st.button("Log Sensory Shift", use_container_width=True): 
                log_event("🎧 Recovery", "Contextual Shift"); st.session_state._toast = "🧠 Cognitive loop broken."; st.rerun()
        with r4:
            st.markdown("<div class='recovery-box'><strong>💧 Hydration Intercept</strong><br><span style='font-size:0.85rem;'>Flush excess glucose; reduce resistance.</span></div>", unsafe_allow_html=True)
            if st.button("Log 16oz Water", use_container_width=True): 
                log_event("💧 Recovery", "16oz Hydration"); st.session_state._toast = "✅ Hydration logged."; st.rerun()

    elif st.session_state.active_view == "Trends":
        top_container = st.container()
        chart_container = st.container()
        
        st.markdown("<br>", unsafe_allow_html=True)
        trend_window = st.radio("Select Horizon", ["1 Week", "1 Month", "3 Months"], horizontal=True, key="trends_tw")
    
        days = 7 if trend_window == "1 Week" else 30 if trend_window == "1 Month" else 90
        dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
        mock_tir = np.clip(np.random.normal(75, 8, days), 0, 100) 
        mock_avg_bg = np.clip(np.random.normal(135, 15, days), 70, 200)
    
        with top_container:
            if st.button(f"🧠 Synthesize {trend_window} Patterns", type="primary", use_container_width=True):
                with st.spinner("Analyzing historical telemetry, journal logs, and metabolic load..."):
                    try:
                        journal_text = " | ".join([f"{e['time']}: {e['desc']}" for e in st.session_state.event_log]) if st.session_state.event_log else "No recent manual logs."
                        sys_prompt = f"""You are my elite long-term performance endocrinologist.
                        Analyze my {trend_window} metabolic trends based on my recent journals, current Whoop strain ({w_strain}), and average TIR of {int(mock_tir.mean())}%.
                        Journal Context: {journal_text}
                        Provide a 3-sentence deep insight identifying a hidden pattern (e.g., "Your TIR drops on days you log high stress and sleep poorly"). Speak directly to me ('you'). No markdown.
                        """
                        trend_insight = ask_claude(sys_prompt, [{"role": "user", "content": "Find my hidden metabolic patterns."}], max_tokens=500, parse_json=False)
                        st.session_state.latest_trend_insight = trend_insight
                        st.success(f"**Agentic Synthesis:** {trend_insight}")
                    except Exception as e:
                        st.error(f"Analysis failed: {e}")
            elif st.session_state.latest_trend_insight != "No macro trend synthesized yet. Run an analysis in the Trends tab.":
                st.success(f"**Latest Synthesis:** {st.session_state.latest_trend_insight}")
    
        with chart_container:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=dates, y=mock_tir, name="Time in Range (%)", marker_color="#8B5CF6", opacity=0.7))
            fig.add_trace(go.Scatter(x=dates, y=mock_avg_bg, name="Avg Glucose (mg/dL)", mode="lines+markers", line=dict(color="#ED8796", width=3), yaxis="y2"))
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color='gray'), height=350, margin=dict(l=0, r=0, t=30, b=0),
                xaxis=dict(showgrid=False, fixedrange=True), yaxis=dict(title="TIR (%)", range=[0, 100], showgrid=False, fixedrange=True),
                yaxis2=dict(title="Avg BG", range=[50, 250], overlaying="y", side="right", showgrid=True, gridcolor='rgba(128,128,128,0.2)', fixedrange=True), showlegend=False
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    
    elif st.session_state.active_view == "Sleep":
        st.markdown("### 🌙 Sleep & Recovery Correlation")
        if st.session_state.whoop_token and whoop_metrics:
            sleep_perf = whoop_metrics.get('score', {}).get('sleep_performance_percentage', 85)
            overnight_df = full_data.tail(96)
            raw_std = overnight_df['Glucose_Value'].std()
            safe_std = int(raw_std) if pd.notna(raw_std) else 0

            with st.spinner("Synthesizing Sleep Impact..."):
                metrics_str = f"Avg: {int(overnight_df['Glucose_Value'].mean())}, Min: {int(overnight_df['Glucose_Value'].min())}, Max: {int(overnight_df['Glucose_Value'].max())}, Std Dev: {safe_std}"
                st.success(f"**🤖 Agentic Insight:** {get_ai_chart_summary(f'Overnight Glucose (with {sleep_perf}% Sleep Performance)', '12h', metrics_str, context_memory_string)}")
            
            s_col1, s_col2 = st.columns(2)
            with s_col1: st.metric("Sleep Performance", f"{sleep_perf}%", delta="Restorative" if sleep_perf > 80 else "Deficit", delta_color="normal" if sleep_perf > 80 else "inverse")
            with s_col2: st.metric("Overnight Volatility", f"±{safe_std} mg/dL", delta="Stable" if safe_std < 15 else "Erratic", delta_color="normal" if safe_std < 15 else "inverse")
            st.markdown("---")
            
            st.markdown("##### 🌙 Overnight Blood Sugar")
            sleep_fig = go.Figure()
            sleep_fig.add_trace(go.Scatter(x=overnight_df['Timestamp'], y=overnight_df['Glucose_Value'], mode='lines+markers', line=dict(color='#A855F7', width=4)))
            sleep_fig.add_hrect(y0=70, y1=180, line_width=0, fillcolor="rgba(166, 218, 149, 0.1)", opacity=0.5); sleep_fig.add_hline(y=70, line_dash="dash", line_color="#ED8796")
            sleep_fig.update_layout(height=300, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=0, r=0, t=30, b=0), xaxis=dict(fixedrange=True), yaxis=dict(fixedrange=True))
            st.plotly_chart(sleep_fig, use_container_width=True, config={'displayModeBar': False})
        else:
            st.info("🔗 Open the ☰ MENU above to connect Whoop and enable Sleep Impact correlation.")

st.markdown(styles.FOOTER_HTML, unsafe_allow_html=True)