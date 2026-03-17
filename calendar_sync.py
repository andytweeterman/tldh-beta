import re
from datetime import datetime

def analyze_local_calendar(ics_string):
    """
    Parses a local .ics file string to count today's meetings and detect high-stress contexts.
    This acts as our web-prototype stand-in for native Apple EventKit / Android CalendarContract.
    """
    if not ics_string:
        return 0, False
        
    # Get today's date in the standard ICS format (YYYYMMDD)
    today_str = datetime.now().strftime("%Y%m%d")
    events = ics_string.split("BEGIN:VEVENT")
    
    meeting_count = 0
    speaker_mode = False
    
    # High-stress / High-cognitive-load triggers
    stress_keywords = r'(present|speak|panel|pitch|board meeting|interview|keynote)'
    
    for event in events[1:]: # Skip the calendar header
        # Check if the event occurs today
        if today_str in event:
            meeting_count += 1
            
            # Scan the event block for high-load keywords
            if re.search(stress_keywords, event, re.IGNORECASE):
                speaker_mode = True
                
    return meeting_count, speaker_mode

def fetch_calendar_context():
    """
    Fallback mock function if no local device ICS is provided.
    Returns: meeting_count, speaker_mode
    """
    return 3, False