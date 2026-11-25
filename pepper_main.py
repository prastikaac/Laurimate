# -*- coding: utf-8 -*-
"""
Laurimate - Campus Assistant Robot
SoftBank Pepper | NAOqi | Python 2.7

Features:
  1. Smooth VAD Listening:
     - 1.0s pre-roll ring buffer (first word never lost)
     - Adaptive noise floor (adapts to robot head fan noise)
     - Clean silence cutoff (0.85s)
     - Auto mic muting while Pepper speaks
  2. Single-Shot Speech-to-Text:
     - Google Cloud STT in 1 clean request (English & Finnish)
  3. AI Answering on Pepper (No Laptop Required):
     - Groq API (Llama 3.3 70B / 8B — 14,400 free requests/day, ~250ms speed)
     - Live Weather in Leppävaara, Espoo (Open-Meteo, 100% free, no key needed)
     - Live Finnish Date & Time
     - Grounded in 1,650 campus Q&As from campus.json
     - Zero cost, runs directly on Pepper
"""

import sys
import os
import time
import json
import base64
import urllib2
import threading
import random
import re
import collections
import audioop
import wave
import StringIO
import Queue
import subprocess

for _p in ["/opt/aldebaran/lib/python2.7/site-packages", "/usr/lib/python2.7/site-packages"]:
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from naoqi import ALProxy, ALModule, ALBroker

# ------------------------------------------------------------------
# Python 2 Unicode Safety
# ------------------------------------------------------------------
try:
    string_types = (str, unicode)
except NameError:
    string_types = (str,)

def to_utf8(val):
    if val is None:
        return ""
    if isinstance(val, unicode):
        return val.encode("utf-8")
    return str(val)

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------
PEPPER_IP         = "127.0.0.1" if os.path.exists("/home/nao") else "192.168.0.118"
PEPPER_PORT       = 9559
TABLET_URL_BASE   = "http://198.18.0.1/apps/laurimate-1e47c7/index.html"
FIREBASE_URL      = "https://chatwithgemini-wfqmz3bdja-uc.a.run.app"
GOOGLE_STT_KEY    = "AIzaSyBf23uxEGc9upLpirqrdtnfUPKD5um5sDY"

# --- GROQ API (100% Free, runs directly on Pepper, ~200ms latency) ---
def _load_groq_key():
    env_k = os.environ.get("GROQ_API_KEY", "").strip()
    if env_k:
        return env_k
    cand_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "groq_key.txt"),
        "groq_key.txt",
        "/home/nao/Laurimate/groq_key.txt"
    ]
    for p in cand_paths:
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    k = f.read().strip()
                    if k:
                        return k
            except Exception:
                pass
    return ""

GROQ_API_KEY      = _load_groq_key()
GROQ_MODEL        = "openai/gpt-oss-120b"

# --- GEMINI API (Optional alternative from https://aistudio.google.com/apikey) ---
GEMINI_API_KEY    = ""

SAMPLE_RATE         = 16000     # 16 kHz front mic
AUDIO_CHANNEL       = 3         # 3 = Front microphone on Pepper's head
PREROLL_SECONDS     = 1.0       # Retain 1.0s audio before speech trigger
START_THRESHOLD_S   = 0.16      # Speech must sustain 160ms to start listening
SILENCE_TIMEOUT_S   = 1.45      # Wait 1.45s of silence so the user can speak their WHOLE question without being cut off mid-sentence
MIN_SPEECH_SEC      = 0.50      # Ignore short 1-syllable noise bursts shorter than 500ms
MAX_RECORD_SEC      = 16.0      # Safety cutoff for long questions
IDLE_SESSION_SEC    = 60.0      # Return to welcome screen after 60s inactivity

# Smart Barge-In (Mid-Answer Interruption) Settings:
# From live Pepper mic logs:
#   - Pepper's own TTS voice averages ~3500-7500 RMS (with brief 1-frame syllable peaks ~8500 RMS)
#   - A human interrupting Pepper while TTS plays produces sustained ~9200-12000+ RMS
# Setting BARGE_IN_MIN_RMS = 8800.0 with 0.36s sustain lets Pepper finish answers smoothly
# while interrupting immediately when a person talks over Pepper.
BARGE_IN_SUSTAIN_S  = 0.36      # 360ms sustained voice above threshold to interrupt Pepper mid-answer
BARGE_IN_MIN_RMS    = 8800.0    # Sweet-spot threshold measured from Pepper's head mic logs
BARGE_IN_GRACE_S    = 0.55      # Initial 550ms grace window at start of TTS answer

# ------------------------------------------------------------------
# Natural Hand Signs & Gestures Library (Categorized by Meaning)
# ------------------------------------------------------------------
GESTURE_HEY = [
    "animations/Stand/Gestures/Hey_1", "animations/Stand/Gestures/Hey_3",
    "animations/Stand/Gestures/Hey_4", "animations/Stand/Gestures/Hey_6"
]
GESTURE_WAVE = [
    "animations/Stand/Gestures/Hey_3", "animations/Stand/Gestures/Hey_1"
]
GESTURE_BYE = [
    "animations/Stand/Gestures/Hey_2", "animations/Stand/Gestures/BowShort_1",
    "animations/Stand/Gestures/Salute_1"
]
GESTURE_ME = [
    "animations/Stand/Gestures/Me_1", "animations/Stand/Gestures/Me_2",
    "animations/Stand/Gestures/Me_4", "animations/Stand/Gestures/Me_7"
]
GESTURE_YOU = [
    "animations/Stand/Gestures/You_1", "animations/Stand/Gestures/You_2",
    "animations/Stand/Gestures/You_3", "animations/Stand/Gestures/You_4",
    "animations/Stand/Gestures/Give_1", "animations/Stand/Gestures/Give_3",
    "animations/Stand/Gestures/Please_1"
]
GESTURE_YES = [
    "animations/Stand/Gestures/Yes_1", "animations/Stand/Gestures/Yes_2",
    "animations/Stand/Gestures/Yes_3", "animations/Stand/Gestures/Great_1"
]
GESTURE_NO = [
    "animations/Stand/Gestures/No_1", "animations/Stand/Gestures/No_2",
    "animations/Stand/Gestures/No_3", "animations/Stand/Gestures/No_8"
]
GESTURE_DONT_KNOW = [
    "animations/Stand/Gestures/IDontKnow_1", "animations/Stand/Gestures/IDontKnow_2",
    "animations/Stand/Gestures/IDontKnow_3", "animations/Stand/Gestures/Maybe_1"
]
GESTURE_DIRECTION = [
    "animations/Stand/Gestures/ShowFloor_1", "animations/Stand/Gestures/ShowFloor_2",
    "animations/Stand/Gestures/ShowFloor_3", "animations/Stand/Gestures/Far_1",
    "animations/Stand/Gestures/Far_2", "animations/Stand/Gestures/TakePlace_1",
    "animations/Stand/Gestures/TakePlace_2", "animations/Stand/Gestures/Look_1"
]
GESTURE_SKY_WEATHER = [
    "animations/Stand/Gestures/ShowSky_1", "animations/Stand/Gestures/ShowSky_2",
    "animations/Stand/Gestures/ShowSky_4", "animations/Stand/Gestures/ShowSky_6",
    "animations/Stand/Gestures/ShowSky_8"
]
GESTURE_SHOW = [
    "animations/Stand/Gestures/ShowTablet_1", "animations/Stand/Gestures/ShowTablet_2",
    "animations/Stand/Gestures/ShowTablet_3", "animations/Stand/Gestures/This_1",
    "animations/Stand/Gestures/This_2", "animations/Stand/Gestures/This_3"
]
GESTURE_FOOD = [
    "animations/Stand/Gestures/Yum_1", "animations/Stand/Gestures/Give_4",
    "animations/Stand/Gestures/Everything_1", "animations/Stand/Gestures/Enthusiastic_4"
]
GESTURE_COUNT_ALL = [
    "animations/Stand/Gestures/Everything_1", "animations/Stand/Gestures/Everything_2",
    "animations/Stand/Gestures/Everything_3", "animations/Stand/Gestures/Everything_4",
    "animations/Stand/Gestures/CountTwo_1", "animations/Stand/Gestures/CountThree_1",
    "animations/Stand/Gestures/Choice_1"
]
GESTURE_ENTHUSE = [
    "animations/Stand/Gestures/Enthusiastic_4", "animations/Stand/Gestures/Enthusiastic_5",
    "animations/Stand/Gestures/Joy_1", "animations/Stand/Gestures/Excited_1",
    "animations/Stand/Gestures/Great_1"
]
GESTURE_STORY = [
    "animations/Stand/Gestures/YouKnowWhat_1", "animations/Stand/Gestures/YouKnowWhat_2",
    "animations/Stand/Gestures/YouKnowWhat_3", "animations/Stand/Gestures/YouKnowWhat_5",
    "animations/Stand/Gestures/WhatSThis_1", "animations/Stand/Gestures/WhatSThis_2",
    "animations/Stand/Gestures/This_4", "animations/Stand/Gestures/This_5"
]
GESTURE_EXPLAIN = [
    "animations/Stand/Gestures/Explain_1", "animations/Stand/Gestures/Explain_2",
    "animations/Stand/Gestures/Explain_3", "animations/Stand/Gestures/Explain_4",
    "animations/Stand/Gestures/Explain_5", "animations/Stand/Gestures/Explain_6",
    "animations/Stand/Gestures/Explain_7", "animations/Stand/Gestures/Explain_8",
    "animations/Stand/Gestures/Explain_10", "animations/Stand/Gestures/Explain_11",
    "animations/Stand/BodyTalk/Speaking/BodyTalk_1", "animations/Stand/BodyTalk/Speaking/BodyTalk_2",
    "animations/Stand/BodyTalk/Speaking/BodyTalk_3", "animations/Stand/BodyTalk/Speaking/BodyTalk_4",
    "animations/Stand/BodyTalk/Speaking/BodyTalk_5", "animations/Stand/BodyTalk/Speaking/BodyTalk_6"
]
GESTURE_THINKING = [
    "animations/Stand/Gestures/Thinking_1", "animations/Stand/Gestures/Thinking_3",
    "animations/Stand/Gestures/Thinking_4", "animations/Stand/Gestures/Thinking_6"
]

INSTANT_CACHE = {
    "hello":             "Hello! I am Laurimate, your campus assistant. How can I help you today?",
    "hi":                "Hi there! How can I help you?",
    "hey":               "Hey! What would you like to know about Laurea?",
    "hey laurimate":     "Hello! I am here and listening.",
    "moi":               "Moi! Kuinka voin auttaa sinua tänään?",
    "moikka":            "Moikka! Miten voin auttaa sinua?",
    "moro":              "Moro! Mitä haluaisit tietää Laureasta?",
    "hei":               "Hei! Mitä haluaisit tietää Laureasta?",
    "heippa":            "Heippa! Kuinka voin auttaa?",
    "terve":             "Terve! Kuinka voin auttaa?",
    "huomenta":          "Hyvää huomenta! Kuinka voin auttaa sinua tänään?",
    "hyvää huomenta":    "Hyvää huomenta! Miten voin auttaa?",
    "päivää":            "Hyvää päivää! Kuinka voin auttaa?",
    "hyvää päivää":      "Hyvää päivää! Kuinka voin auttaa sinua Laureassa?",
    "mitä kuuluu":       "Kiitos, minulle kuuluu oikein hyvää! Entä sinulle, miten voin auttaa?",
    "kuka sinä olet":    "Olen Laurimate, Laurean älykäs kampusrobotti. Rakesh ja Prasiddha ovat luoneet minut.",
    "kuka olet":         "Olen Laurimate, Laurean kampusavustajarobotti.",
    "puhutko suomea":    "Kyllä, puhun suomea ja englantia! Kysy vain mitä tahansa.",
    "thank you":         "You are warmly welcome!",
    "thanks":            "Happy to help!",
    "kiitos":            "Ole hyvä! Autan mielelläni.",
    "kiitti":            "Ole hyvä!",
    "kiitoksia":         "Ole hyvä! Mukava olla avuksi.",
    "paljon kiitoksia":  "Ole hyvä! Mukavaa päivää sinulle.",
    "anteeksi":          "Ei mitään! Kuinka voin auttaa sinua?",
    "bye":               "Goodbye! Have a wonderful day at Laurea!",
    "goodbye":           "Goodbye! See you soon!",
    "näkemiin":          "Näkemiin! Hyvää päivänjatkoa Laureassa!",
    "nähdään":           "Nähdään taas! Mukavaa päivää!",
    "hei hei":           "Hei hei! Nähdään taas!"
}

STOP_WORDS = set([
    "what", "where", "when", "how", "who", "whom", "whose", "which", "why",
    "is", "are", "was", "were", "be", "been", "being", "am",
    "the", "a", "an", "to", "from", "in", "on", "at", "of", "for", "with", "without", "by", "about", "into", "onto",
    "can", "could", "would", "should", "will", "shall", "may", "might", "must",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them", "my", "your", "our", "their",
    "this", "that", "these", "those", "there", "here",
    "do", "does", "did", "done", "doing", "go", "going", "get", "got", "getting", "make", "making",
    "have", "has", "had", "having", "need", "want", "like", "know", "think", "find", "give",
    "tell", "show", "please", "thanks", "thank", "hey", "hi", "hello", "mate", "uh", "um", "oh", "well", "ok", "okay",
    "right", "now", "today", "currently", "just", "really", "very", "much", "many", "some", "any", "more", "also",
    "laurimate",
    "mitä", "missä", "milloin", "miten", "kuka", "miksi", "onko", "se", "ja", "ole", "on", "voitko", "kerro", "minulle"
])

