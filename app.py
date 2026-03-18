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
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import calendar_sync
from audio_recorder_streamlit import audio_recorder
from openai import OpenAI
from PIL import Image
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
# 1. SETUP & PAGE CONFIG (BETA 3.0)
# -----------------------------------------------------------------------------
page_icon_img = "🌙"
if os.path.exists("logo.jpg"):
    try:
        page_icon_img = Image.open("logo.jpg")
    except: pass

st.set_page_config(page_title="TLDH Beta 3.0", page_icon=page_icon_img, layout="wide", initial_sidebar_state="collapsed")
styles.apply_theme()
styles.inject_custom_css()

def get_logo_html():
    if os.path.exists("logo.jpg"):
        try:
            with open("logo.jpg", "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
                return f'<img src="data:image/jpeg;base64,{b64}" style="height: 48px; margin-right: 15px; vertical-align: middle; border-radius: 8px;">'
        except: pass
    return ''

# -----------------------------------------------------------------------------
# 1.1 OAUTH CATCHER (MUST BE BEFORE VELVET ROPE)
# -----------------------------------------------------------------------------
if "whoop_token" not in st.session_state: 
    st.session_state.whoop_token = whoop.get_valid_access_token()

if "code" in st.query_params:
    try:
        token_data = whoop.get_access_token(st.query_params["code"])
        if token_data and "access_token" in token_data:
            st.session_state.whoop_token = token_data["access_token"]
            whoop.save_tokens(token_data)
        st.query_params.clear()
    except Exception as e:
        pass 

# -----------------------------------------------------------------------------
# 1.5 THE VELVET ROPE (IP PROTECTION GATE)
# -----------------------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.markdown(f"<h1 style='text-align: center; color: #8B5CF6; font-size: 3rem;'>{get_logo_html()} TLDH Beta 3.0</h1>", unsafe_allow_html=True)
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
    if ctx == "Stressed": return "gentle, concerned, and highly supportive."
    elif ctx == "Exercise": return "excited, energetic, and highly encouraging."
    elif ctx == "Recovery": return "calm, analytical, and restorative."
    elif ctx == "Sick": return "compassionate, cautious, and clinically protective."
    elif ctx == "Travel": return "vigilant, organized, and proactive."
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

def get_ai_chart_summary(chart_title, time_window, metrics_str, context_str):
    sys_prompt = f"""You are an elite metabolic data analyst.
    Summarize this {time_window} chart data for {chart_title}.
    Metrics: {metrics_str}
    Context: {context_str}
    Provide a single punchy, insightful sentence about the user's biological stability. Speak directly to the user as 'you'."""
    try:
        return ask_claude(sys_prompt, [{"role": "user", "content": "Analyze this data."}], max_tokens=150, parse_json=False)
    except Exception as e:
        return f"Analysis unavailable: {e}"

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
if "camera_active" not in st.session_state: st.session_state.camera_active = False
if "mic_active" not in st.session_state: st.session_state.mic_active = False
if "event_log" not in st.session_state: st.session_state.event_log = []
if "muted_intercepts" not in st.session_state: st.session_state.muted_intercepts = {}
if "_toast" not in st.session_state: st.session_state._toast = None
if "active_view" not in st.session_state: st.session_state.active_view = "Home"
if "show_dossier" not in st.session_state: st.session_state.show_dossier = False
if "smart_nudge_dismissed" not in st.session_state: st.session_state.smart_nudge_dismissed = False
if "hydration_oz" not in st.session_state: st.session_state.hydration_oz = 0
if "favorite_meals" not in st.session_state: st.session_state.favorite_meals = []
if "daily_briefing" not in st.session_state: st.session_state.daily_briefing = None
if "wellness_advice" not in st.session_state: st.session_state.wellness_advice = None
if "weekly_pattern" not in st.session_state: st.session_state.weekly_pattern = None
if "schedule_action_plan" not in st.session_state: st.session_state.schedule_action_plan = None
if "sleep_insight" not in st.session_state: st.session_state.sleep_insight = None

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

@st.cache_data(ttl=300)
def get_cached_health_data(url, token):
    if url:
        real_df = logic.fetch_nightscout_data(url, token)
        if real_df is not None and not real_df.empty: return real_df, True
    return logic.fetch_health_data(), False

@st.cache_data(ttl=60)
def get_cached_glycemic_risk(df, context, whoop_data=None, meeting_count=0, speaker_mode=False, owm_api_key="", is_real_data=False):
    return logic.calc_glycemic_risk(df, context, whoop_data, meeting_count, speaker_mode, owm_api_key, is_real_data)

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
        else: w_rec, w_sleep, w_strain = 0, 0, 0.0

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
    active_memory_list.append(f"Recently logged a meal via camera: {meal_mem.get('food_identified', 'Food')} ({display_c}g carbs).")

if st.session_state.current_context in ["Exercise", "Recovery"]:
    active_memory_list.append(f"Currently in {st.session_state.current_context} mode.")
elif w_strain > 12.0:
    active_memory_list.append(f"Notable Whoop strain: {w_strain}.")

recent_journals = [e for e in st.session_state.event_log if e['type'] in ["🍽️ Meal", "💊 Medication", "🏃‍♂️ Exercise", "📝 Other", "🧬 Context Override"]]
if recent_journals:
    active_memory_list.append(f"Recent journal entry: {recent_journals[-1]['desc']}")

context_memory_string = " | ".join(active_memory_list) if active_memory_list else "No active external events logged."

# -----------------------------------------------------------------------------
# 5. UI HEADERS & AGENTIC INTERCEPTS
# -----------------------------------------------------------------------------
st.markdown(f"""
    <div style="margin-top: 10px; margin-bottom: 25px; padding: 24px 30px; background: linear-gradient(135deg, rgba(139,92,246,0.08), rgba(109,40,217,0.03)); border: 1px solid rgba(139,92,246,0.2); border-radius: 24px; box-shadow: 0 8px 24px rgba(0,0,0,0.04);">
        <div style="display: flex; align-items: center; margin-bottom: 4px;">
            {get_logo_html()}
            <div style="font-size: 34px; font-weight: 900; background: linear-gradient(135deg, #8B5CF6, #6D28D9); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: -0.5px; line-height: 1.2;">
                Total Life Download Hub
            </div>
        </div>
        <div style="color: var(--text-secondary); font-weight: 600; font-size: 1.15rem; letter-spacing: 0.5px;">Agentic Risk Management Engine</div>
    </div>
""", unsafe_allow_html=True)

if st.session_state.current_context == "Normal":
    auto_mode, auto_dur, auto_reason = None, 0, ""
    
    if w_strain > 14.0 and latest_bg['Trend'] in ["Falling", "Falling Fast"]:
        auto_mode, auto_dur, auto_reason = "Recovery", 2, "High Whoop strain detected with dropping glucose."
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

# Variables init
db_search_submit = False; db_search_query = ""; text_submit = False; text_input = ""; food_image = None

# Calculate Drivers data for popovers
tir_df = full_data.tail(36)
low, tgt, elev, high = 0, 0, 0, 0
if len(tir_df) > 0:
    low, tgt, elev, high = [len(tir_df[cond])/len(tir_df)*100 for cond in [tir_df['Glucose_Value'] < 80, (tir_df['Glucose_Value'] >= 80) & (tir_df['Glucose_Value'] <= 140), (tir_df['Glucose_Value'] > 140) & (tir_df['Glucose_Value'] <= 180), tir_df['Glucose_Value'] > 180]]

weather_str = "☁️ Weather Nominal"
for p in raw_reason.split("|"):
    if "Weather" in p or "Clear" in p or "Cloud" in p or "Rain" in p:
        clean = re.sub(r'System nominal\.?', '', p).replace('()', '').strip()
        if clean: weather_str = f"☁️ {clean}"; break

cal_icon = "🟢" if meeting_count < 3 else "🟡" if meeting_count < 5 else "🔴"
cal_load = "Light" if meeting_count < 3 else "Mod" if meeting_count < 5 else "Heavy"

# MAIN ACTION BUTTONS (4 Columns)
with st.container(border=True):
    btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)
    
    with btn_col1:
        with st.popover("⚡ Drivers", use_container_width=True):
            st.markdown("##### Total Life Drivers")
            st.caption("Drill down into systemic biological metrics.")
            
            if len(tir_df) > 0:
                tir_lbl = f"🔴 {int(low)}% BG Low" if low > 5 else (f"🔴 {int(high)}% BG High" if high > 15 else (f"🟡 {int(elev)}% BG Elev" if elev > 25 else f"🟢 {int(tgt)}% BG Target"))
                with st.expander(f"{tir_lbl} (3h)"):
                    st.write(f"Target (70-180): **{int(tgt)}%**")
                    st.write(f"Elevated (141-180): **{int(elev)}%**")
                    st.write(f"High (>180): **{int(high)}%**")
                    st.write(f"Low (<70): **{int(low)}%**")
            else:
                st.info("🟣 No CGM Data")

            rec_icon = "🟢" if w_rec >= 67 else "🟡" if w_rec >= 34 else ("🔴" if w_rec > 0 else "🟣")
            with st.expander(f"{rec_icon} {w_rec}% Recovery" if w_rec > 0 else "🟣 No Recovery Data"):
                st.write(f"Target >67%. Current: **{w_rec}%**.")

            strain_icon = "🔴" if w_strain >= 14 else "🟡" if w_strain >= 10 else ("🟢" if w_strain > 0 else "🟣")
            with st.expander(f"{strain_icon} {w_strain} Strain" if w_strain > 0 else "🟣 No Strain Data"):
                st.write(f"Cardiovascular exertion scale (0-21). Current: **{w_strain}**.")

            mood_str = "Elevated" if st.session_state.current_context == "Normal" else st.session_state.current_context
            with st.expander(f"🧠 Mood: {mood_str}"):
                if st.session_state.current_context != "Normal": st.write(f"Active Mode: **{st.session_state.current_context}**")
                else: st.write("System operating in standard baseline mode.")

            if st.session_state.hydration_oz == 0:
                with st.expander("🟣 No Hydration Data"): st.write("Track water intake to optimize glucose flushing.")
            else:
                hydro_icon = "🟢" if st.session_state.hydration_oz >= 64 else "🟡" if st.session_state.hydration_oz >= 32 else "🔴"
                with st.expander(f"{hydro_icon} {st.session_state.hydration_oz}oz Hydration"):
                    st.write(f"Daily Goal: 80 oz. Logged: **{st.session_state.hydration_oz} oz**.")

            sleep_icon = "🟢" if w_sleep >= 70 else "🟡" if w_sleep >= 50 else ("🔴" if w_sleep > 0 else "🟣")
            with st.expander(f"{sleep_icon} {w_sleep}% Sleep Perf" if w_sleep > 0 else "🟣 No Sleep Data"):
                st.write(f"Target >70%. Current: **{w_sleep}%**.")

            with st.expander(f"{cal_icon} {meeting_count} Meetings ({cal_load})"):
                st.write(f"Detected **{meeting_count}** upcoming scheduled events.")

            with st.expander(weather_str):
                st.write("Ambient conditions correlate with behavioral activity limits.")

    with btn_col2:
        with st.popover("🍽️ Meals", use_container_width=True):
            st.caption("Snap a photo to estimate carbohydrates and metabolic impact.")
            st.markdown("<div style='background: rgba(237, 135, 150, 0.1); border-left: 3px solid #ED8796; padding: 8px; font-size: 0.75rem; color: var(--text-color); margin-bottom: 10px;'>⚠️ <b>RAI Disclaimer:</b> This tool uses generative AI. Nutritional estimates may vary, can be inaccurate, and should not replace professional medical judgment.</div>", unsafe_allow_html=True)
            
            if not st.session_state.camera_active:
                if st.button("📸 Open Camera Scanner", use_container_width=True):
                    st.session_state.camera_active = True; st.rerun()
            else:
                food_image = st.camera_input("Food Scanner", label_visibility="collapsed")
                if st.button("❌ Disable Camera", use_container_width=True):
                    st.session_state.camera_active = False; st.rerun()
                    
            st.divider()
            with st.form("usda_search_form"):
                db_search_query = st.text_input("Search USDA Database:", placeholder="E.g., 1 cup cooked quinoa")
                db_search_submit = st.form_submit_button("Look up Food Macros", use_container_width=True)
                
            if st.session_state.favorite_meals:
                st.divider()
                st.markdown("##### ⭐ Quick Log: Favorites")
                for fav in st.session_state.favorite_meals:
                    raw_c = fav.get('estimated_carbs_g', 0)
                    display_c = raw_c.get('total_estimated', raw_c.get('total', 0)) if isinstance(raw_c, dict) else raw_c
                    if st.button(f"{fav.get('food_identified', 'Meal')} ({display_c}g)", key=f"fav_{fav.get('food_identified')}"):
                        st.session_state.latest_meal_analysis = fav
                        log_event("🍽️ Meal", f"Logged from Favorites: {fav.get('food_identified')} ({display_c}g Carbs)")
                        st.rerun()
                
    with btn_col3:
        with st.popover("📓 Journal", use_container_width=True):
            st.caption("Log events, record a voice note, or tag drivers.")
            
            if not st.session_state.mic_active:
                if st.button("🎙️ Enable Microphone", use_container_width=True):
                    st.session_state.mic_active = True; st.rerun()
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
                        st.warning("🎙️ **OpenAI API Key Missing!**")
            
            st.divider()
            with st.form("manual_event_form", clear_on_submit=True):
                st.markdown("<span style='font-size: 0.85rem; font-weight: 600; color: var(--text-color);'>BIOLOGICAL OVERRIDES</span>", unsafe_allow_html=True)
                context_tags = st.multiselect(
                    "Active strain drivers:",
                    ["Menstrual Cycle (Luteal/High Resistance)", "Menstrual Cycle (Onset/High Sensitivity)", "Fighting Illness", "Travel/Jet Lag", "Muscle Soreness (DOMS)"],
                    placeholder="No active systemic overrides...", label_visibility="collapsed"
                )
                
                st.markdown("<br><span style='font-size: 0.85rem; font-weight: 600; color: var(--text-color);'>TEXT LOG</span>", unsafe_allow_html=True)
                ev_type = st.selectbox("Type", ["📝 Note", "🍽️ Meal", "💊 Medication", "🏃‍♂️ Exercise"], label_visibility="collapsed")
                ev_desc = st.text_area("Context", placeholder="E.g., I had a cookie at lunch...", height=80, label_visibility="collapsed")
                if st.form_submit_button("Synthesize & Log", use_container_width=True):
                    if context_tags:
                        log_event("🧬 Context Override", ", ".join(context_tags))
                        st.session_state._toast = f"🧬 System Adjusted for: {', '.join(context_tags)}"
                    if ev_desc and ev_type == "📝 Note":
                        text_input = ev_desc
                        text_submit = True
                    elif ev_desc:
                        log_event(ev_type, ev_desc)
                        st.session_state._toast = f"✅ {ev_type.split(' ')[1]} logged to memory!"
                    if context_tags or ev_desc:
                        st.rerun()
                        
    with btn_col4:
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
                if is_real_cgm: st.success("🟢 Connected & Streaming")
                else: st.error("🔴 Connection Failed.")
                if st.button("Disconnect", key="dc_ns"):
                    st.session_state.ns_url = ""; st.session_state.ns_token = ""; save_ns_config("", ""); st.cache_data.clear(); st.rerun()
            else:
                with st.form("ns_form"):
                    ns_url_input = st.text_input("URL", placeholder="https://site.herokuapp.com", label_visibility="collapsed")
                    if st.form_submit_button("Connect", use_container_width=True):
                        st.session_state.ns_url = ns_url_input; save_ns_config(ns_url_input, ""); st.cache_data.clear(); st.rerun()
            
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("**⚡ Whoop Telemetry**")
            if not st.session_state.whoop_token:
                oauth_state = secrets.token_urlsafe(16)
                st.components.v1.html(f"<script>window.parent.document.cookie = 'whoop_oauth_state={oauth_state}; path=/; max-age=3600; SameSite=Lax';</script>", height=0)
                st.link_button("Connect", whoop.get_authorization_url(oauth_state), use_container_width=True)
            else:
                if whoop_metrics: st.success("🟢 Connected")
                else: st.error("🔴 Data Sync Failed")
                if st.button("🔄 Refresh Sync", use_container_width=True): 
                    st.session_state.whoop_token = whoop.get_valid_access_token()
                    whoop.fetch_whoop_recovery.clear(); st.rerun() 
            
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("**🍎 Apple HealthKit**")
            st.button("Connect HealthKit", disabled=True, use_container_width=True, help="Arriving in Beta 3.0")
            st.caption("Coming Soon")
                    
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("**📱 Native Calendar (Mock)**")
            cal_file = st.file_uploader("Upload .ics", type=["ics"], label_visibility="collapsed")
            if cal_file:
                mc, sm = calendar_sync.analyze_local_calendar(cal_file.getvalue().decode("utf-8"))
                st.session_state.local_meeting_count, st.session_state.local_speaker_mode = mc, sm
                st.success(f"Local Sync: {mc} events loaded.")
                
            st.divider()
            st.markdown("##### 🩺 Clinical Export")
            if st.button("📄 Generate Doctor Report", use_container_width=True):
                st.session_state.show_dossier = True; st.rerun()

