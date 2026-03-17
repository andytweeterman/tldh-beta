import streamlit as st
import re

FOOTER_HTML = """
<div style='text-align: center; color: var(--text-secondary); margin-top: 50px; font-size: 12px; opacity: 0.7;'>
    TLDH Core Architecture | Experimental AI. Not medical advice.<br>
    <strong>USPTO Patent Pending: Application No. 64/004,105</strong>
</div>
"""

def apply_theme():
    """Placeholder for overarching Streamlit theme configs."""
    pass

def inject_custom_css():
    """Injects all complex CSS animations, Beta UI elements, and pill styles."""
    st.markdown("""
        <style>
        /* Glowing Popover Button (2nd Column) */
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="column"]:nth-of-type(2) button {
            background: linear-gradient(135deg, #8B5CF6, #6D28D9) !important;
            color: white !important; border: none !important; border-radius: 50px !important;
            animation: pulse-purple 2s infinite !important; transition: all 0.3s ease !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="column"]:nth-of-type(2) button * {
            color: white !important; font-weight: 800 !important; letter-spacing: 0.5px !important;
        }
        @keyframes pulse-purple {
            0% { box-shadow: 0 0 0 0 rgba(139, 92, 246, 0.7); }
            70% { box-shadow: 0 0 0 15px rgba(139, 92, 246, 0); }
            100% { box-shadow: 0 0 0 0 rgba(139, 92, 246, 0); }
        }
        
        /* Total Life Driver Pills */
        .driver-pill {
            display: inline-flex; align-items: center; padding: 6px 14px; border-radius: 24px;
            font-size: 0.8rem; font-weight: 800; margin-right: 10px; margin-bottom: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1); letter-spacing: 0.3px;
            transition: transform 0.2s ease, box-shadow 0.2s ease; cursor: default;
        }
        .driver-pill:hover {
            transform: translateY(-2px); box-shadow: 0 6px 10px rgba(0,0,0,0.15);
        }

        /* --- BETA UI GLOBAL OVERRIDES --- */
        div[data-testid="stButton"] > button { border-radius: 50px !important; font-weight: 700 !important; transition: all 0.3s ease !important; letter-spacing: 0.5px !important; box-shadow: 0 4px 10px rgba(0,0,0,0.08) !important; }
        div[data-testid="stButton"] > button[kind="primary"] { background: linear-gradient(135deg, #8B5CF6, #6D28D9) !important; color: white !important; border: none !important; }
        div[data-testid="stButton"] > button[kind="primary"]:hover { box-shadow: 0 6px 15px rgba(139, 92, 246, 0.4) !important; transform: translateY(-2px); }
        div[data-testid="stButton"] > button[kind="secondary"] { border: 1px solid rgba(139, 92, 246, 0.3) !important; background-color: var(--secondary-background-color) !important; }
        div[data-testid="stButton"] > button[kind="secondary"]:hover { border-color: #8B5CF6 !important; color: #8B5CF6 !important; transform: translateY(-2px); }
        div[data-testid="stPopover"] > button { border-radius: 50px !important; font-weight: 700 !important; box-shadow: 0 4px 12px rgba(0,0,0,0.12) !important; border: 1px solid rgba(139, 92, 246, 0.2) !important; transition: all 0.3s ease !important;}
        div[data-testid="stPopover"] > button:hover { transform: translateY(-2px); box-shadow: 0 6px 15px rgba(139, 92, 246, 0.25) !important; border-color: #8B5CF6 !important; }
        @media (max-width: 768px) { .desktop-spacer { display: none !important; } }
        
        /* --- BETA UI CLASSES (Insights & Recovery) --- */
        .metric-card { background: var(--secondary-background-color); border: 1px solid rgba(255,255,255,0.05); border-radius: 16px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 15px;}
        .metric-value { font-size: 1.8rem; font-weight: 800; color: var(--text-color); line-height: 1.2; }
        .metric-label { font-size: 0.85rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; }
        .agentic-nudge { background: linear-gradient(to right, rgba(139, 92, 246, 0.15), rgba(109, 40, 217, 0.05)); border-left: 4px solid #8B5CF6; padding: 15px 20px; border-radius: 0 12px 12px 0; margin-bottom: 25px; }
        .recovery-box { text-align: center; padding: 15px; border-radius: 15px; margin: 10px 0; border: 1px solid rgba(139, 92, 246, 0.3); background: rgba(139, 92, 246, 0.05); }
        </style>
    """, unsafe_allow_html=True)

def get_driver_pill_html(t):
    """Parses a driver string and returns the styled HTML pill."""
    if "🔴" in t or "🔥" in t or "❄️" in t or "🤒" in t:
        bg, text, border = "#FFD1D9", "#8A001A", "#FFB3C1" 
    elif "🟡" in t or "⚡" in t or "💤" in t or "🧘‍♂️" in t or "🏃‍♂️" in t:
        bg, text, border = "#FFEDB3", "#805500", "#FFDF80"
    elif "🔋" in t or "RECOVERY" in t.upper() or "RESTORE" in t.upper():
        bg, text, border = "#C2E0FF", "#004085", "#99CCFF" # Recovery Blue
    elif "🟢" in t or "☁️" in t:
        bg, text, border = "#D1F4D9", "#00591A", "#A3E9B3"
    else:
        bg, text, border = "#E1D4FA", "#330099", "#C4B5F5"
    
    # Intercept specific backend flags and make them user-friendly before title casing
    friendly_text = t.replace("BENIGN ENVIRONMENT", "CLEAR WEATHER")
    friendly_text = friendly_text.replace("LOAD", "CALENDAR LOAD")
    friendly_text = friendly_text.replace("NOMINAL", "BIOMETRICS NOMINAL")
    friendly_text = friendly_text.title()
    
    # Text formatting cleanup for acronyms and timers
    friendly_text = friendly_text.replace("12H", "12h")
    friendly_text = friendly_text.replace("Bg", "BG")
    friendly_text = friendly_text.replace("Mode", "MODE")
    friendly_text = re.sub(r'(\d+)H', r'\1h', friendly_text)
    friendly_text = re.sub(r'(\d+)M', r'\1m', friendly_text)
    friendly_text = friendly_text.replace(" Left)", " left)")
    
    return f"<div class='driver-pill' style='background-color:{bg}; color:{text}; border:1px solid {border};'>{friendly_text}</div>"