LaurimateAudioInstance = None


# ==================================================================
# Live Weather & Live Time Services (100% Free, Direct on Pepper)
# ==================================================================

cached_weather_str = ""
last_weather_fetch = 0.0

def get_live_weather():
    """Fetches real-time weather in Leppävaara, Espoo via Open-Meteo (No API key needed)."""
    global cached_weather_str, last_weather_fetch
    now_ts = time.time()
    # Cache weather for 10 minutes to be fast and gentle on network
    if cached_weather_str and (now_ts - last_weather_fetch) < 600.0:
        return cached_weather_str

    try:
        cmd = ["curl", "-s", "--max-time", "4", "http://api.open-meteo.com/v1/forecast?latitude=60.2185&longitude=24.8126&current_weather=true"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = p.communicate()
        data = json.loads(out)
        cw = data.get("current_weather", {})
        temp = cw.get("temperature", "")
        wind = cw.get("windspeed", "")
        code = cw.get("weathercode", 0)

        condition = "clear sky"
        if code in [1, 2, 3]: condition = "partly cloudy"
        elif code in [45, 48]: condition = "foggy"
        elif code in [51, 53, 55, 61, 63, 65]: condition = "rainy"
        elif code in [71, 73, 75, 77, 85, 86]: condition = "snowing"
        elif code in [95, 96, 99]: condition = "thunderstorm"

        weather_desc = "{:.0f} degrees Celsius, {}, wind speed {} km/h".format(float(temp), condition, wind)
        cached_weather_str = weather_desc
        last_weather_fetch = now_ts
        print("[Laurimate] Live weather updated: {}".format(weather_desc))
        return weather_desc
    except Exception as e:
        print("[Laurimate] Weather fetch note: {}".format(e))
        return cached_weather_str or "around 4 degrees Celsius and clear"


def _helsinki_from_utc(utc):
    """Convert a naive UTC datetime to Helsinki time (EET UTC+2 / EEST UTC+3, EU DST rules)."""
    import datetime
    def last_sunday(year, month):
        d = datetime.datetime(year, month, 31)
        while d.weekday() != 6:
            d -= datetime.timedelta(days=1)
        return d
    start = last_sunday(utc.year, 3).replace(hour=1)    # last Sunday of March, 01:00 UTC
    end = last_sunday(utc.year, 10).replace(hour=1)     # last Sunday of October, 01:00 UTC
    offset = 3 if start <= utc < end else 2
    return utc + datetime.timedelta(hours=offset)


# The robot's own clock is unreliable (it can be years off), so we read real time
# from the internet once, remember how far the robot clock is off, and apply that.
_time_offset = None       # real UTC minus robot clock, in seconds
_time_offset_at = 0.0


def _fetch_real_utc():
    """Returns a naive UTC datetime from the internet, or None."""
    import datetime
    import email.utils
    # 1) timeapi.io gives Helsinki time directly (already DST-correct)
    try:
        cmd = ["curl", "-k", "-s", "--max-time", "4",
               "https://timeapi.io/api/Time/current/zone?timeZone=Europe/Helsinki"]
        out, _ = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
        d = json.loads(out)
        hel = datetime.datetime(int(d["year"]), int(d["month"]), int(d["day"]), int(d["hour"]), int(d["minute"]), int(d.get("seconds", 0)))
        hours = 3 if d.get("dstActive") else 2
        return hel - datetime.timedelta(hours=hours)
    except Exception:
        pass
    # 2) HTTP Date header (always UTC) from a reliable server
    for url in ["http://www.google.com", "http://www.cloudflare.com"]:
        try:
            out, _ = subprocess.Popen(["curl", "-s", "-I", "--max-time", "4", url],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
            m = re.search(r"^Date:\s*(.+?)\s*$", out, re.I | re.M)
            if m:
                tup = email.utils.parsedate(m.group(1))
                return datetime.datetime(*tup[:6])
        except Exception:
            pass
    return None


def _helsinki_now():
    """Current Helsinki time, independent of the robot's (wrong) clock when internet is available."""
    import datetime
    global _time_offset, _time_offset_at
    now_ts = time.time()
    if _time_offset is None or (now_ts - _time_offset_at) > 600:
        real_utc = _fetch_real_utc()
        if real_utc is not None:
            robot_utc = datetime.datetime.utcfromtimestamp(now_ts)
            _time_offset = (real_utc - robot_utc).total_seconds()
            _time_offset_at = now_ts
            print("[Laurimate] Clock synced from internet (robot clock off by {:.0f}s)".format(_time_offset))
    utc = datetime.datetime.utcfromtimestamp(now_ts)
    if _time_offset is not None:
        utc += datetime.timedelta(seconds=_time_offset)
    return _helsinki_from_utc(utc)


def get_live_time_str(lang="en"):
    """Returns Helsinki day, time and date."""
    now = _helsinki_now()
    wd = now.weekday()  # Monday = 0
    if lang == "fi":
        days_fi = ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai", "sunnuntai"]
        return "{}, kello on {:02d}:{:02d}, {}.{}.{}".format(days_fi[wd], now.hour, now.minute, now.day, now.month, now.year)
    days_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return "{}, {:02d}:{:02d}, {}/{}/{}".format(days_en[wd], now.hour, now.minute, now.month, now.day, now.year)


# ==================================================================
# Local Campus Knowledge Base (1,650 Questions & Answers)
# ==================================================================

CORE_CAMPUS_FACTS = (
    u"LAUREA LEPPÄVAARA CAMPUS ESSENTIAL FACTS:\n"
    u"- Address: Vanha maantie 9, 02650 Espoo, Finland.\n"
    u"- Getting there: Leppävaara train station is about a 7-8 min walk (~600m). Located in HSL B zone.\n"
    u"- Entrances: Main entrance on 1st floor; Stairway B entrance on ground floor (has elevator).\n"
    u"- Reception & Lobby Services: 1st floor at main entrance. Phone: +358 9 8868 7402, email: aulapalvelut.leppavaara@laurea.fi.\n"
    u"- Opening hours: Open weekdays during daytime. Closed on weekends.\n"
    u"- Wi-Fi: The Wi-Fi SSID is the 'eduroam' network, and students/staff log in using their Laurea student email (username@laurea.fi) and password. Visitors can use 'Laurea-Guest'.\n"
    u"- Canteen / Student Lunch: Campus restaurant BarLaurea / cafeteria on ground floor. Discounted student lunch with student card; menus are in the Tuudo app.\n"
    u"- Library: Laurea Leppävaara Library on campus. Books, quiet study spaces, computers, group work rooms. Library card in Tuudo app.\n"
    u"- Printing & Copying: Multifunctional printers across campus. Log in using student card or Laurea credentials.\n"
    u"- Student Services / Study Affairs: Assists with enrollment, study certificates, transcript of records (Pakki at pakki.laurea.fi).\n"
    u"- Campuses: Leppävaara (Espoo), Otaniemi, Tikkurila (Vantaa), Hyvinkää, Porvoo, and Lohja."
)

CAMPUS_SYNONYMS = {
    "wifi": ["wifi", "eduroam", "wireless", "network"],
    "internet": ["wifi", "eduroam", "network"],
    "password": ["password", "eduroam", "credentials", "login"],
    "salasana": ["password", "eduroam", "credentials", "login"],
    "verkko": ["wifi", "eduroam", "wireless", "network"],
    "toilet": ["restroom", "toilet", "accessible"],
    "bathroom": ["restroom", "toilet", "accessible"],
    "wc": ["restroom", "toilet"],
    "vessa": ["restroom", "toilet", "accessible"],
    "canteen": ["restaurant", "lunch", "cafeteria", "menu", "tuudo"],
    "cafeteria": ["restaurant", "lunch", "cafeteria", "menu", "tuudo"],
    "food": ["restaurant", "lunch", "menu", "cafe", "tuudo"],
    "eat": ["restaurant", "lunch", "menu"],
    "ruokala": ["restaurant", "lunch", "cafeteria", "menu", "tuudo"],
    "ravintola": ["restaurant", "lunch", "cafeteria", "menu", "tuudo"],
    "ruoka": ["restaurant", "lunch", "menu", "tuudo"],
    "ruokalista": ["restaurant", "lunch", "menu", "tuudo"],
    "lounas": ["restaurant", "lunch", "menu", "tuudo"],
    "kahvila": ["cafe", "cafeteria", "restaurant", "lunch"],
    "kirjasto": ["library", "book", "borrow", "study", "tuudo"],
    "opintotoimisto": ["student", "services", "office", "study", "affairs", "pakki"],
    "aulapalvelut": ["reception", "lobby", "entrance", "services"],
    "lukujärjestys": ["timetable", "schedule", "tuudo", "pakki"],
    "lukujarjestys": ["timetable", "schedule", "tuudo", "pakki"],
    "opiskelijakortti": ["student", "card", "tuudo", "discount", "lunch"],
    "pysäköinti": ["parking", "car", "park", "permit"],
    "pysakointi": ["parking", "car", "park", "permit"],
    "osoite": ["address", "vanha", "maantie", "location", "espoo"],
    "aukioloajat": ["opening", "hours", "open", "close", "door"],
    "juna": ["train", "station", "leppavaara", "walk", "hsl"],
    "train": ["station", "leppavaara", "walk", "hsl"],
    "bussi": ["buses", "hsl", "terminal", "station"],
    "bus": ["buses", "hsl", "terminal", "station"],
    "leppävaara": ["leppavaara", "vanha", "maantie", "espoo", "campus", "station"],
    "leppavaara": ["leppavaara", "vanha", "maantie", "espoo", "campus", "station"],
    "tikkurila": ["tikkurila", "vantaa", "campus", "ratatie"],
    "otaniemi": ["otaniemi", "espoo", "campus", "metsanpojankuja"],
    "hyvinkää": ["hyvinkaa", "campus", "udenmaankatu"],
    "hyvinkaa": ["hyvinkaa", "campus", "udenmaankatu"],
    "porvoo": ["porvoo", "campus", "taidetehtaankatu"],
    "lohja": ["lohja", "campus", "nummenkatu"],
}


def _normalize_for_search(text):
    """Collapses hyphenated words like 'Wi-Fi' -> 'wifi' so spoken 'wifi' matches 'Wi-Fi' in campus.json."""
    t = text.lower()
    t = re.sub(r'(\w)-(\w)', r'\1\2', t)
    return t


def _word_stem(w):
    w = w.lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("es"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


class CampusDatabase(object):
    def __init__(self, json_path="/home/nao/Laurimate/campus.json"):
        self.faqs = []       # list of (q, a, q_stems, a_norm)
        base_dir = os.path.dirname(os.path.abspath(__file__))

        for jp in [json_path, os.path.join(base_dir, "campus.json"), os.path.join(base_dir, "functions", "data", "campus.json")]:
            if os.path.exists(jp):
                try:
                    with open(jp, "r") as f:
                        data = json.load(f)
                    sections = data.get("sections", {})
                    for s_key, sec in sections.items():
                        questions = sec.get("questions", {})
                        for q_key, item in questions.items():
                            q = to_utf8(item.get("q", ""))
                            a = to_utf8(item.get("a", ""))
                            if q and a:
                                q_norm = _normalize_for_search(q)
                                a_norm = _normalize_for_search(a)
                                q_words = [w for w in re.findall(r'\b\w+\b', q_norm) if len(w) >= 2]
                                q_stems = set(_word_stem(w) for w in q_words)
                                self.faqs.append((q, a, q_stems, a_norm))
                    print("[Laurimate] Loaded {} campus Q&As from {}".format(len(self.faqs), jp))
                    break
                except Exception as e:
                    print("[Laurimate] Campus DB load note: {}".format(e))

    def get_context(self, query, top_k=8):
        """Extracts top relevant Q&A facts from campus.json to feed into the AI for natural formatting."""
        if not self.faqs or not query:
            return ""

        q_norm = _normalize_for_search(query)
        raw_words = [
            w for w in re.findall(r'\b\w+\b', q_norm)
            if w not in STOP_WORDS and (len(w) > 2 or w in ("it", "id", "cv", "eu", "vr", "pc", "3d", "ai", "ui", "ux", "wc"))
        ]
        if not raw_words:
            return ""

        expanded = list(raw_words)
        for w in raw_words:
            if w in CAMPUS_SYNONYMS:
                expanded.extend(CAMPUS_SYNONYMS[w])
            stem = _word_stem(w)
            if stem in CAMPUS_SYNONYMS:
                expanded.extend(CAMPUS_SYNONYMS[stem])

        stems = set(_word_stem(w) for w in expanded)
        primary_stems = set(_word_stem(w) for w in raw_words)

        scored = []
        for q, a, q_stems, a_norm in self.faqs:
            score = 0
            primary_overlap = primary_stems.intersection(q_stems)
            syn_overlap = (stems - primary_stems).intersection(q_stems)
            score += len(primary_overlap) * 8 + len(syn_overlap) * 5

            for w in set(expanded):
                if len(w) >= 3 and re.search(r'\b' + re.escape(w), a_norm):
                    score += 3 if w in raw_words else 2

            if score >= 5:
                scored.append((score, q, a))

        if not scored:
            return ""

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]

        context_lines = []
        for s, q, a in top:
            context_lines.append("Q: {} | A: {}".format(q, a))
        print("[Laurimate] campus.json matched {} facts (top score={}): {}".format(len(top), top[0][0], top[0][1]))
        return "\n".join(context_lines)

    def get_best_match(self, query):
        if not self.faqs or not query:
            return None, 0
        q_norm = _normalize_for_search(query)
        raw_words = [w for w in re.findall(r'\b\w+\b', q_norm) if w not in STOP_WORDS and len(w) > 2]
        if not raw_words:
            return None, 0
        stems = set(_word_stem(w) for w in raw_words)
        best_match = None
        best_score = 0
        for q, a, q_stems, a_norm in self.faqs:
            score = len(stems.intersection(q_stems)) * 8
            if score > best_score:
                best_score = score
                best_match = (q, a)
        if best_score >= 8:
            return best_match, best_score
        return None, 0

campus_db = CampusDatabase()


# ==================================================================
# Live Website & Web Search (100% Free, Direct on Pepper)
# ==================================================================

def _curl_text(url, timeout=4):
    try:
        cmd = ["curl", "-k", "-s", "-L", "--max-time", str(timeout), "-A", "Mozilla/5.0 (Laurimate Pepper)", url]
        out, _ = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()
        return out
    except Exception:
        return ""


def _page_excerpt(url, query_words, max_chars=900):
    """Downloads a web page and returns the paragraphs most relevant to the question."""
    raw = _curl_text(url, 4)
    if not raw:
        return ""
    html = raw.decode("utf-8", "ignore")
    html = re.sub(r'(?is)<(script|style|nav|header|footer|noscript)[^>]*>.*?</\1>', ' ', html)
    paras = re.findall(r'(?is)<(?:p|li|h2|h3)[^>]*>(.*?)</(?:p|li|h2|h3)>', html)
    cleaned = []
    for ptxt in paras:
        ptxt = re.sub(r'(?s)<[^>]+>', ' ', ptxt)
        ptxt = re.sub(r'&(#8217|#8216|rsquo|lsquo);', "'", ptxt)
        ptxt = re.sub(r'&(#8211|#8212|ndash|mdash);', '-', ptxt)
        ptxt = re.sub(r'&nbsp;', ' ', ptxt)
        ptxt = re.sub(r'&amp;', '&', ptxt)
        ptxt = re.sub(r'\s+', ' ', ptxt).strip()
        if len(ptxt) > 40:
            cleaned.append(ptxt)
    if not cleaned:
        return ""
    def rel(ptxt):
        low = ptxt.lower()
        return sum(1 for w in query_words if w in low)
    ranked = [c for c in sorted(cleaned, key=rel, reverse=True) if rel(c) > 0]
    text = " ".join(ranked[:4])
    return to_utf8(text[:max_chars])


def search_laurea_website(query):
    """Searches the official laurea.fi site and returns real page text (not just titles)."""
    try:
        words = [w.lower() for w in re.findall(r'\w+', query) if w.lower() not in STOP_WORDS and len(w) > 2]
        clean_q = re.sub(r'[^\w\s]', '', query).strip()
        if not clean_q or not words:
            return ""
        out = _curl_text("https://www.laurea.fi/wp-json/wp/v2/search?search=" + clean_q.replace(" ", "+") + "&per_page=3", 4)
        data = json.loads(out)
        if not isinstance(data, list) or not data:
            return ""
        results = []
        for item in data[:2]:
            title = to_utf8(item.get("title", ""))
            url = to_utf8(item.get("url", ""))
            if not url:
                continue
            excerpt = _page_excerpt(url, words)
            if excerpt:
                results.append("[laurea.fi: {}] {}".format(title, excerpt))
        if results:
            print("[Laurimate] Found {} relevant pages on laurea.fi".format(len(results)))
        return "\n".join(results)
    except Exception as e:
        print("[Laurimate] Laurea.fi search note: {}".format(e))
    return ""


def search_wikipedia(query):
    """Short verified encyclopedia extracts (top 3 pages) for general-knowledge questions."""
    try:
        clean_q = re.sub(r'[^\w\s]', '', query).strip()
        if not clean_q:
            return ""
        url = ("https://en.wikipedia.org/w/api.php?action=query&generator=search&gsrlimit=3&prop=extracts"
               "&exintro=1&explaintext=1&exsentences=4&format=json&gsrsearch=" + clean_q.replace(" ", "+"))
        data = json.loads(_curl_text(url, 4))
        pages = data.get("query", {}).get("pages", {})
        out_list = []
        for pg in sorted(pages.values(), key=lambda x: x.get("index", 99)):
            extract = to_utf8(pg.get("extract", "")).strip()
            if extract:
                title = to_utf8(pg.get("title", ""))
                print("[Laurimate] Found Wikipedia extract: {}".format(title))
                out_list.append("[Wikipedia: {}] {}".format(title, extract[:500]))
        return "\n".join(out_list)
    except Exception as e:
        print("[Laurimate] Wikipedia note: {}".format(e))
    return ""


def search_web_instant(query):
    """DuckDuckGo Instant Answer (free, no key)."""
    try:
        clean_q = re.sub(r'[^\w\s]', '', query).strip()
        if not clean_q:
            return ""
        data = json.loads(_curl_text("https://api.duckduckgo.com/?q=" + clean_q.replace(" ", "+") + "&format=json", 4))
        abstract = to_utf8(data.get("AbstractText", "")).strip()
        if abstract:
            return "[Web: {}] {}".format(to_utf8(data.get("AbstractSource", "Web")), abstract[:700])
    except Exception as e:
        print("[Laurimate] Web search note: {}".format(e))
    return ""


def gather_web_sources(question):
    """Runs laurea.fi, Wikipedia and DuckDuckGo lookups in parallel; returns list of source strings."""
    results = {}
    def run(name, fn):
        try:
            results[name] = fn(question)
        except Exception:
            results[name] = ""
    threads = []
    for name, fn in [("laurea", search_laurea_website), ("wiki", search_wikipedia), ("ddg", search_web_instant)]:
        th = threading.Thread(target=run, args=(name, fn))
        th.daemon = True
        th.start()
        threads.append(th)
    deadline = time.time() + 7.0
    for th in threads:
        th.join(max(0.1, deadline - time.time()))
    return [results[k] for k in ("laurea", "wiki", "ddg") if results.get(k)]


# ==================================================================
# Tablet UI Helpers
# ==================================================================

def _ensure_webview_layer_on_top(tablet):
    """Brings the loaded WebView layer to the foreground without reloading the page."""
    if tablet and not os.path.exists("/tmp/laurimate_kids_webview_v6.flag"):
        try: tablet.showWebview()
        except Exception: pass

def set_welcome(tablet):
    if tablet:
        _ensure_webview_layer_on_top(tablet)
        try: tablet.executeJS("showWelcome();")
        except Exception: pass

def set_listening(tablet):
    if tablet:
        _ensure_webview_layer_on_top(tablet)
        try: tablet.executeJS("showListening();")
        except Exception: pass

def set_thinking(tablet):
    if tablet:
        _ensure_webview_layer_on_top(tablet)
        try: tablet.executeJS("showThinking();")
        except Exception: pass

def set_transcript(tablet, transcript):
    if tablet and transcript:
        _ensure_webview_layer_on_top(tablet)
        try:
            t_js = to_utf8(transcript).replace("\\", "\\\\").replace("'", "\\'")
            tablet.executeJS("showTranscript('{}');".format(t_js))
        except Exception: pass

def set_answer(tablet, question, answer, source="ai"):
    if tablet:
        _ensure_webview_layer_on_top(tablet)
        try:
            q_js = to_utf8(question).replace("\\", "\\\\").replace("'", "\\'")
            a_js = to_utf8(answer).replace("\\", "\\\\").replace("'", "\\'")
            tablet.executeJS("showAnswer('{}', '{}', '{}');".format(q_js, a_js, source))
        except Exception: pass

def set_no_speech(tablet):
    if tablet:
        _ensure_webview_layer_on_top(tablet)
        try: tablet.executeJS("showNoSpeech();")
        except Exception: pass

def play_gesture_async(animation_player, gesture_path):
    if not gesture_path: return
    if isinstance(gesture_path, list):
        gesture_path = random.choice(gesture_path)

    def _run():
        try: animation_player.run(gesture_path)
        except Exception as e:
            print("[Laurimate] Gesture error: {}".format(e))
    t = threading.Thread(target=_run)
    t.daemon = True
    t.start()


# ==================================================================
# Finnish Speech Recognition Hints, Samples & Fast Phonetic Normalizer
# ==================================================================

FINNISH_PHRASE_HINTS = [
    # Campuses & phonetic variants
    "Laurea", "Lauria", "Loria", "Laurean", "Laureassa", "Laureasta",
    "Laurimate", "Lauri mate",
    "Leppävaara", "Leppavaara", "Leppavara", "Lepavara", "Leppa vaara",
    "Leppävaaran", "Leppävaarassa", "Leppävaaraan", "Leppavaaran",
    "Tikkurila", "Tikurilla", "Tikkurilla", "Tikurila", "Tiku rila",
    "Tikkurilan", "Tikkurilassa", "Tikkurilaan",
    "Otaniemi", "Ota niemi", "Otaniemen", "Otaniemessä", "Otaniemeen",
    "Hyvinkää", "Hyvinkaa", "Hyvinka", "Huvinka", "Hyvinkään", "Hyvinkäällä",
    "Porvoo", "Porvo", "Porvoon", "Porvoossa",
    "Lohja", "Lohya", "Lohjan", "Lohjalla",
    # Cities, streets & transport
    "Espoo", "Espoon", "Espoossa", "Vantaa", "Vantaan", "Vantaalla",
    "Helsinki", "Helsingin", "Vanha maantie", "Vanha maantie 9", "HSL",
    # Campus systems & student life
    "eduroam", "Tuudo", "Tudo", "Moodle", "Pakki", "Paki",
    "Laureamko", "BarLaurea", "Bar Laurea", "Kela", "HOAS", "AMK",
    # Common Finnish campus nouns
    "kirjasto", "kirjastossa", "ruokala", "ravintola", "ruokalista", "lounas", "kahvila",
    "opintotoimisto", "aulapalvelut", "vessa", "pysäköinti", "lukujärjestys",
    "opiskelija", "opiskelijakortti", "osoite", "aukioloajat", "juna", "bussi",
    # Common Finnish greetings & question starters
    "terve", "päivää", "hyvää päivää", "huomenta", "hyvää huomenta",
    "kiitos", "kiitti", "kiitoksia", "paljon kiitoksia", "ole hyvä",
    "näkemiin", "nähdään", "hei hei", "anteeksi",
    "moi", "moikka", "moro", "hei", "heippa",
    "mitä", "mitä kuuluu", "missä", "missä on", "milloin", "miten",
    "kuka", "kuka olet", "onko", "voitko", "puhutko suomea", "kello", "sää"
]

# Direct multi-word & single-word spoken mishearing samples -> Canonical Finnish word
FINNISH_RECOGNITION_SAMPLES = [
    # Leppävaara samples (hardest Finnish word for English STT)
    ("leppa vaara", "Leppävaara"), ("lepa vaara", "Leppävaara"), ("lepa vara", "Leppävaara"),
    ("leppa vara", "Leppävaara"), ("lipa vara", "Leppävaara"), ("lipa vaara", "Leppävaara"),
    ("leppä vaara", "Leppävaara"), ("let the vara", "Leppävaara"), ("leopard vara", "Leppävaara"),
    ("leppa bar", "Leppävaara"), ("lepa bar", "Leppävaara"), ("leppavara", "Leppävaara"),
    ("lepavara", "Leppävaara"), ("lepavaara", "Leppävaara"), ("leppavaara", "Leppävaara"),
    ("leppavaaran", "Leppävaara"), ("leppavarassa", "Leppävaara"), ("leppavaar", "Leppävaara"),

    # Tikkurila samples
    ("tiku rila", "Tikkurila"), ("tiku rilla", "Tikkurila"), ("tikka rilla", "Tikkurila"),
    ("tikka rila", "Tikkurila"), ("tequila campus", "Tikkurila campus"),
    ("tikurilla", "Tikkurila"), ("tikkurilla", "Tikkurila"), ("tikurila", "Tikkurila"),
    ("ticorila", "Tikkurila"), ("tecurila", "Tikkurila"), ("tickrila", "Tikkurila"),
    ("tikorila", "Tikkurila"), ("tikurilan", "Tikkurila"), ("tikkuril", "Tikkurila"),

    # Laurea & Laurimate samples
    ("lauri mate", "Laurimate"), ("laurie mate", "Laurimate"), ("lori mate", "Laurimate"),
    ("laurea mate", "Laurimate"), ("lory mate", "Laurimate"), ("lauramite", "Laurimate"),
    ("bar laura", "BarLaurea"), ("bar loria", "BarLaurea"), ("bar lauria", "BarLaurea"),
    ("bar laurea", "BarLaurea"),
    ("laurea amko", "Laureamko"), ("lauriamko", "Laureamko"), ("lauramko", "Laureamko"),
    ("loriamko", "Laureamko"),
    ("lauria", "Laurea"), ("laura", "Laurea"), ("loria", "Laurea"), ("lorea", "Laurea"),
    ("lorya", "Laurea"), ("gloria campus", "Laurea campus"), ("lowry", "Laurea"),
    ("lauriam", "Laurea"), ("lauream", "Laurea"),

    # Otaniemi, Hyvinkää, Porvoo, Lohja, Vanha maantie
    ("ota niemi", "Otaniemi"), ("otta niemi", "Otaniemi"), ("ota nimi", "Otaniemi"),
    ("otanimi", "Otaniemi"), ("autoniemi", "Otaniemi"), ("atanimi", "Otaniemi"),
    ("hyvinkaa", "Hyvinkää"), ("hyvinka", "Hyvinkää"), ("huvinka", "Hyvinkää"),
    ("huvinkaa", "Hyvinkää"), ("hivinka", "Hyvinkää"), ("hivinkaa", "Hyvinkää"),
    ("hyvinga", "Hyvinkää"), ("hoovinka", "Hyvinkää"), ("heavinka", "Hyvinkää"),
    ("porvo", "Porvoo"), ("poorvo", "Porvoo"), ("poorvoo", "Porvoo"), ("borvo", "Porvoo"),
    ("lohya", "Lohja"), ("loja", "Lohja"), ("loya", "Lohja"),
    ("vanha mantie", "Vanha maantie"), ("vana mantie", "Vanha maantie"),
    ("vanha monty", "Vanha maantie"), ("vanha man tie", "Vanha maantie"),

    # Systems & common Finnish words
    ("edu roam", "eduroam"), ("edu room", "eduroam"), ("eduroom", "eduroam"),
    ("eduram", "eduroam"), ("edurom", "eduroam"),
    ("to do app", "Tuudo"), ("todo app", "Tuudo"), ("two do", "Tuudo"), ("tudo", "Tuudo"),
    ("paki", "Pakki"), ("pucky", "Pakki"), ("packy", "Pakki"),
    ("opinto toimisto", "opintotoimisto"), ("luku järjestys", "lukujärjestys"),
    ("lukujarjestys", "lukujärjestys"), ("pysakointi", "pysäköinti"),
    ("nakemiin", "näkemiin"), ("nahdaan", "nähdään"), ("kito", "kiitos"), ("kitos", "kiitos"),
]

FINNISH_CORRECTIONS = [
    (re.compile(r'\blep+\s*[aäe]?\s*v+[aä]+r+[aä]*(?:n|ssa|ssä|sta|stä|lla|llä|lle|aan|ään)?\b', re.I), "Leppävaara"),
    (re.compile(r'\btik+\s*u?\s*r+\s*[il]+a+(?:n|ssa|sta|lla|lle|an)?\b', re.I), "Tikkurila"),
    (re.compile(r'\b(laura|lauria|loria|lorea|lorya|laurean|laureassa|laureasta|laureaan)\b', re.I), "Laurea"),
    (re.compile(r'\b(h[uy]vink+[aäe]{1,2}(?:n|llä|lla|lle|ltä)?|h[iu]vinka+)\b', re.I), "Hyvinkää"),
    (re.compile(r'\botan\s*[ie]+m+[ie]+(?:n|ssä|ssa|stä|emeen)?\b', re.I), "Otaniemi"),
    (re.compile(r'\bporvo+(?:n|ssa|sta|seen)?\b', re.I), "Porvoo"),
    (re.compile(r'\bloh[jy]a+(?:n|lla|lta|lle)?\b', re.I), "Lohja"),
    (re.compile(r'\bedu\s*ro[aomnu]{2,4}\b', re.I), "eduroam"),
    (re.compile(r'\btu+do+(?:n|ssa|sta)?\b', re.I), "Tuudo"),
    (re.compile(r'\bpak+i(?:n|ssa|sta)?\b', re.I), "Pakki"),
    (re.compile(r'\blaure?a?mko(?:n|ssa)?\b', re.I), "Laureamko"),
]

# Canonical targets for fast phonetic-skeleton fuzzy matching
FINNISH_PHONETIC_TARGETS = [
    ("lepavara",      "Leppävaara"),
    ("lepavaran",     "Leppävaara"),
    ("lepavarasa",    "Leppävaara"),
    ("tikurila",      "Tikkurila"),
    ("tikurilan",     "Tikkurila"),
    ("tikurilasa",    "Tikkurila"),
    ("laurea",        "Laurea"),
    ("laurean",       "Laurea"),
    ("laureasa",      "Laurea"),
    ("laurimate",     "Laurimate"),
    ("otaniemi",      "Otaniemi"),
    ("otaniemen",     "Otaniemi"),
    ("huvinka",       "Hyvinkää"),
    ("huvinkan",      "Hyvinkää"),
    ("porvo",         "Porvoo"),
    ("porvon",        "Porvoo"),
    ("lohja",         "Lohja"),
    ("lohya",         "Lohja"),
    ("laureamko",     "Laureamko"),
    ("barlaurea",     "BarLaurea"),
    ("eduroam",       "eduroam"),
    ("tudo",          "Tuudo"),
    ("paki",          "Pakki"),
    ("kirjasto",      "kirjasto"),
    ("ravintola",     "ravintola"),
    ("ruokala",       "ruokala"),
    ("opintotoimisto","opintotoimisto"),
    ("lukujarjestus", "lukujärjestys"),
    ("opiskelijakorti","opiskelijakortti"),
    ("pusakointi",    "pysäköinti"),
    ("kitos",         "kiitos"),
    ("nakemin",       "näkemiin"),
    ("huomenta",      "huomenta"),
]

FINNISH_ONLY_INDICATORS = set([
    "moi", "moikka", "moro", "hei", "heippa", "terve", "huomenta", "päivää",
    "kiitos", "kiitti", "kiitoksia", "näkemiin", "nähdään", "anteeksi",
    "mitä", "missä", "milloin", "miten", "kuka", "miksi", "mikä", "onko", "voitko",
    "kerro", "minulle", "kuuluu", "kirjasto", "ravintola", "ruokala", "ruokalista",
    "lounas", "kahvila", "opintotoimisto", "lukujärjestys", "opiskelijakortti",
    "pysäköinti", "vessa", "osoite", "aukioloajat", "juna", "bussi", "kello", "sää"
])

ENGLISH_SENTENCE_INDICATORS = set([
    "what", "where", "when", "how", "who", "which", "why", "is", "are", "can", "could",
    "tell", "show", "give", "find", "the", "to", "in", "at", "for", "from", "about", "please"
])


def _phonetic_finnish_skeleton(word):
    """
    Reduces a spoken word to its Finnish phonetic skeleton:
    - Lowercases UTF-8
    - Maps ä->a, ö->o, å->o, y->u, w->v, c->k, q->k
    - Collapses repeated adjacent letters (e.g. 'leppävaara' -> 'lepavara', 'tikurilla' -> 'tikurila')
    """
    if not word:
        return ""
    w = to_utf8(word).lower()
    w = w.replace("\xc3\xa4", "a").replace("\xc3\xb6", "o").replace("\xc3\xa5", "o")
    w = w.replace("\xc3\x84", "a").replace("\xc3\x96", "o").replace("\xc3\x85", "o")
    out = []
    for ch in w:
        if ch == "y": ch = "u"
        elif ch == "w": ch = "v"
        elif ch in ("c", "q"): ch = "k"
        if ch.isalnum():
            if not out or out[-1] != ch:
                out.append(ch)
    return "".join(out)


def _edit_distance_le1(a, b):
    """Fast check whether string a and string b have Levenshtein edit distance <= 1."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        diffs = sum(1 for x, y in zip(a, b) if x != y)
        return diffs <= 1
    if la > lb:
        a, b, la, lb = b, a, lb, la
    # la + 1 == lb
    i = j = diffs = 0
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
        else:
            diffs += 1
            if diffs > 1:
                return False
            j += 1
    return True


def _fuzzy_match_finnish_token(token):
    """Snaps an individual word token to a canonical Finnish word if its phonetic skeleton matches."""
    clean = re.sub(r'[^\w\xc3\xa4\xc3\xb6\xc3\xa5\xc3\x84\xc3\x96\xc3\x85]', '', to_utf8(token))
    if len(clean) < 4 or clean.lower() in ENGLISH_SENTENCE_INDICATORS:
        return None
    skel = _phonetic_finnish_skeleton(clean)
    if len(skel) < 4:
        return None
    for target_skel, canonical in FINNISH_PHONETIC_TARGETS:
        if skel == target_skel:
            return canonical
        # Allow 1-character phonetic tolerance on longer Finnish words (e.g. leppavaara, tikkurila, hyvinkää, otaniemi)
        if len(target_skel) >= 6 and len(skel) >= 5 and skel[0] == target_skel[0] and _edit_distance_le1(skel, target_skel):
            return canonical
    return None


def normalize_finnish_words(text):
    """
    3-Stage Fast Finnish Word Normalizer:
      1) Multi-word & known phrase sample replacement (FINNISH_RECOGNITION_SAMPLES)
      2) Regex inflection & phonetic pattern replacement (FINNISH_CORRECTIONS)
      3) Token-level Finnish phonetic skeleton fuzzy matching (FINNISH_PHONETIC_TARGETS)
    """
    if not text:
        return ""
    text = to_utf8(text)

    # Stage 1: Multi-word and exact sample replacements
    for sample, canonical in FINNISH_RECOGNITION_SAMPLES:
        pattern = re.compile(r'\b' + re.escape(sample) + r'\b', re.I)
        text = pattern.sub(canonical, text)

    # Stage 2: Regex pattern replacements
    for pattern, replacement in FINNISH_CORRECTIONS:
        text = pattern.sub(replacement, text)

    # Stage 3: Token-level fuzzy phonetic skeleton snapping
    tokens = text.split()
    out_tokens = []
    for tok in tokens:
        m = re.match(r'^([^\w]*)([\w\xc3\xa4\xc3\xb6\xc3\xa5\xc3\x84\xc3\x96\xc3\x85]+)([^\w]*)$', tok)
        if m:
            prefix, word, suffix = m.group(1), m.group(2), m.group(3)
            matched_canonical = _fuzzy_match_finnish_token(word)
            if matched_canonical:
                out_tokens.append(prefix + matched_canonical + suffix)
                continue
        out_tokens.append(tok)

    return " ".join(out_tokens)


def _score_finnish_alternative(transcript_text):
    """Scores an STT alternative higher if it contains recognized Finnish campus/vocabulary words."""
    norm = normalize_finnish_words(transcript_text)
    words = [w.lower() for w in re.findall(r'[\w\xc3\xa4\xc3\xb6\xc3\xa5]+', norm)]
    bonus = 0
    high_value = set([c.lower() for _, c in FINNISH_PHONETIC_TARGETS]) | FINNISH_ONLY_INDICATORS
    for w in words:
        if w in high_value:
            bonus += 15
    return bonus, norm


def _detect_effective_language(normalized_text, google_lang_code):
    """
    Determines whether the user spoke Finnish ('fi') or English ('en').
    Even if Google STT tags a short Finnish utterance as 'en-US', switches to 'fi'
    when unmistakable Finnish words are present and no English sentence words exist.
    """
    if "fi" in to_utf8(google_lang_code).lower():
        return "fi"
    words = set(re.findall(r'[\w\xc3\xa4\xc3\xb6\xc3\xa5]+', to_utf8(normalized_text).lower()))
    has_fi_words = bool(words.intersection(FINNISH_ONLY_INDICATORS))
    has_en_words = bool(words.intersection(ENGLISH_SENTENCE_INDICATORS))
    if has_fi_words and not has_en_words:
        return "fi"
    return "en"


# ==================================================================
# Speech Recognition & AI Functions
# ==================================================================

def transcribe_audio_google(wav_bytes):
    """
    Transcribe complete utterance using Google Cloud Speech-to-Text.
    Supports English & Finnish simultaneously with heavy phrase biasing (boost=20.0),
    multi-alternative Finnish word scoring, and 3-stage phonetic normalization.
    """
    try:
        url = "https://speech.googleapis.com/v1/speech:recognize?key=" + GOOGLE_STT_KEY
        encoded = base64.b64encode(wav_bytes)
        payload = json.dumps({
            "config": {
                "encoding": "LINEAR16",
                "sampleRateHertz": SAMPLE_RATE,
                "languageCode": "en-US",
                "alternativeLanguageCodes": ["fi-FI"],
                "maxAlternatives": 3,
                "speechContexts": [{
                    "phrases": FINNISH_PHRASE_HINTS,
                    "boost": 20.0
                }]
            },
            "audio": {
                "content": encoded
            }
        })
        req = urllib2.Request(url, data=payload, headers={"Content-Type": "application/json"})
        resp = urllib2.urlopen(req, timeout=10)
        data = json.loads(resp.read())

        results = data.get("results", [])
        if not results:
            return "", "en"

        alternatives = results[0].get("alternatives", [{}])
        raw_transcript = to_utf8(alternatives[0].get("transcript", "")).strip()

        # Pick the best alternative (preferring alternatives that match our Finnish words collection)
        best_norm = normalize_finnish_words(raw_transcript)
        best_score = -1
        for idx, alt in enumerate(alternatives):
            cand_raw = to_utf8(alt.get("transcript", "")).strip()
            if not cand_raw:
                continue
            fi_bonus, cand_norm = _score_finnish_alternative(cand_raw)
            # Rank primary alternative slightly higher unless a secondary alternative caught a Finnish keyword
            total_score = fi_bonus - (idx * 5)
            if total_score > best_score:
                best_score = total_score
                best_norm = cand_norm

        transcript = best_norm
        lang = to_utf8(results[0].get("languageCode", "en-US"))
        lang_short = _detect_effective_language(transcript, lang)

        print("[Laurimate] Transcribed: '{}' (Normalized: '{}', Lang: {})".format(raw_transcript, transcript, lang_short))
        return transcript, lang_short
    except Exception as e:
        print("[Laurimate] STT Error: {}".format(e))
        return "", "en"


def ensure_complete_sentences(text, max_words=50):
    """
    Ensures answers stay strictly under ~50 words and NEVER cut off mid-sentence.
    Guarantees the text ends with complete sentences.
    """
    if not text:
        return ""
    clean = re.sub(r'[\*\_#`]', '', text).strip()
    words = clean.split()
    if not words:
        return ""

    # Find all sentence endings (. ! ?)
    matches = list(re.finditer(r'[\.\!\?](?:\s+|$)', clean))
    if not matches:
        return clean + "."

    # If within word limit and ends in punctuation, keep as-is
    if len(words) <= max_words and clean[-1] in ".!?":
        return clean

    # Pick the best sentence boundary that respects the word limit
    best_end = matches[0].end()
    for m in matches:
        sub = clean[:m.end()].strip()
        if len(sub.split()) <= max_words + 6:
            best_end = m.end()
        else:
            break

    result = clean[:best_end].strip()
    if result and result[-1] not in ".!?":
        result += "."
    return result


def query_groq_ai(question, context_text="", lang="en"):
    """
    Calls Groq API directly from Pepper via curl (handles modern SSL/TLS).
    Blazing fast (~200ms) with 14,400 free requests per day.
    """
    if not GROQ_API_KEY:
        return ""

    try:
        lang_name = u"Finnish" if lang == "fi" else u"English"
        live_weather = unicode(get_live_weather())
        live_time = unicode(get_live_time_str(lang))

        sys_prompt = (
            u"You are Laurimate, the friendly, intelligent campus assistant robot (SoftBank Pepper) "
            u"at Laurea University of Applied Sciences in Espoo, Finland. Created by Rakesh & Prasiddha.\n\n"
            u"CRITICAL CONVERSATION & LENGTH RULES:\n"
            u"1. STRICT 50-WORD LIMIT: Keep your total spoken answer strictly under 50 words.\n"
            u"2. COMPLETE SENTENCES ONLY: You must NEVER cut off mid-sentence or mid-thought. Every sentence must end with a full stop or question mark.\n"
            u"3. DO NOT CREATE LONG ANSWERS: Keep your response concise (1 to 2 spoken sentences). "
            u"If a topic requires more information or a longer response, provide the brief core answer first and ask: "
            u"'Would you like to know more about this?' (or in Finnish: 'Haluatko tietää tästä lisää?').\n"
            u"4. NEVER use bullet points, asterisks, markdown formatting, numbered lists, or emojis because you are speaking out loud.\n"
            u"5. Always speak in " + lang_name + u".\n"
            u"6. ANSWER ANY QUESTION, BUT ONLY WITH CORRECT INFORMATION. Use this order of trust: "
            u"(1) the REFERENCE SOURCES below (Laurea database first, then laurea.fi pages, then Wikipedia/web extracts), "
            u"(2) your own knowledge ONLY for well-established general facts you are certain about, simple explanations, maths, jokes and chit-chat.\n"
            u"7. For anything about Laurea or this campus (services, rooms, people, schedules, prices, rules, deadlines, contacts) use ONLY the reference sources. "
            u"Never guess Laurea details. Ignore sources that are not clearly relevant to the question.\n"
            u"8. If you are not sure the answer is correct, or the sources do not contain it, say so honestly: " + (u"'En valitettavasti tiedä tätä varmasti.'" if lang == "fi" else u"'Hmm, I am not sure about that one.'") + u" Never make something up.\n"
            u"9. Tell short, clean, family-friendly jokes when asked. Use the live date/time and weather below when asked. You are Laurimate, a Pepper robot created by Rakesh and Prasiddha.\n\n"
            u"LIVE ENVIRONMENT CONTEXT:\n"
            u"- Current Local Date & Time: " + live_time + u"\n"
            u"- Current Weather in Leppavaara, Espoo: " + live_weather + u"\n"
            u"- Campus Location: Vanha maantie 9, Leppavaara, 02650 Espoo.\n\n"
        )
        if context_text:
            if isinstance(context_text, str):
                context_text = context_text.decode("utf-8", "ignore")
            sys_prompt += u"REFERENCE SOURCES (database first, then laurea.fi, then web):\n" + unicode(context_text) + u"\n\n"

        if isinstance(question, str):
            question_u = question.decode("utf-8", "ignore")
        else:
            question_u = unicode(question)

        payload_obj = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": question_u}
            ],
            "temperature": 0.1,
            "max_tokens": 140
        }
        payload = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")

        cmd = [
            "curl", "-k", "-s", "--max-time", "8", "-X", "POST",
            "https://api.groq.com/openai/v1/chat/completions",
            "-H", "Content-Type: application/json",
            "-H", "User-Agent: curl/7.68.0",
            "-H", "Authorization: Bearer " + GROQ_API_KEY,
            "-d", "@-"
        ]

        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate(input=payload)
        data = json.loads(out)

        raw_content = data["choices"][0]["message"]["content"]
        if isinstance(raw_content, unicode):
            raw_content = raw_content.encode("utf-8", "ignore")
        clean_reply = ensure_complete_sentences(raw_content, max_words=50)
        print("[Laurimate] Groq AI ({}) -> '{}'".format(GROQ_MODEL, clean_reply[:80]))
        return clean_reply
    except Exception as e:
        print("[Laurimate] Groq Error: {}".format(e))
        return ""


def query_gemini_ai(question, context_text="", lang="en"):
    """
    Direct Gemini API call if user provided GEMINI_API_KEY.
    """
    if not GEMINI_API_KEY:
        return ""
    try:
        lang_name = "Finnish" if lang == "fi" else "English"
        live_weather = get_live_weather()
        live_time = get_live_time_str(lang)

        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=" + GEMINI_API_KEY
        sys_prompt = (
            "You are Laurimate, the campus assistant robot at Laurea University of Applied Sciences in Espoo, Finland. "
            "Created by Rakesh & Prasiddha.\n"
            "CRITICAL RULES:\n"
            "- STRICT 50-WORD LIMIT: Keep your response strictly under 50 words in 1 to 2 spoken sentences.\n"
            "- COMPLETE SENTENCES ONLY: Never cut off mid-thought; every sentence must finish completely with punctuation.\n"
            "- DO NOT CREATE LONG ANSWERS: If a topic needs a longer response, answer the key question first and ask: "
            "'Would you like to know more about this?' (or in Finnish: 'Haluatko tietää tästä lisää?').\n"
            "- Never use asterisks, markdown, or emojis. Speak in " + lang_name + ".\n"
            "- Answer any question, but ONLY with correct information. Trust order: 1) the Reference Sources below (Laurea database, then laurea.fi, then Wikipedia/web), 2) your own knowledge only for facts you are certain about, jokes and chit-chat.\n"
            "- For Laurea/campus matters use ONLY the Reference Sources; never guess. Ignore irrelevant sources.\n"
            "- If you are not sure it is correct, reply honestly: " + ("'En valitettavasti tiedä tätä varmasti.'" if lang == "fi" else "'Sorry, I am not certain about that.'") + " Never make things up.\n"
            "Live Time: " + live_time + " | Live Espoo Weather: " + live_weather + "\n"
        )
        if context_text:
            sys_prompt += "Reference Sources:\n" + context_text + "\n"

        payload = json.dumps({
            "contents": [
                {"role": "user", "parts": [{"text": sys_prompt + "\nUser question: " + question}]}
            ],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 140}
        })
        req = urllib2.Request(url, data=payload, headers={"Content-Type": "application/json"})
        resp = urllib2.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        clean_reply = ensure_complete_sentences(reply, max_words=50)
        print("[Laurimate] Gemini AI -> '{}'".format(clean_reply[:80]))
        return clean_reply
    except Exception as e:
        print("[Laurimate] Gemini Error: {}".format(e))
        return ""


# ------------------------------------------------------------------
# Conversation memory: remembered until the start/welcome page returns
# ------------------------------------------------------------------
conversation_history = []      # list of (user_text, assistant_text)
MAX_HISTORY_TURNS = 8


def clear_conversation_memory():
    del conversation_history[:]
    print("[Laurimate] Conversation memory cleared.")


def _history_text(max_turns=6):
    if not conversation_history:
        return u""
    lines = []
    for q, a in conversation_history[-max_turns:]:
        lines.append(u"User: " + (q.decode("utf-8", "ignore") if isinstance(q, str) else q))
        lines.append(u"Laurimate: " + (a.decode("utf-8", "ignore") if isinstance(a, str) else a))
    return u"\n".join(lines)


def _resolve_followup(question, lang="en"):
    """Turns a short follow-up ('another one', 'and in Finnish?', 'why?') into a standalone question."""
    if not conversation_history:
        return question
    if len(question.split()) > 10:
        return question
    sys_txt = (
        u"Rewrite the user's LAST message as a complete standalone question or request, using the conversation for context. "
        u"Resolve words like 'another', 'again', 'one more', 'it', 'that', 'there', 'why', 'and you?'. "
        u"If the user asks for 'another'/'one more' of something (joke, fact, riddle...), make clear it must be DIFFERENT from the earlier one. "
        u"If the message is already standalone, output it unchanged. Output ONLY the rewritten message, nothing else, in the user's language."
    )
    user_txt = u"CONVERSATION:\n" + _history_text(4) + u"\n\nLAST MESSAGE: " + (question.decode("utf-8", "ignore") if isinstance(question, str) else question)
    out = _llm_chat(sys_txt, user_txt, 120)
    out = to_utf8(out).strip().strip('"')
    if out and len(out) < 300:
        if out != question:
            print("[Laurimate] Follow-up resolved: '{}' -> '{}'".format(question, out))
        return out
    return question


def _llm_chat(system_text, user_text, max_tokens=220):
    """One AI call (Groq first, then Gemini). Returns raw text or ''."""
    if isinstance(system_text, str):
        system_text = system_text.decode("utf-8", "ignore")
    if isinstance(user_text, str):
        user_text = user_text.decode("utf-8", "ignore")
    if GROQ_API_KEY:
        try:
            payload = json.dumps({
                "model": GROQ_MODEL,
                "messages": [{"role": "system", "content": system_text}, {"role": "user", "content": user_text}],
                "temperature": 0.1,
                "reasoning_effort": "low",
                "max_tokens": max(max_tokens, 1200)
            }, ensure_ascii=False).encode("utf-8")
            cmd = ["curl", "-k", "-s", "--max-time", "10", "-X", "POST",
                   "https://api.groq.com/openai/v1/chat/completions",
                   "-H", "Content-Type: application/json", "-H", "User-Agent: curl/7.68.0",
                   "-H", "Authorization: Bearer " + GROQ_API_KEY, "-d", "@-"]
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out, _ = p.communicate(input=payload)
            content = json.loads(out)["choices"][0]["message"]["content"]
            if isinstance(content, unicode):
                content = content.encode("utf-8", "ignore")
            if content and content.strip():
                return content.strip()
        except Exception as e:
            print("[Laurimate] Groq call error: {}".format(e))
    if GEMINI_API_KEY:
        try:
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=" + GEMINI_API_KEY
            payload = json.dumps({
                "contents": [{"role": "user", "parts": [{"text": system_text + u"\n\n" + user_text}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": max(max_tokens, 700)}
            })
            req = urllib2.Request(url, data=payload, headers={"Content-Type": "application/json"})
            data = json.loads(urllib2.urlopen(req, timeout=10).read())
            txt = data["candidates"][0]["content"]["parts"][0]["text"]
            if isinstance(txt, unicode):
                txt = txt.encode("utf-8", "ignore")
            return txt.strip()
        except Exception as e:
            print("[Laurimate] Gemini call error: {}".format(e))
    return ""


def _uncertain_msg(lang):
    if lang == "fi":
        return "Hmm, en ole varma tästä. Anteeksi!"
    return "Hmm, I'm not sure about that one, sorry!"


def _hedged_answer(question, draft, lang):
    """If the AI already has a real answer, return it directly and naturally; only say 'not sure' if draft had no answer."""
    low = draft.lower()
    if (not draft) or any(k in low for k in ["not sure", "don't know", "do not know", "no idea", "en tied", "en ole varma"]):
        return _uncertain_msg(lang)
    return ensure_complete_sentences(draft, max_words=50)


def _persona_block(lang):
    lang_name = u"Finnish" if lang == "fi" else u"English"
    return (
        u"You are Laurimate, a warm, witty, friendly campus assistant robot (SoftBank Pepper) at Laurea University of Applied Sciences in Espoo, Finland, "
        u"created by Rakesh and Prasiddha. Speak in " + lang_name + u". Talk like a natural, friendly person having a chat: casual, direct, no stiff phrases "
        u"like 'according to my database', 'reliable source', or 'as an AI'. Spoken style: under 50 words, 1 to 2 complete sentences, no markdown, bullet points or emojis. "
        u"For small talk (e.g. 'what are you doing?', 'how are you?') reply naturally and playfully, like 'Just hanging out and waiting to help you, what's up?'.\n"
        u"LIVE CONTEXT: Helsinki date/time: " + unicode(get_live_time_str(lang)) + u" | Weather in Leppavaara: " + unicode(get_live_weather()) + u"\n"
        + ((u"RECENT CONVERSATION (use it to understand follow-ups; never repeat a joke or answer you already gave):\n" + _history_text() + u"\n") if conversation_history else u"")
    )


def answer_with_ai_then_verify(question, lang="en"):
    """
    1) AI drafts a natural answer.
    2) If the AI is confident (needs_verification=False), return it immediately.
    3) If it needs a web check (e.g. AI is unsure or specific Laurea website info), search using clean keywords.
       If web sources provide a clear answer/correction, use it; otherwise keep the AI's natural draft.
    """
    draft_sys = _persona_block(lang) + (
        u"TASK: Answer the user's question naturally and accurately. Reply ONLY with a JSON object, no other text:\n"
        u'{"answer": "<natural spoken answer>", "needs_verification": true or false, "search_query": "<2-5 core keywords for web search, no filler words>"}\n'
        u"Set needs_verification to FALSE when you know the answer confidently and it does not change over time "
        u"(small talk, jokes, maths, capitals, science, history, definitions, or LIVE CONTEXT date/time/weather).\n"
        u"Set needs_verification to TRUE when the answer can change over time (current presidents, prime ministers, office holders, "
        u"current events, prices, records), when you are not 100% sure, or when it is a specific Laurea detail not in the database.\n"
        u"Never invent facts, and NEVER say 'I don't have a reliable source'."
    )
    raw = _llm_chat(draft_sys, question, 260)
    if not raw:
        return ""
    answer, needs, search_q = raw, False, ""
    m = re.search(r'\{.*\}', raw, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            answer = to_utf8(obj.get("answer", "")).strip()
            needs = bool(obj.get("needs_verification", False))
            search_q = to_utf8(obj.get("search_query", "")).strip()
        except Exception:
            pass
    answer = ensure_complete_sentences(answer, max_words=50)
    print("[Laurimate] AI draft (verify={}): {}".format(needs, answer[:90]))
    if not answer:
        return ""
    if not needs:
        return answer

    if not search_q:
        search_q = " ".join([w for w in re.findall(r'\w+', question) if w.lower() not in STOP_WORDS and len(w) > 2][:5]) or question
    print("[Laurimate] Verifying with search: '{}'".format(search_q))
    sources = gather_web_sources(search_q)
    if not sources:
        return _hedged_answer(question, answer, lang)

    verify_sys = _persona_block(lang) + (
        u"TASK: You are given a QUESTION, a DRAFT ANSWER and web SOURCES. Rules:\n"
        u"- If the sources clearly answer the question or correct the draft, output a natural spoken answer using the sources.\n"
        u"- If the sources are unrelated/unhelpful, output the DRAFT ANSWER as-is (unless the draft says 'I am not sure', in which case output NOT_VERIFIED).\n"
        u"- NEVER mention sources, searching, or 'reliable source'. Output only the final spoken answer (or NOT_VERIFIED)."
    )
    verify_user = (
        u"QUESTION: " + (question.decode("utf-8", "ignore") if isinstance(question, str) else question) + u"\n\nDRAFT ANSWER: " + answer.decode("utf-8", "ignore") +
        u"\n\nSOURCES:\n" + u"\n\n".join([s.decode("utf-8", "ignore") for s in sources])
    )
    verdict = _llm_chat(verify_sys, verify_user, 220)
    if not verdict or "NOT_VERIFIED" in verdict:
        return _hedged_answer(question, answer, lang)
    final = ensure_complete_sentences(verdict, max_words=50)
    print("[Laurimate] Verified answer: {}".format(final[:90]))
    return final


def answer_from_database_with_ai(question, campus_context, lang="en"):
    """Takes raw facts from campus.json and uses the AI to format them into a natural spoken answer."""
    if not campus_context:
        return ""
    sys_txt = _persona_block(lang) + (
        u"TASK: Take the data from the CAMPUS.JSON DATABASE ENTRIES (and CORE CAMPUS FACTS) below and format it into a clear, "
        u"natural, conversational spoken answer to the user's question.\n"
        u"- The database entries are written as short notes (for example: \"Connect to 'eduroam' network. Use username@laurea.fi and your Laurea password.\" "
        u"or \"About 7-8 min walk (~600m).\"). Do NOT read short fragments verbatim — rewrite and combine the relevant facts into 1 to 2 smooth, natural spoken sentences "
        u"(for example: \"The Wi-Fi SSID is the eduroam network, and you can log in using your student email and password.\").\n"
        u"- Use ONLY the facts from the database entries below; do not invent details.\n"
        u"- Do NOT say 'according to the database'.\n"
        u"- ONLY if the user's question is NOT answered by any of the database entries or core campus facts below, output exactly: NO_DB_MATCH"
    )
    q_u = question.decode("utf-8", "ignore") if isinstance(question, str) else unicode(question)
    ctx_u = campus_context.decode("utf-8", "ignore") if isinstance(campus_context, str) else unicode(campus_context)
    user_txt = CORE_CAMPUS_FACTS + u"\n\nMATCHED CAMPUS.JSON ENTRIES:\n" + ctx_u + u"\n\nUSER QUESTION: " + q_u
    out = _llm_chat(sys_txt, user_txt, 220)
    if not out or "NO_DB_MATCH" in out:
        return ""
    reply = ensure_complete_sentences(out, max_words=50)
    print("[Laurimate] Formatted campus.json answer via AI -> '{}'".format(reply[:90]))
    return reply


def get_answer_for_question(question, lang="en"):
    """Conversation-aware entry point: resolves follow-ups, answers, then remembers the exchange."""
    standalone = _resolve_followup(question, lang)
    answer, source = _answer_core(standalone, lang)
    conversation_history.append((to_utf8(question), to_utf8(answer)))
    del conversation_history[:-MAX_HISTORY_TURNS]
    return answer, source


def _answer_core(question, lang="en"):
    """
    Master Answering Pipeline:
      1. Instant Cache for greetings (<50ms)
      2. Check campus.json first -> AI formats raw campus.json data into a natural answer
      3. General AI + web verification if not in campus.json
      4. Offline fallbacks
    """
    clean_q = re.sub(r'[^\w\s]', '', question).lower().strip()

    # 1. Instant Cache
    if clean_q in INSTANT_CACHE:
        return INSTANT_CACHE[clean_q], "faq"

    # 2. Check campus.json FIRST (1,650 campus Q&As) and format with AI
    campus_context = campus_db.get_context(question, top_k=8)
    if campus_context:
        db_reply = answer_from_database_with_ai(question, campus_context, lang)
        if db_reply:
            return db_reply, "faq"
        # If AI API failed/offline, return best direct database match
        match, _ = campus_db.get_best_match(question)
        if match and not GROQ_API_KEY and not GEMINI_API_KEY:
            return match[1], "faq"
        print("[Laurimate] campus.json entries were not relevant to '{}' -> falling back to general AI".format(question))

    # 3. General AI (with web verification when needed)
    reply = answer_with_ai_then_verify(question, lang)
    if reply:
        return reply, "ai"
    # 5. Direct Weather question check without AI
    if any(w in clean_q for w in ["weather", "sää", "temperature", "lumi", "rain", "cold", "warm"]):
        weather_info = get_live_weather()
        if lang == "fi":
            return "Täällä Leppävaarassa sää on tällä hetkellä: " + weather_info + ".", "weather"
        else:
            return "Currently in Leppävaara, the weather is " + weather_info + ".", "weather"

    # 6. Direct Time question check without AI
    if any(w in clean_q for w in ["time", "kello", "aika", "date", "päivä"]):
        time_info = get_live_time_str(lang)
        if lang == "fi":
            return "Nyt on " + time_info + ".", "time"
        else:
            return "The current time is " + time_info + ".", "time"

    # 7. Conversational Database Fallback
    match, score = campus_db.get_best_match(question)
    if match:
        matched_q, matched_a = match
        print("[Laurimate] Local DB Match (Score {}): {}".format(score, matched_a[:60]))
        return matched_a, "faq"

    # 8. Friendly General Fallback
    if lang == "fi":
        return (
            "En valitettavasti tiedä tätä.",
            "faq"
        )
    else:
        return (
            "Sorry, I do not have that information.",
            "faq"
        )


# ==================================================================
# Audio Voice Activity Detection (VAD) Listener
# ==================================================================

class SmoothAudioListener(ALModule):
    def __init__(self, name, tablet_proxy):
        ALModule.__init__(self, name)
        self.module_name = name
        self.tablet = tablet_proxy
        self.audio = ALProxy("ALAudioDevice", PEPPER_IP, PEPPER_PORT)
        try:
            self.tts_proxy = ALProxy("ALTextToSpeech", PEPPER_IP, PEPPER_PORT)
        except Exception:
            self.tts_proxy = None
        self.utterance_queue = Queue.Queue()

        self.muted = False
        self.pepper_speaking = False
        self.speaking_started_at = 0.0
        self.barge_in_echo_clear_until = 0.0
        self.tts_echo_floor = 5500.0
        self.barge_in_accum = 0.0
        self.barge_in_triggered = False

        self.is_recording = False
        self.noise_floor = 350.0

        self.preroll = collections.deque()
        self.preroll_duration = 0.0

        self.recorded_frames = []
        self.speech_start_accum = 0.0
        self.silence_accum = 0.0
        self.total_recorded_duration = 0.0

    def start(self):
        self.audio.setClientPreferences(self.module_name, SAMPLE_RATE, AUDIO_CHANNEL, 0)
        self.audio.subscribe(self.module_name)
        print("[Laurimate] Audio stream subscribed (16 kHz, Front Mic, Smart Barge-In active).")

    def stop(self):
        try:
            self.audio.unsubscribe(self.module_name)
            print("[Laurimate] Audio stream unsubscribed.")
        except Exception:
            pass

    def flush_queue(self):
        while not self.utterance_queue.empty():
            try:
                self.utterance_queue.get_nowait()
            except Exception:
                break

    def set_muted(self, muted):
        self.muted = muted
        if muted:
            self.pepper_speaking = False
            self.is_recording = False
            self.preroll.clear()
            self.preroll_duration = 0.0
            self.recorded_frames = []
            self.speech_start_accum = 0.0
            self.silence_accum = 0.0
            self.barge_in_accum = 0.0

    def set_pepper_speaking(self, speaking):
        """
        Enables/disables smart barge-in monitoring while Pepper is speaking an answer.
        Never stops answering unless someone speaks loudly and continuously right to Pepper.
        """
        if speaking:
            self.muted = False
            self.is_recording = False
            self.barge_in_triggered = False
            self.barge_in_accum = 0.0
            self.tts_echo_floor = 5500.0
            self.speaking_started_at = time.time()
            self.preroll.clear()
            self.preroll_duration = 0.0
            self.recorded_frames = []
            self.speech_start_accum = 0.0
            self.silence_accum = 0.0
            self.pepper_speaking = True
        else:
            self.pepper_speaking = False
            self.barge_in_accum = 0.0
            if not self.is_recording:
                self.preroll.clear()
                self.preroll_duration = 0.0
                self.speech_start_accum = 0.0
                self.silence_accum = 0.0

    def _is_voice_like_frame(self, buf, dur):
        """Checks zero-crossing rate to distinguish human voice from thumps, bumps, or clicks."""
        if dur <= 0:
            return False
        try:
            crossings_per_sec = float(audioop.cross(buf, 2)) / dur
            # Human speech fundamental + formants at 16kHz typically have 180..3200 zero-crossings/sec
            return 160.0 <= crossings_per_sec <= 3400.0
        except Exception:
            return True

    def processRemote(self, nbOfChannels, nbOfSamplesByChannel, timeStamp, inputBuffer):
        if self.muted:
            return

        now_ts = time.time()
        if now_ts < self.barge_in_echo_clear_until:
            return

        buf = str(inputBuffer)
        dur = float(nbOfChannels and nbOfSamplesByChannel) / float(SAMPLE_RATE)
        rms = audioop.rms(buf, 2)

        # --------------------------------------------------------------
        # Mode A: Pepper is currently speaking -> Barge-In on User Speech
        # --------------------------------------------------------------
        if self.pepper_speaking:
            elapsed_speaking = now_ts - self.speaking_started_at
            if elapsed_speaking < BARGE_IN_GRACE_S:
                self.tts_echo_floor = min(max(self.tts_echo_floor * 0.85 + 0.15 * float(rms), 4500.0), 7500.0)
                return

            barge_threshold = max(self.tts_echo_floor * 1.35, BARGE_IN_MIN_RMS)
            is_voice = self._is_voice_like_frame(buf, dur)

            if rms > barge_threshold and is_voice:
                self.barge_in_accum += dur
                if self.barge_in_accum >= BARGE_IN_SUSTAIN_S:
                    # Human speech interruption confirmed!
                    # Stop TTS immediately and ignore 0.25s of audio so Pepper's own TTS words
                    # are never recorded into the user's new question.
                    self.pepper_speaking = False
                    self.barge_in_triggered = True
                    self.barge_in_accum = 0.0
                    self.flush_queue()
                    self.preroll.clear()
                    self.preroll_duration = 0.0

                    if self.tts_proxy:
                        try:
                            self.tts_proxy.post.stopAll()
                        except Exception:
                            pass

                    self.barge_in_echo_clear_until = time.time() + 0.25
                    self.is_recording = True
                    self.silence_accum = -0.75
                    self.total_recorded_duration = 0.0
                    self.recorded_frames = []

                    set_listening(self.tablet)
                    print("[Laurimate] Instant Barge-In Detected (RMS={:.0f}, BargeThresh={:.0f}) -> Interrupting answer & listening!".format(
                        rms, barge_threshold
                    ))
            else:
                self.barge_in_accum = max(0.0, self.barge_in_accum - dur * 2.4)
                if rms < barge_threshold:
                    self.tts_echo_floor = 0.94 * self.tts_echo_floor + 0.06 * float(rms)
                    self.tts_echo_floor = min(max(self.tts_echo_floor, 4500.0), 7500.0)
            return

        # --------------------------------------------------------------
        # Mode B: Standard Idle / Full-Question Recording VAD
        #   Uses dual-threshold hysteresis so Pepper listens to the
        #   WHOLE question and never splits words mid-sentence!
        # --------------------------------------------------------------
        start_threshold = max(self.noise_floor * 2.3, 650.0)
        hold_threshold  = max(self.noise_floor * 1.45, 380.0)

        if not self.is_recording:
            self.noise_floor = 0.96 * self.noise_floor + 0.04 * float(rms)
            self.noise_floor = min(max(self.noise_floor, 150.0), 1200.0)

            self.preroll.append((buf, dur))
            self.preroll_duration += dur
            while self.preroll_duration > PREROLL_SECONDS and self.preroll:
                old_buf, old_dur = self.preroll.popleft()
                self.preroll_duration -= old_dur

            if rms > start_threshold and self._is_voice_like_frame(buf, dur):
                self.speech_start_accum += dur
                if self.speech_start_accum >= START_THRESHOLD_S:
                    self.is_recording = True
                    self.silence_accum = 0.0
                    self.total_recorded_duration = 0.0
                    self.recorded_frames = [b[0] for b in self.preroll]
                    for b in self.preroll:
                        self.total_recorded_duration += b[1]
                    set_listening(self.tablet)
                    print("[Laurimate] Speech detected (RMS={:.0f}, StartThresh={:.0f}) -> Listening to full question...".format(rms, start_threshold))
            else:
                self.speech_start_accum = max(0.0, self.speech_start_accum - dur * 1.5)

        else:
            self.recorded_frames.append(buf)
            self.total_recorded_duration += dur

            # Hysteresis: once speaking has started, any voice energy above hold_threshold resets silence timer
            if rms < hold_threshold:
                self.silence_accum += dur
            else:
                self.silence_accum = max(0.0, min(self.silence_accum, 0.0))

            if self.silence_accum >= SILENCE_TIMEOUT_S or self.total_recorded_duration >= MAX_RECORD_SEC:
                self.is_recording = False
                active_speech_dur = self.total_recorded_duration - max(0.0, self.silence_accum)

                if active_speech_dur >= MIN_SPEECH_SEC:
                    # Mute listener while Pepper is Thinking/Processing so room noises never cancel the answer!
                    self.muted = True
                    set_thinking(self.tablet)
                    print("[Laurimate] Full question complete ({:.1f}s speech) -> Processing...".format(active_speech_dur))
                    wav_data = self._pcm_to_wav("".join(self.recorded_frames))
                    self.utterance_queue.put(wav_data)
                else:
                    print("[Laurimate] Sound too short ({:.2f}s) -> Ignored.".format(active_speech_dur))
                    set_welcome(self.tablet)

                self.preroll.clear()
                self.preroll_duration = 0.0
                self.recorded_frames = []
                self.silence_accum = 0.0
                self.speech_start_accum = 0.0

    def _pcm_to_wav(self, pcm_bytes):
        out = StringIO.StringIO()
        w = wave.open(out, "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm_bytes)
        w.close()
        return out.getvalue()


# ==================================================================
# Main Conversation Controller
# ==================================================================

class LaurimateController(object):
    def __init__(self, tablet, listener):
        self.tablet = tablet
        self.listener = listener

        self.tts = ALProxy("ALTextToSpeech", PEPPER_IP, PEPPER_PORT)
        try:
            self.tts.setVolume(0.75)
        except Exception:
            pass
        self.animated_speech = ALProxy("ALAnimatedSpeech", PEPPER_IP, PEPPER_PORT)
        self.animation_player = ALProxy("ALAnimationPlayer", PEPPER_IP, PEPPER_PORT)
        try:
            self.motion = ALProxy("ALMotion", PEPPER_IP, PEPPER_PORT)
        except Exception:
            self.motion = None

        self.session_active = False
        self.idle_timer = None
        self.running = True
        self.recent_gestures = collections.deque(maxlen=6)

    def _pick_unique_gesture(self, pool):
        """Picks a gesture from pool without repeating any of the last 6 gestures used."""
        if not pool:
            return "animations/Stand/Gestures/Explain_1"
        if isinstance(pool, string_types):
            return pool
        fresh = [g for g in pool if g not in self.recent_gestures]
        chosen = random.choice(fresh if fresh else pool)
        self.recent_gestures.append(chosen)
        return chosen

    def _select_gesture_pool_for_sentence(self, sentence, question="", is_first=False, is_last=False):
        """
        Matches the exact meaning of a spoken sentence (plus question context)
        to the most natural Pepper hand sign category.
        """
        s_low = to_utf8(sentence).lower()
        q_low = to_utf8(question).lower()

        # 1. Farewells / Goodbyes
        if any(w in s_low for w in ["goodbye", "see you", "have a wonderful day", "näkemiin", "nähdään", "hei hei", "päivänjatkoa"]):
            return GESTURE_BYE

        # 2. Greetings / Hello
        if any(w in s_low for w in ["hello!", "hi there", "hey!", "moi!", "moikka!", "moro!", "hei!", "heippa!", "terve!", "huomenta"]):
            return GESTURE_HEY

        # 3. Self-reference / Robot identity ("I am Laurimate", "created by", "olen laurimate")
        if any(w in s_low for w in ["i am laurimate", "i'm laurimate", "olen laurimate", "my name", "created by", "luoneet minut", "kampusrobotti"]):
            return GESTURE_ME

        # 4. Uncertainty / Apologies / Don't know
        if any(w in s_low for w in ["not sure", "don't know", "do not have", "sorry", "en ole varma", "en valitettavasti", "anteeksi"]):
            return GESTURE_DONT_KNOW

        # 5. Weather / Sky / Temperature / Outdoors
        if any(w in s_low or w in q_low for w in ["weather", "sää", "degrees", "celsius", "cloudy", "sunny", "rain", "snow", "wind", "aste", "lämpötila"]):
            return GESTURE_SKY_WEATHER

        # 6. Food / Restaurant / Lunch / Coffee
        if any(w in s_low or w in q_low for w in ["lunch", "restaurant", "cafeteria", "canteen", "barlaurea", "food", "coffee", "menu", "lounas", "ravintola", "ruokala", "kahvila", "ruokalista"]):
            return GESTURE_FOOD

        # 7. Locations / Directions / Floors / Entrances / Transport
        if any(w in s_low or (is_first and w in q_low) for w in [
            "floor", "ground", "entrance", "stair", "elevator", "walk", "station", "located",
            "address", "vanha maantie", "building", "room", "library", "parking", "restroom", "toilet",
            "kerros", "sisäänkäynti", "kävely", "asema", "sijaitsee", "osoite", "kirjasto", "pysäköinti", "vessa"
        ]):
            return GESTURE_DIRECTION

        # 8. Digital / Apps / Tablet / Wi-Fi / Portals
        if any(w in s_low for w in ["tuudo", "pakki", "eduroam", "wi-fi", "wifi", "app", "website", "portal", "online", "password", "login", "verkkosivu", "sovellus"]):
            return GESTURE_SHOW

        # 9. Gratitude / Enthusiasm / Jokes / Positive Reactions
        if any(w in s_low or w in q_low for w in ["welcome!", "happy to help", "ole hyvä", "mielelläni", "joke", "vitsi", "funny", "great", "awesome", "wonderful", "congrat"]):
            return GESTURE_ENTHUSE

        # 10. Direct Affirmation ("Yes", "Of course", "Absolutely", "Kyllä")
        if any(s_low.startswith(w) for w in ["yes", "absolutely", "of course", "sure", "certainly", "kyllä", "totta kai"]):
            return GESTURE_YES

        # 11. Direct Negation ("No,", "Closed", "Ei,")
        if any(s_low.startswith(w) for w in ["no,", "no ", "unfortunately", "ei,", "ei "]) or "closed on weekends" in s_low:
            return GESTURE_NO

        # 12. Multiple items / Campuses / Lists / Numbers
        if any(w in s_low for w in ["campuses", "all ", "everything", "both", "several", "kampusta", "kaikki", "useita"]):
            return GESTURE_COUNT_ALL

        # 13. Questions & Invitations directed to the user ("How can I help you?", "Would you like to know more?")
        if s_low.endswith("?") or any(w in s_low for w in ["how can i help", "would you like", "let me know", "you can", "kuinka voin auttaa", "haluatko", "voit "]):
            return GESTURE_YOU

        # 14. Varied conversational storytelling & explaining
        if not is_first:
            return GESTURE_STORY + GESTURE_EXPLAIN
        return GESTURE_EXPLAIN

    def build_annotated_speech(self, question, answer, fallback_gesture=None):
        """
        Annotates every sentence (and long clause) of the answer with its own
        context-matched, non-repeating NAOqi hand gesture (^start / ^wait) so Pepper's
        hand signs flow naturally and match what it is saying throughout the entire answer.
        """
        clean_ans = to_utf8(answer).strip()
        if not clean_ans:
            return ""

        # Split answer into sentences while keeping punctuation
        raw_sentences = [s.strip() for s in re.findall(r'[^.!?]+[.!?]?', clean_ans) if s.strip()]
        if not raw_sentences:
            raw_sentences = [clean_ans]

        # If a single sentence is long (> 16 words) and has a comma/conjunction, split into 2 natural clauses
        segments = []
        for sent in raw_sentences:
            words = sent.split()
            if len(words) > 16 and ", " in sent:
                parts = sent.split(", ", 1)
                segments.append(parts[0] + ",")
                segments.append(parts[1])
            else:
                segments.append(sent)

        annotated_parts = []
        total = len(segments)
        for idx, seg in enumerate(segments):
            pool = self._select_gesture_pool_for_sentence(
                seg,
                question=question,
                is_first=(idx == 0),
                is_last=(idx == total - 1)
            )
            if idx == 0 and fallback_gesture and pool is GESTURE_EXPLAIN:
                pool = fallback_gesture
            g = self._pick_unique_gesture(pool)
            annotated_parts.append("^start({}) {}".format(g, seg))

        return " ".join(annotated_parts)

    def _reset_idle_timer(self):
        if self.idle_timer:
            self.idle_timer.cancel()
        self.idle_timer = threading.Timer(IDLE_SESSION_SEC, self._on_idle_timeout)
        self.idle_timer.daemon = True
        self.idle_timer.start()

    def _cancel_idle_timer(self):
        if self.idle_timer:
            self.idle_timer.cancel()
            self.idle_timer = None

    def _on_idle_timeout(self):
        self.session_active = False
        print("[Laurimate] Idle timeout ({}s) -> Returning to welcome screen.".format(IDLE_SESSION_SEC))
        clear_conversation_memory()
        set_welcome(self.tablet)

    def speak_and_show(self, question, answer, lang="en", source="ai", gesture=None):
        self._cancel_idle_timer()

        # 1. Enable smart barge-in mode (ignores Pepper's own voice & small noises,
        #    but interrupts immediately if a person speaks directly to Pepper)
        self.listener.set_pepper_speaking(True)

        # 2. Set TTS language
        if "fi" in lang.lower():
            try: self.tts.setLanguage("Finnish")
            except Exception: pass
        else:
            try: self.tts.setLanguage("English")
            except Exception: pass

        # 3. Update tablet UI
        set_answer(self.tablet, question, answer, source)

        # 4. Speak with multi-sentence natural hand gestures in an interruptible worker thread
        spoken_text = self.build_annotated_speech(question, answer, fallback_gesture=gesture)
        print("[Laurimate] Animated Speech with Natural Hand Signs: {}".format(spoken_text[:140]))

        def _do_speak():
            try:
                self.animated_speech.say(spoken_text)
            except Exception as e:
                if not self.listener.barge_in_triggered:
                    print("[Laurimate] Animated speech fallback: {}".format(e))
                    if gesture:
                        play_gesture_async(self.animation_player, gesture)
                    try:
                        self.tts.say(answer)
                    except Exception:
                        pass

        speech_th = threading.Thread(target=_do_speak)
        speech_th.daemon = True
        speech_th.start()

        last_head_lock = 0.0
        while speech_th.is_alive():
            if self.listener.barge_in_triggered or self.listener.is_recording:
                print("[Laurimate] Interrupted by user speech -> Stopping current answer immediately.")
                try:
                    self.tts.stopAll()
                except Exception:
                    pass
                try:
                    self.animation_player.stopAll()
                except Exception:
                    pass
                break
            # Keep head looking straight forward and UP (-0.35 rad = ~20 deg up) at the person speaking,
            # overriding any gesture timeline that tries to drop the head down or turn it sideways.
            now_t = time.time()
            if self.motion and (now_t - last_head_lock) >= 0.25:
                last_head_lock = now_t
                try:
                    self.motion.setAngles(["HeadYaw", "HeadPitch"], [0.0, -0.35], 0.15)
                except Exception:
                    pass
            time.sleep(0.04)

        # If interrupted by real user speech, listener is already recording the new question; exit right away!
        if self.listener.barge_in_triggered or self.listener.is_recording:
            if self.motion:
                try:
                    self.motion.setAngles(["HeadYaw", "HeadPitch"], [0.0, -0.35], 0.15)
                except Exception:
                    pass
            self.session_active = True
            return

        # 5. Normal completion: gently lock head looking UP at front person while still muted, then wait 0.45s for motors/echo to settle
        self.listener.set_muted(True)
        try:
            self.motion.setAngles(["HeadYaw", "HeadPitch"], [0.0, -0.35], 0.14)
        except Exception:
            pass
        time.sleep(0.45)
        self.listener.set_pepper_speaking(False)
        self.listener.set_muted(False)

        # 6. Session stays alive
        self.session_active = True
        self._reset_idle_timer()

    def select_gesture(self, text):
        words = set(re.findall(r'[\w\xc3\xa4\xc3\xb6\xc3\xa5]+', to_utf8(text).lower()))
        if words.intersection(["where", "missä", "location", "find", "room", "kartta"]):
            return GESTURE_SHOW
        elif words.intersection(["how", "miten", "why", "miksi", "explain", "kerro"]):
            return GESTURE_EXPLAIN
        elif words.intersection(["thank", "thanks", "kiitos", "great", "hyvä", "loistava"]):
            return GESTURE_ENTHUSE
        elif words.intersection(["yes", "joo", "kyllä"]):
            return GESTURE_YES
        elif words.intersection(["no", "ei"]):
            return GESTURE_NO
        return GESTURE_EXPLAIN

    def run_loop(self):
        print("[Laurimate] Controller running. Listening for user speech...")
        noise_words = set(["for", "the", "a", "an", "to", "in", "of", "and", "or", "uh", "um", "oh", "hmm", "it", "is"])
        while self.running:
            try:
                wav_bytes = self.listener.utterance_queue.get(timeout=1.0)
            except Queue.Empty:
                continue

            # 1. Transcribe audio with Google Cloud STT
            transcript, lang = transcribe_audio_google(wav_bytes)

            if not transcript or transcript.lower().strip() in noise_words:
                print("[Laurimate] No meaningful speech detected in utterance ('{}').".format(transcript))
                set_no_speech(self.tablet)
                time.sleep(1.0)
                if not self.session_active:
                    set_welcome(self.tablet)
                self.listener.set_muted(False)
                continue

            # 2. Show user question on tablet
            set_transcript(self.tablet, transcript)

            # 3. Get AI answer using database context + live weather/time
            answer, source = get_answer_for_question(transcript, lang)

            # 4. Select gesture & respond (unmutes into smart barge-in mode while speaking)
            gesture = self.select_gesture(transcript)
            self.speak_and_show(transcript, answer, lang, source, gesture)


# ==================================================================
# Entrypoint
# ==================================================================

def main():
    global LaurimateAudioInstance

    print("==================================================")
    print(" Laurimate Campus Assistant - Groq & Campus AI")
    print("==================================================")

    # 1. Start NAOqi broker
    broker = ALBroker("LaurimateBroker", "0.0.0.0", 0, PEPPER_IP, PEPPER_PORT)

    # 2. Motion wake-up
    motion = ALProxy("ALMotion", PEPPER_IP, PEPPER_PORT)
    try:
        motion.wakeUp()
        print("[Laurimate] Robot woken up — motors enabled.")
    except Exception as e:
        print("[Laurimate] Could not wake robot: {}".format(e))

    # 3. Disable AutonomousLife tablet screensaver hijack, keep natural awareness & speaking movement
    try:
        auto_life = ALProxy("ALAutonomousLife", PEPPER_IP, PEPPER_PORT)
        if auto_life.getState() != "disabled":
            auto_life.setState("disabled")
        print("[Laurimate] Autonomous life disabled (prevents Pepper screensaver from hiding tablet UI).")
    except Exception as e:
        print("[Laurimate] Autonomous life note: {}".format(e))

    # Stop startapplaunchertablet screensaver daemon if running so it never overrides our webview
    try:
        os.system("pkill -f '[s]tartapplaunchertablet.py' >/dev/null 2>&1")
    except Exception:
        pass

    # Re-ensure robot is standing awake after disabling AutonomousLife
    try:
        motion.wakeUp()
        posture = ALProxy("ALRobotPosture", PEPPER_IP, PEPPER_PORT)
        posture.goToPosture("StandInit", 0.5)
    except Exception as e:
        print("[Laurimate] Posture note: {}".format(e))

    # Stop ALBasicAwareness from swinging Pepper's head sideways to random room sounds/movements,
    # and instead run a smooth front-only head controller focused on the people directly in front.
    try:
        awareness = ALProxy("ALBasicAwareness", PEPPER_IP, PEPPER_PORT)
        awareness.stopAwareness()
        print("[Laurimate] Side-sound head wandering disabled — keeping head focused on front people.")
    except Exception as e:
        print("[Laurimate] Basic awareness note: {}".format(e))

    def _front_focused_head_loop():
        """
        Keeps Pepper's head looking straight forward (HeadYaw = 0.0) and UP (HeadPitch = -0.35 rad, ~20 deg up)
        toward the standing person's face without wandering left/right or moving motors during quiet listening.
        """
        target_yaw = 0.0
        target_pitch = -0.35
        try:
            motion.setStiffnesses("Head", 0.80)
            motion.setAngles(["HeadYaw", "HeadPitch"], [target_yaw, target_pitch], 0.14)
        except Exception:
            pass

        while True:
            time.sleep(1.5)
            if os.path.exists("/tmp/laurimate_kids_webview_v6.flag"):
                continue
            try:
                angles = motion.getAngles(["HeadYaw", "HeadPitch"], True)
                # If any animation lowered the head or turned it sideways, restore front upward eye contact
                if abs(angles[0] - target_yaw) > 0.08 or abs(angles[1] - target_pitch) > 0.08:
                    if not LaurimateAudioInstance or LaurimateAudioInstance.pepper_speaking or LaurimateAudioInstance.muted or abs(angles[1] - target_pitch) > 0.12:
                        motion.setAngles(["HeadYaw", "HeadPitch"], [target_yaw, target_pitch], 0.12)
            except Exception:
                pass

    head_th = threading.Thread(target=_front_focused_head_loop)
    head_th.daemon = True
    head_th.start()

    try:
        speaking_move = ALProxy("ALSpeakingMovement", PEPPER_IP, PEPPER_PORT)
        speaking_move.setEnabled(True)
        # Use 'random' mode so Pepper continuously blends smooth BodyTalk gestures between our explicit ^start() hand signs
        speaking_move.setMode("random")
        anim_speech_cfg = ALProxy("ALAnimatedSpeech", PEPPER_IP, PEPPER_PORT)
        anim_speech_cfg.setBodyLanguageModeFromStr("random")
        print("[Laurimate] Natural continuous speaking hand movement enabled.")
    except Exception as e:
        print("[Laurimate] Speaking movement note: {}".format(e))

    # 4. Tablet setup + Permanent Anti-Screensaver Heartbeat Watchdog (Port 8766)
    tablet = None
    try:
        import BaseHTTPServer
        tablet_state = {"last_ping": time.time()}

        class TabletPingHandler(BaseHTTPServer.BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return
            def do_GET(self):
                tablet_state["last_ping"] = time.time()
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write("OK")

        def _serve_ping():
            try:
                httpd = BaseHTTPServer.HTTPServer(("0.0.0.0", 8766), TabletPingHandler)
                httpd.serve_forever()
            except Exception:
                pass

        ping_th = threading.Thread(target=_serve_ping)
        ping_th.daemon = True
        ping_th.start()

        tablet = ALProxy("ALTabletService", PEPPER_IP, PEPPER_PORT)
        try:
            bm = ALProxy("ALBehaviorManager", PEPPER_IP, PEPPER_PORT)
            for bhv in bm.getDefaultBehaviors():
                try: bm.removeDefaultBehavior(bhv)
                except Exception: pass
            for bhv in bm.getRunningBehaviors():
                if "laurimate" not in bhv.lower():
                    try: bm.stopBehavior(bhv)
                    except Exception: pass
        except Exception:
            pass
        try:
            at = ALProxy("_ALAutonomousTablet", PEPPER_IP, PEPPER_PORT)
            at.setEnabled(False)
        except Exception:
            pass
        try:
            tablet.wakeUp()
            tablet._setPreventCommandScreenOff(True)
            tablet._stopAnimation()
        except Exception:
            pass
        url_with_cache_bust = "{}?t={}".format(TABLET_URL_BASE, int(time.time()))
        tablet.showWebview(url_with_cache_bust)
        tablet_state["last_ping"] = time.time()
        print("[Laurimate] Tablet active: {}".format(url_with_cache_bust))
        set_welcome(tablet)

        def _tablet_keepalive_watchdog():
            """Continuously locks WebView layer on top of Pepper's bubble screensaver without reloading."""
            while True:
                time.sleep(2.0)
                if os.path.exists("/tmp/laurimate_kids_webview_v6.flag"):
                    tablet_state["last_ping"] = time.time()
                    continue
                try:
                    # 0-arg showWebview() + _stopAnimation() keeps the webview layer in front
                    # of the OpenGL bubble screensaver with ZERO page reloads!
                    tablet._stopAnimation()
                    tablet.showWebview()
                except Exception:
                    pass
                if (time.time() - tablet_state["last_ping"]) > 6.5:
                    try:
                        try:
                            tablet.wakeUp()
                        except Exception:
                            pass
                        t_url = "{}?t={}".format(TABLET_URL_BASE, int(time.time()))
                        print("[Laurimate] Tablet heartbeat lost (screensaver/boot) -> Re-opening tablet UI...")
                        tablet.showWebview(t_url)
                        tablet_state["last_ping"] = time.time()
                        time.sleep(1.2)
                        set_welcome(tablet)
                    except Exception:
                        pass

        tb_thread = threading.Thread(target=_tablet_keepalive_watchdog)
        tb_thread.daemon = True
        tb_thread.start()
    except Exception as e:
        print("[Laurimate] Tablet note: {}".format(e))

    # 5. Initialize Smooth Audio VAD Listener
    LaurimateAudioInstance = SmoothAudioListener("LaurimateAudioInstance", tablet)
    LaurimateAudioInstance.start()

    # 6. Initialize Controller
    controller = LaurimateController(tablet, LaurimateAudioInstance)

    # 7. Initial greeting
    tts = ALProxy("ALTextToSpeech", PEPPER_IP, PEPPER_PORT)
    anim_player = ALProxy("ALAnimationPlayer", PEPPER_IP, PEPPER_PORT)
    play_gesture_async(anim_player, GESTURE_WAVE)
    LaurimateAudioInstance.set_muted(True)
    tts.say("Hello! I am Laurimate, your campus assistant. How can I help you?")
    time.sleep(0.3)
    LaurimateAudioInstance.set_muted(False)
    set_welcome(tablet)

    print("[Laurimate] Listening smoothly. Ready for questions.")

    try:
        controller.run_loop()
    except KeyboardInterrupt:
        print("\n[Laurimate] Shutting down...")
    finally:
        controller.running = False
        if LaurimateAudioInstance:
            LaurimateAudioInstance.stop()
        if tablet:
            try: tablet.hideWebview()
            except Exception: pass
        broker.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