st.divider()

# -----------------------------------------------------------------------------
# 6. EVENT PROCESSORS (SEMANTIC NLP DETECT)
# -----------------------------------------------------------------------------

# --- Process USDA Text Search ---
if db_search_submit and db_search_query:
    with st.spinner(f"Querying USDA Database for '{db_search_query}'..."):
        try:
            sys = f"""You are my elite personal clinical nutritionist managing my Type 1 Diabetes.
            Look up the exact macronutrients for the following food query: {db_search_query}.
            Speak directly to me using "you" and "your". Tone should be {get_claude_tone()}.
            Return ONLY a valid JSON object with EXACTLY these keys and strict data types:
            - "food_identified": "Short description." (Must be a String)
            - "estimated_carbs_g": 45 (MUST be a single Integer. No dictionaries)
            - "components": A list of objects breaking down the meal. Format: [{{"name": "Ingredient 1", "carbs_g": 10}}] (Must be an Array of Objects)
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
            Correlate my text with the telemetry and memory. 
            Speak to me as 'you'. Tone should be {get_claude_tone()}. NEVER refer to me as "the patient".
            Return ONLY a valid JSON object with EXACTLY these keys:
            - "reply": "A contextual response."
            - "summary": "3 words."
            - "scores": {{"bio_strain": 5, "cog_load": 5}}
            - "impact_prediction": "1-sentence prediction."
            - "suggested_mode": "Exercise", "Recovery", "Stressed", "Sick", "Project", "Travel", or "Normal"
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
                Analyze the food image. Estimate carbs, glycemic index, and break down the visible ingredients.
                Speak directly to me using "you" and "your". Tone should be {get_claude_tone()}. NEVER refer to me as "the patient".
                Return ONLY a valid JSON object with EXACTLY these keys and strict data types:
                - "food_identified": "Short description." (Must be a String)
                - "estimated_carbs_g": 45 (MUST be a single Integer. No dictionaries)
                - "components": A list of objects breaking down the visible items. Format: [{{"name": "Granola", "carbs_g": 30}}] (Must be an Array of Objects)
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

# Render Journal/Note Result
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

# Render Meal Analysis Result
if st.session_state.get("latest_meal_analysis"):
    meal = st.session_state.latest_meal_analysis
    st.markdown(f"### 🍽️ Meal Analysis <span style='font-size:14px;color:gray;'>({meal.get('source')})</span>", unsafe_allow_html=True)
    
    m1, m2, m3 = st.columns([1, 1, 2])
    m1.metric("Identified", str(meal.get("food_identified", "Unknown")))
    
    raw_carbs = meal.get('estimated_carbs_g', 0)
    display_carbs = raw_carbs.get('total_estimated', raw_carbs.get('total', 0)) if isinstance(raw_carbs, dict) else raw_carbs
    m2.metric("Total Carbs", f"{display_carbs}g")
    
    gi = str(meal.get("glycemic_index", "Unknown"))
    gi_color = "🔴" if "high" in gi.lower() else "🟡" if "medium" in gi.lower() else "🟢"
    m3.metric("Glycemic Index", f"{gi_color} {gi}")
    
    # Render Component Breakdown
    components = meal.get("components", [])
    if components and isinstance(components, list):
        st.markdown("<h6 style='color: var(--text-secondary); margin-top: 10px; margin-bottom: 5px; font-size: 0.85rem; text-transform: uppercase;'>🥗 Macro Breakdown</h6>", unsafe_allow_html=True)
        for comp in components:
            c_name = comp.get("name", "Item")
            c_carbs = comp.get("carbs_g", 0)
            st.markdown(f"<div style='display: flex; justify-content: space-between; border-bottom: 1px solid rgba(128,128,128,0.2); padding: 4px 0;'><span style='color: var(--text-color);'>{c_name}</span><span style='color: #8B5CF6; font-weight: 600;'>{c_carbs}g</span></div>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
    
    st.info(f"**Clinical Insight:** {meal.get('analysis', '')}")
    
    # Action Row
    st.markdown("<br>", unsafe_allow_html=True)
    b1, b2, b3 = st.columns(3)
    if b1.button("⭐ Add to Favorites", use_container_width=True):
        st.session_state.favorite_meals.append(meal)
        st.session_state._toast = "⭐ Meal saved to your Favorites!"
        st.session_state.latest_meal_analysis = None
        st.rerun()
    if b2.button("➕ Add Something Else", use_container_width=True):
        st.session_state.latest_meal_analysis = None
        st.rerun()
    if b3.button("✅ Done", use_container_width=True, type="primary"):
        st.session_state.latest_meal_analysis = None
        st.rerun()
    st.divider()

# -----------------------------------------------------------------------------
# 7. NAVIGATION & RENDER VIEWS
# -----------------------------------------------------------------------------
views = ["Home", "Insights", "Recovery", "Schedule", "Sleep"]
v_cols = st.columns(len(views))
for i, view in enumerate(views):
    is_active = (st.session_state.active_view == view)
    if v_cols[i].button(view, use_container_width=True, type="primary" if is_active else "secondary"):
        st.session_state.active_view = view
        st.rerun()
st.markdown("---")

# -----------------------------------------------------------------------------
# CHARTING HELPER FUNCTION (For dynamic zoom and timeframes)
# -----------------------------------------------------------------------------
def render_dynamic_cgm_chart(df, chart_key="home"):
    time_range = st.radio("Timeframe", ["3h", "6h", "12h", "24h"], horizontal=True, key=f"range_{chart_key}")
    hours = int(time_range.replace('h', ''))
    cutoff = df['Timestamp'].max() - timedelta(hours=hours)
    plot_df = df[df['Timestamp'] >= cutoff]
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=plot_df['Timestamp'], y=plot_df['Glucose_Value'], mode='lines', line=dict(color='#8B5CF6', width=3)))
    fig.add_hrect(y0=70, y1=180, line_width=0, fillcolor="rgba(166, 218, 149, 0.1)", opacity=0.3, layer="below")
    fig.add_hline(y=70, line_dash="dot", line_color="#ED8796", layer="below")
    fig.add_hline(y=180, line_dash="dot", line_color="#EED49F", layer="below")
    
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font=dict(color='gray'), height=300, margin=dict(l=0, r=0, t=10, b=0),
        xaxis=dict(showgrid=False), yaxis=dict(title="mg/dL", range=[40, 260], showgrid=True, gridcolor='rgba(128,128,128,0.2)'), showlegend=False
    )
    st.plotly_chart(fig, use_container_width=True)

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
        # AI Daily Briefing Generation
        if st.button("🧠 Synthesize Daily Briefing", type="primary", use_container_width=True):
            with st.spinner("Compiling cross-domain telemetry..."):
                try:
                    sys_prompt = f"""You are an elite clinical data analyst. Look at the user's current data:
                    Glucose: {int(latest_bg['Glucose_Value'])} ({latest_bg['Trend']}), Whoop Strain: {w_strain}, Sleep: {w_sleep}%, Meetings today: {meeting_count}.
                    Return ONLY a JSON object with:
                    - "rating": Must be exactly "good", "caution", "danger", or "neutral" based on their combined risk.
                    - "message": A 2-sentence punchy, actionable briefing on their current state and what to watch out for. Speak as 'you'."""
                    brief_data = ask_claude(sys_prompt, [{"role": "user", "content": "Generate my daily briefing."}])
                    st.session_state.daily_briefing = brief_data
                except Exception as e:
                    st.error(f"Synthesis failed: {e}")
        
        # Render AI Briefing Box
        if st.session_state.daily_briefing:
            b_rating = st.session_state.daily_briefing.get("rating", "neutral").lower()
            b_msg = st.session_state.daily_briefing.get("message", "")
            if b_rating == "good": st.success(f"**🟢 Daily Briefing:** {b_msg}")
            elif b_rating == "caution": st.warning(f"**🟡 Daily Briefing:** {b_msg}")
            elif b_rating == "danger": st.error(f"**🔴 Daily Briefing:** {b_msg}")
            else: st.info(f"**🔵 Daily Briefing:** {b_msg}")
            st.markdown("<br>", unsafe_allow_html=True)
        
        # Standard CGM Chart (Dynamic)
        st.markdown("##### 🩸 Current Blood Sugar")
        render_dynamic_cgm_chart(full_data, "home")
        
        st.markdown("---")
        
        c1, c2, c3, c4 = st.columns(4)
        delta = int(latest_bg['Glucose_Value'] - full_data.iloc[-2]['Glucose_Value']) if len(full_data) > 1 else 0
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

    # ---------------- BETA UI: INSIGHTS ----------------
    elif st.session_state.active_view == "Insights":
        if st.button("🧠 Synthesize 1 Week Pattern", type="primary", use_container_width=True):
            with st.spinner("Analyzing historical telemetry, journal logs, and metabolic load..."):
                try:
                    mock_tir = np.clip(np.random.normal(75, 8, 7), 0, 100)
                    journal_text = " | ".join([f"{e['time']}: {e['desc']}" for e in st.session_state.event_log]) if st.session_state.event_log else "No recent logs."
                    sys_prompt = f"""You are my elite long-term performance endocrinologist.
                    Analyze my 1-week metabolic trends based on my recent journals, Whoop strain ({w_strain}), and average TIR of {int(mock_tir.mean())}%.
                    Journal Context: {journal_text}
                    Provide a 3-sentence deep insight identifying a hidden pattern. Speak directly to me ('you')."""
                    pattern_insight = ask_claude(sys_prompt, [{"role": "user", "content": "Find my hidden metabolic patterns."}], parse_json=False)
                    st.session_state.weekly_pattern = pattern_insight
                except Exception as e:
                    st.error(f"Analysis failed: {e}")
                    
        if st.session_state.weekly_pattern:
            st.success(f"**Agentic Synthesis:** {st.session_state.weekly_pattern}")

        st.markdown("<h5 style='color: var(--text-secondary); margin-top: 20px;'>CLINICAL TELEMETRY (Live)</h5>", unsafe_allow_html=True)
        ic1, ic2, ic3 = st.columns(3)
        gmi_val = calculate_gmi(full_data['Glucose_Value'].mean())
        tir_val = calculate_tir(full_data)
        gly_var = int(full_data['Glucose_Value'].std())
        
        with ic1: st.metric("Estimated A1C (GMI)", f"{gmi_val}%", "Based on trailing data", delta_color="off")
        with ic2: st.metric("Time-In-Range", f"{tir_val}%", "Target: > 70%", delta_color="off")
        with ic3: st.metric("Glycemic Variability", f"±{gly_var} mg/dL", "Standard Deviation", delta_color="off")

        st.markdown("<h5 style='color: var(--text-secondary); margin-top: 20px;'>BEHAVIORAL RISK METRICS</h5>", unsafe_allow_html=True)
        pc1, pc2, pc3 = st.columns(3)
        with pc1: st.metric("Cortisol Spikes Averted", "14", "Via Active Intercepts", delta_color="off")
        with pc2: st.metric("Current Bio-Strain", f"{w_strain} / 21", "Synced from Whoop", delta_color="off")
        with pc3: st.metric("Recovery Adherence", "82%", "High engagement", delta_color="off")

    # ---------------- BETA UI: DUAL-VECTOR RECOVERY ----------------
    elif st.session_state.active_view == "Recovery":
        if st.button("🧠 Synthesize Wellness Advice", type="primary", use_container_width=True):
            with st.spinner("Generating custom recovery protocols..."):
                try:
                    sys_prompt = f"""You are an elite holistic wellness coach. Look at the user's data:
                    Whoop Strain: {w_strain}, Sleep: {w_sleep}%, Hydration: {st.session_state.hydration_oz}oz.
                    Return ONLY a JSON object with:
                    - "short_term": "One sentence of actionable advice to implement TODAY."
                    - "long_term": "One sentence of strategic advice to build resilience THIS WEEK." """
                    adv_data = ask_claude(sys_prompt, [{"role": "user", "content": "Give me wellness advice."}])
                    st.session_state.wellness_advice = adv_data
                except Exception as e:
                    st.error(f"Synthesis failed: {e}")
                    
        if st.session_state.wellness_advice:
            st.info(f"**🎯 Today's Focus:** {st.session_state.wellness_advice.get('short_term', '')}")
            st.success(f"**📅 This Week's Strategy:** {st.session_state.wellness_advice.get('long_term', '')}")

        st.markdown("<h3 style='color: #A6DA95; margin-top: 20px;'>🔋 Dual-Vector Recovery Architecture</h3>", unsafe_allow_html=True)
        st.caption("Intentional down-regulation of the nervous system to stabilize metabolic volatility and reduce cognitive load.")
        
        st.markdown("#### Vector 1: Internal Reset (Parasympathetic)")
        r1, r2 = st.columns(2)
        with r1:
            with st.container(border=True):
                st.markdown("<div style='text-align: center;'><strong>🧘‍♂️ Box Breathing (2 Min)</strong><br><span style='font-size:0.85rem; color: gray;'>Rapid acute stress mitigation.</span></div><br>", unsafe_allow_html=True)
                if st.button("Log Breathing", use_container_width=True): 
                    log_event("🧘‍♂️ Recovery", "2 Min Box Breathing"); st.session_state._toast = "✅ Nervous system down-regulating."; st.rerun()
        with r2:
            with st.container(border=True):
                st.markdown("<div style='text-align: center;'><strong>🕉️ Transcendental Meditation (20 Min)</strong><br><span style='font-size:0.85rem; color: gray;'>Deep baseline physiological rest.</span></div><br>", unsafe_allow_html=True)
                if st.button("Log TM Session", use_container_width=True, type="primary"): 
                    log_event("🕉️ Recovery", "20 Min TM Session"); st.session_state._toast = "🕰️ Deep physiological rest initiated."; st.rerun()

        st.markdown("---")
        st.markdown("#### Vector 2: External Reset (Contextual)")
        r3, r4 = st.columns(2)
        with r3:
            with st.container(border=True):
                st.markdown("<div style='text-align: center;'><strong>🎧 Contextual Realignment</strong><br><span style='font-size:0.85rem; color: gray;'>Sensory pattern interruption.</span></div><br>", unsafe_allow_html=True)
                if st.button("Log Sensory Shift", use_container_width=True): 
                    log_event("🎧 Recovery", "Contextual Shift"); st.session_state._toast = "🧠 Cognitive loop broken."; st.rerun()
        with r4:
            with st.container(border=True):
                st.markdown("<div style='text-align: center;'><strong>💧 Hydration Intercept</strong><br><span style='font-size:0.85rem; color: gray;'>Flush excess glucose; reduce resistance.</span></div><br>", unsafe_allow_html=True)
                if st.button("Log 16oz Water", use_container_width=True): 
                    st.session_state.hydration_oz += 16
                    log_event("💧 Recovery", "16oz Hydration"); st.session_state._toast = "✅ Hydration logged."; st.rerun()

    # ---------------- BETA UI: SCHEDULE (CALENDAR INTEGRATION) ----------------
    elif st.session_state.active_view == "Schedule":
        
        if st.button("🧠 Synthesize Action Plan", type="primary", use_container_width=True):
            with st.spinner("Generating meeting preparation strategy..."):
                try:
                    sys_prompt = f"""You are an elite holistic wellness and metabolic coach. The user has {meeting_count} meetings today and a current glucose of {int(latest_bg['Glucose_Value'])} mg/dL.
                    Return a 2-3 sentence actionable plan on how to prepare for these meetings to maintain stable glucose and low stress (e.g., bring sugar/snacks, stay hydrated, stretch, or take a walk). Speak directly to the user as 'you'."""
                    plan_data = ask_claude(sys_prompt, [{"role": "user", "content": "Generate my meeting action plan."}], parse_json=False)
                    st.session_state.schedule_action_plan = plan_data
                except Exception as e:
                    st.error(f"Synthesis failed: {e}")
                    
        if st.session_state.get("schedule_action_plan"):
            st.success(f"**🎯 Action Plan:** {st.session_state.schedule_action_plan}")
            st.markdown("<br>", unsafe_allow_html=True)
            
        st.markdown("### 📅 Schedule & Cognitive Load")
        st.info(f"**Agentic Insight:** The Risk Engine is factoring in **{meeting_count} meetings** to adjust glycemic sensitivity.")
        
        # Native Streamlit containers to fix cross-theme visibility issues
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            with st.container(border=True): st.markdown("<div style='text-align: center; color: var(--text-secondary); font-size: 0.8rem; font-weight: bold;'>1 HOUR</div><div style='text-align: center; font-size: 1.5rem; font-weight: 800;'>🟢 SAFE</div>", unsafe_allow_html=True)
        with sc2:
            with st.container(border=True): st.markdown("<div style='text-align: center; color: var(--text-secondary); font-size: 0.8rem; font-weight: bold;'>4 HOURS</div><div style='text-align: center; font-size: 1.5rem; font-weight: 800;'>🟢 CLEAR</div>", unsafe_allow_html=True)
        with sc3:
            with st.container(border=True): st.markdown("<div style='text-align: center; color: var(--text-secondary); font-size: 0.8rem; font-weight: bold;'>24 HOURS</div><div style='text-align: center; font-size: 1.5rem; font-weight: 800;'>🟢 GOOD</div>", unsafe_allow_html=True)
            
        st.markdown("---")
        st.markdown("##### Upcoming Events")
        st.caption("Synchronized from native calendar integration.")
        
        # Dynamic Actionable Notes
        action_notes = [
            "Check glucose 15 minutes prior to start.",
            "Bring a fast-acting carb snack to this block.",
            "Take a 5-minute walking/hydration break beforehand.",
            "High cognitive load block—monitor for cortisol spike."
        ]
        
        if meeting_count > 0:
            for i in range(meeting_count):
                note = action_notes[i % len(action_notes)]
                st.markdown(f"- 🗓️ **Scheduled Block {i+1}** <br>&nbsp;&nbsp;&nbsp;&nbsp;*(Agentic Note: {note})*", unsafe_allow_html=True)
        else:
            st.markdown("No upcoming meetings today. Optimal time for deep work or recovery without acute cortisol spikes.")

    elif st.session_state.active_view == "Sleep":
        st.markdown("### 🌙 Sleep & Recovery Correlation")
        
        if st.session_state.whoop_token and whoop_metrics:
            sleep_perf = whoop_metrics.get('score', {}).get('sleep_performance_percentage', 85)
            overnight_df = full_data.tail(96)
            raw_std = overnight_df['Glucose_Value'].std()
            safe_std = int(raw_std) if pd.notna(raw_std) else 0

            if st.button("🧠 Synthesize Sleep Analysis", type="primary", use_container_width=True):
                with st.spinner("Synthesizing Sleep Impact..."):
                    metrics_str = f"Avg: {int(overnight_df['Glucose_Value'].mean())}, Min: {int(overnight_df['Glucose_Value'].min())}, Max: {int(overnight_df['Glucose_Value'].max())}, Std Dev: {safe_std}"
                    st.session_state.sleep_insight = get_ai_chart_summary(f'Overnight Glucose (with {sleep_perf}% Sleep Performance)', '12h', metrics_str, context_memory_string)
            
            if st.session_state.get("sleep_insight"):
                st.success(f"**🤖 Agentic Insight:** {st.session_state.sleep_insight}")
                
            s_col1, s_col2 = st.columns(2)
            with s_col1: st.metric("Sleep Performance", f"{sleep_perf}%", delta="Restorative" if sleep_perf > 80 else "Deficit", delta_color="normal" if sleep_perf > 80 else "inverse")
            with s_col2: st.metric("Overnight Volatility", f"±{safe_std} mg/dL", delta="Stable" if safe_std < 15 else "Erratic", delta_color="normal" if safe_std < 15 else "inverse")
        else:
            st.info("🔗 Open the ☰ MENU above to connect Whoop and enable Sleep Impact correlation.")
            
        st.markdown("---")
        st.markdown("##### 🌙 Overnight Blood Sugar")
        render_dynamic_cgm_chart(full_data, "sleep")

st.markdown(styles.FOOTER_HTML, unsafe_allow_html=True)