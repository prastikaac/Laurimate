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
PEPPER_IP         = "192.168.0.118"
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

SAMPLE_RATE       = 16000     # 16 kHz front mic
AUDIO_CHANNEL     = 3         # 3 = Front microphone on Pepper's head
PREROLL_SECONDS   = 1.0       # Retain 1.0s audio before speech trigger
START_THRESHOLD_S = 0.12      # Speech must sustain 120ms to trigger
SILENCE_TIMEOUT_S = 0.85      # Silence duration before ending utterance
MIN_SPEECH_SEC    = 0.35      # Ignore clicks/bursts shorter than 350ms
MAX_RECORD_SEC    = 14.0      # Safety cutoff for long speech
IDLE_SESSION_SEC  = 60.0      # Return to welcome screen after 60s inactivity

# ------------------------------------------------------------------
# Gestures Configuration
# ------------------------------------------------------------------
GESTURE_HEY     = ["animations/Stand/Gestures/Hey_1", "animations/Stand/Gestures/Hey_4", "animations/Stand/Gestures/Hey_6"]
GESTURE_WAVE    = ["animations/Stand/Gestures/Hey_3", "animations/Stand/Gestures/Hey_1"]
GESTURE_BYE     = ["animations/Stand/Gestures/Hey_2"]
GESTURE_YES     = ["animations/Stand/Gestures/Yes_1", "animations/Stand/Gestures/Yes_2", "animations/Stand/Gestures/Yes_3"]
GESTURE_NO      = ["animations/Stand/Gestures/No_1", "animations/Stand/Gestures/No_3", "animations/Stand/Gestures/No_8"]
GESTURE_EXPLAIN = [
    "animations/Stand/Gestures/Explain_1", "animations/Stand/Gestures/Explain_2",
    "animations/Stand/Gestures/Explain_3", "animations/Stand/Gestures/Explain_4",
    "animations/Stand/Gestures/Explain_5", "animations/Stand/Gestures/Explain_6",
    "animations/Stand/Gestures/Explain_7", "animations/Stand/Gestures/Explain_8"
]
GESTURE_SHOW    = ["animations/Stand/Gestures/ShowTablet_1", "animations/Stand/Gestures/ShowTablet_2", "animations/Stand/Gestures/ShowTablet_3"]
GESTURE_ENTHUSE = ["animations/Stand/Gestures/Enthusiastic_4", "animations/Stand/Gestures/Enthusiastic_5"]

INSTANT_CACHE = {
    "hello":         "Hello! I am Laurimate, your campus assistant. How can I help you today?",
    "hi":            "Hi there! How can I help you?",
    "hey":           "Hey! What would you like to know about Laurea?",
    "hey laurimate": "Hello! I am here and listening.",
    "moi":           "Moi! Kuinka voin auttaa sinua tänään?",
    "hei":           "Hei! Mitä haluaisit tietää Laureasta?",
    "terve":         "Terve! Kuinka voin auttaa?",
    "thank you":     "You are warmly welcome!",
    "thanks":        "Happy to help!",
    "kiitos":        "Ole hyvä! Autan mielelläni.",
    "bye":           "Goodbye! Have a wonderful day at Laurea!",
    "goodbye":       "Goodbye! See you soon!",
    "näkemiin":      "Näkemiin! Hyvää päivänjatkoa Laureassa!",
    "hei hei":       "Hei hei! Nähdään taas!"
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
    "laurea", "laurimate", "campus", "espoo", "leppavaara", "leppävaara",
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
    "toilet": ["restroom", "toilet", "accessible"],
    "bathroom": ["restroom", "toilet", "accessible"],
    "wc": ["restroom", "toilet"],
    "canteen": ["restaurant", "lunch", "cafeteria", "menu", "tuudo"],
    "cafeteria": ["restaurant", "lunch", "cafeteria", "menu", "tuudo"],
    "food": ["restaurant", "lunch", "menu", "cafe", "tuudo"],
    "eat": ["restaurant", "lunch", "menu"],
    "train": ["station", "leppavaara", "walk", "hsl"],
    "bus": ["buses", "hsl", "terminal", "station"],
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

def set_welcome(tablet):
    if tablet:
        try: tablet.executeJS("showWelcome();")
        except Exception: pass

def set_listening(tablet):
    if tablet:
        try: tablet.executeJS("showListening();")
        except Exception: pass

def set_thinking(tablet):
    if tablet:
        try: tablet.executeJS("showThinking();")
        except Exception: pass

def set_transcript(tablet, transcript):
    if tablet and transcript:
        try:
            t_js = to_utf8(transcript).replace("\\", "\\\\").replace("'", "\\'")
            tablet.executeJS("showTranscript('{}');".format(t_js))
        except Exception: pass

def set_answer(tablet, question, answer, source="ai"):
    if tablet:
        try:
            q_js = to_utf8(question).replace("\\", "\\\\").replace("'", "\\'")
            a_js = to_utf8(answer).replace("\\", "\\\\").replace("'", "\\'")
            tablet.executeJS("showAnswer('{}', '{}', '{}');".format(q_js, a_js, source))
        except Exception: pass

def set_no_speech(tablet):
    if tablet:
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
# Finnish Speech Recognition Hints & Normalizer
# ==================================================================

FINNISH_PHRASE_HINTS = [
    "Laurea", "Laurimate", "Leppävaara", "Leppavaara", "Leppävaaran", "Leppävaarassa", "Leppävaaraan",
    "Tikkurila", "Tikurilla", "Tikkurilan", "Tikkurilassa", "Tikkurilaan",
    "Otaniemi", "Otaniemen", "Otaniemessä", "Otaniemeen",
    "Hyvinkää", "Hyvinkaa", "Hyvinkään", "Hyvinkäällä",
    "Porvoo", "Porvoon", "Porvoossa", "Lohja", "Lohjan", "Lohjalla",
    "Vanha maantie", "eduroam", "Tuudo", "Moodle", "Pakki",
    "kirjasto", "ruokala", "ravintola", "opintotoimisto", "vessa",
    "pysäköinti", "lukujärjestys", "opiskelija", "opiskelijakortti",
    "terve", "päivää", "huomenta", "kiitos", "näkemiin", "anteeksi",
    "moi", "hei", "mitä", "missä", "milloin", "miten", "kuka", "onko", "voitko"
]

FINNISH_CORRECTIONS = [
    (re.compile(r'\blep+[aä]?v[aä]+r[aä]+n?\b', re.I), "Leppävaara"),
    (re.compile(r'\btik+ur[il]+a+n?\b', re.I), "Tikkurila"),
    (re.compile(r'\b(laura|lauria|loria)\b', re.I), "Laurea"),
    (re.compile(r'\bhyvink[aä]{1,2}n?\b', re.I), "Hyvinkää"),
    (re.compile(r'\botan[ie]min?\b', re.I), "Otaniemi"),
    (re.compile(r'\bedu\s*ro[amn]{2,3}\b', re.I), "eduroam"),
    (re.compile(r'\btudo\b', re.I), "Tuudo"),
]

def normalize_finnish_words(text):
    if not text:
        return ""
    for pattern, replacement in FINNISH_CORRECTIONS:
        text = pattern.sub(replacement, text)
    return text


# ==================================================================
# Speech Recognition & AI Functions
# ==================================================================

def transcribe_audio_google(wav_bytes):
    """
    Transcribe complete utterance using Google Cloud Speech-to-Text.
    Supports English & Finnish simultaneously with heavy phrase biasing (boost=20.0).
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

        alt = results[0].get("alternatives", [{}])[0]
        raw_transcript = to_utf8(alt.get("transcript", "")).strip()
        lang = to_utf8(results[0].get("languageCode", "en-US"))
        lang_short = "fi" if "fi" in lang.lower() else "en"

        # Apply phonetic normalization for campus names
        transcript = normalize_finnish_words(raw_transcript)

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
                "max_tokens": max(max_tokens, 700)
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
        self.utterance_queue = Queue.Queue()

        self.muted = False
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
        print("[Laurimate] Audio stream subscribed (16 kHz, Front Mic).")

    def stop(self):
        try:
            self.audio.unsubscribe(self.module_name)
            print("[Laurimate] Audio stream unsubscribed.")
        except Exception:
            pass

    def set_muted(self, muted):
        self.muted = muted
        if muted:
            self.is_recording = False
            self.preroll.clear()
            self.preroll_duration = 0.0
            self.recorded_frames = []
            self.speech_start_accum = 0.0
            self.silence_accum = 0.0

    def processRemote(self, nbOfChannels, nbOfSamplesByChannel, timeStamp, inputBuffer):
        if self.muted:
            return

        buf = str(inputBuffer)
        dur = float(nbOfChannels and nbOfSamplesByChannel) / float(SAMPLE_RATE)
        rms = audioop.rms(buf, 2)

        threshold = max(self.noise_floor * 2.2, 550.0)

        if not self.is_recording:
            self.noise_floor = 0.96 * self.noise_floor + 0.04 * float(rms)
            self.noise_floor = min(max(self.noise_floor, 150.0), 1200.0)

            self.preroll.append((buf, dur))
            self.preroll_duration += dur
            while self.preroll_duration > PREROLL_SECONDS and self.preroll:
                old_buf, old_dur = self.preroll.popleft()
                self.preroll_duration -= old_dur

            if rms > threshold:
                self.speech_start_accum += dur
                if self.speech_start_accum >= START_THRESHOLD_S:
                    self.is_recording = True
                    self.silence_accum = 0.0
                    self.total_recorded_duration = 0.0
                    self.recorded_frames = [b[0] for b in self.preroll]
                    for b in self.preroll:
                        self.total_recorded_duration += b[1]
                    set_listening(self.tablet)
                    print("[Laurimate] Speech detected (RMS={:.0f}, Threshold={:.0f}) -> Listening...".format(rms, threshold))
            else:
                self.speech_start_accum = 0.0

        else:
            self.recorded_frames.append(buf)
            self.total_recorded_duration += dur

            if rms < threshold:
                self.silence_accum += dur
            else:
                self.silence_accum = 0.0

            if self.silence_accum >= SILENCE_TIMEOUT_S or self.total_recorded_duration >= MAX_RECORD_SEC:
                self.is_recording = False
                set_thinking(self.tablet)
                active_speech_dur = self.total_recorded_duration - self.silence_accum

                if active_speech_dur >= MIN_SPEECH_SEC:
                    print("[Laurimate] Utterance complete ({:.1f}s speech) -> Processing...".format(active_speech_dur))
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
        self.animated_speech = ALProxy("ALAnimatedSpeech", PEPPER_IP, PEPPER_PORT)
        self.animation_player = ALProxy("ALAnimationPlayer", PEPPER_IP, PEPPER_PORT)

        self.session_active = False
        self.idle_timer = None
        self.running = True

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

        # 1. Mute mic so Pepper never hears itself
        self.listener.set_muted(True)

        # 2. Set TTS language
        if "fi" in lang.lower():
            try: self.tts.setLanguage("Finnish")
            except Exception: pass
        else:
            try: self.tts.setLanguage("English")
            except Exception: pass

        # 3. Update tablet UI
        set_answer(self.tablet, question, answer, source)

        # 4. Speak with animated gestures
        try:
            if gesture:
                if isinstance(gesture, list):
                    gesture = random.choice(gesture)
                spoken_text = "^start({}) {}".format(gesture, answer)
            else:
                spoken_text = answer

            self.animated_speech.say(spoken_text)
        except Exception as e:
            print("[Laurimate] Animated speech fallback: {}".format(e))
            if gesture:
                play_gesture_async(self.animation_player, gesture)
            self.tts.say(answer)

        # 5. Settling delay before unmuting
        time.sleep(0.35)
        self.listener.set_muted(False)

        # 6. Session stays alive
        self.session_active = True
        self._reset_idle_timer()

    def select_gesture(self, text):
        lower = text.lower()
        if any(w in lower for w in ["where", "missä", "location", "find", "room", "kartta"]):
            return GESTURE_SHOW
        elif any(w in lower for w in ["how", "miten", "why", "miksi", "explain", "kerro"]):
            return GESTURE_EXPLAIN
        elif any(w in lower for w in ["thank", "kiitos", "great", "hyvä", "loistava"]):
            return GESTURE_ENTHUSE
        elif any(w in lower for w in ["yes", "joo", "kyllä"]):
            return GESTURE_YES
        elif any(w in lower for w in ["no", "ei"]):
            return GESTURE_NO
        return GESTURE_EXPLAIN

    def run_loop(self):
        print("[Laurimate] Controller running. Listening for user speech...")
        while self.running:
            try:
                wav_bytes = self.listener.utterance_queue.get(timeout=1.0)
            except Queue.Empty:
                continue

            # 1. Transcribe audio with Google Cloud STT
            transcript, lang = transcribe_audio_google(wav_bytes)

            if not transcript:
                print("[Laurimate] No speech detected in utterance.")
                set_no_speech(self.tablet)
                time.sleep(1.5)
                if not self.session_active:
                    set_welcome(self.tablet)
                continue

            # 2. Show user question on tablet
            set_transcript(self.tablet, transcript)

            # 3. Get AI answer using database context + live weather/time
            answer, source = get_answer_for_question(transcript, lang)

            # 4. Select gesture & respond
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

    # 3. Autonomous life & speaking movement
    try:
        auto_life = ALProxy("ALAutonomousLife", PEPPER_IP, PEPPER_PORT)
        auto_life.setState("solitary")
        print("[Laurimate] Autonomous life set to 'solitary'.")
    except Exception as e:
        print("[Laurimate] Autonomous life note: {}".format(e))

    try:
        speaking_move = ALProxy("ALSpeakingMovement", PEPPER_IP, PEPPER_PORT)
        speaking_move.setEnabled(True)
        speaking_move.setMode("contextual")
        print("[Laurimate] Contextual speaking movement enabled.")
    except Exception as e:
        print("[Laurimate] Speaking movement note: {}".format(e))

    # 4. Tablet setup
    tablet = None
    try:
        tablet = ALProxy("ALTabletService", PEPPER_IP, PEPPER_PORT)
        url_with_cache_bust = "{}?t={}".format(TABLET_URL_BASE, int(time.time()))
        tablet.showWebview(url_with_cache_bust)
        print("[Laurimate] Tablet active: {}".format(url_with_cache_bust))
        set_welcome(tablet)
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
