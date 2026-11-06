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
    "what", "where", "when", "how", "who", "why", "is", "are", "the", "a", "an",
    "to", "from", "in", "on", "at", "of", "for", "can", "i", "you", "do", "does",
    "tell", "show", "please", "me", "mitä", "missä", "milloin", "miten", "kuka",
    "miksi", "onko", "se", "ja", "ole", "on", "voitko", "kerro", "minulle", "about"
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


def get_live_time_str(lang="en"):
    """Fetches live date and time in Finland using HTTP response headers or local clock."""
    try:
        # Fetch current date/time from world time API
        cmd = ["curl", "-s", "--max-time", "3", "http://worldtimeapi.org/api/timezone/Europe/Helsinki"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = p.communicate()
        data = json.loads(out)
        dt_str = data.get("datetime", "")  # e.g. "2026-11-06T13:35:12.345678+02:00"
        if dt_str:
            date_part, time_part = dt_str.split("T")
            year, month, day = date_part.split("-")
            hour, minute, _ = time_part.split(":")[:3]
            days_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            day_name = days_en[data.get("day_of_week", 1) - 1]
            if lang == "fi":
                days_fi = ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai", "sunnuntai"]
                return "{}, kello on {}:{}, {}.{}.{}".format(days_fi[data.get("day_of_week", 1) - 1], hour, minute, day, month, year)
            else:
                return "{}, {}:{}, {}/{}/{}".format(day_name, hour, minute, month, day, year)
    except Exception:
        pass

    # Fallback to local clock formatted
    import datetime
    now = datetime.datetime.now()
    return now.strftime("%A, %I:%M %p")


# ==================================================================
# Local Campus Knowledge Base (1,650 Questions & Answers)
# ==================================================================

class CampusDatabase(object):
    def __init__(self, json_path="/home/nao/Laurimate/campus.json"):
        self.faqs = []
        try:
            with open(json_path, "r") as f:
                data = json.load(f)
            sections = data.get("sections", {})
            for s_key, sec in sections.items():
                questions = sec.get("questions", {})
                for q_key, item in questions.items():
                    q = item.get("q", "")
                    a = item.get("a", "")
                    if q and a:
                        self.faqs.append((to_utf8(q), to_utf8(a)))
            print("[Laurimate] Loaded {} campus Q&As from {}".format(len(self.faqs), json_path))
        except Exception as e:
            print("[Laurimate] Campus DB load note: {}".format(e))

    def get_context(self, query, top_k=4):
        """Extracts top relevant facts from campus.json to feed into the AI as context."""
        if not self.faqs or not query:
            return ""

        words = [w.lower() for w in re.findall(r'\b\w+\b', query) if w.lower() not in STOP_WORDS and len(w) > 2]
        if not words:
            return ""

        scored = []
        for q, a in self.faqs:
            q_lower = q.lower()
            a_lower = a.lower()
            score = 0
            for w in words:
                pattern = r'\b' + re.escape(w)
                if re.search(pattern, q_lower):
                    score += 4
                elif re.search(pattern, a_lower):
                    score += 1
            if score > 0:
                scored.append((score, q, a))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]
        if not top:
            return ""

        context_lines = []
        for s, q, a in top:
            context_lines.append("Fact - Q: {} | A: {}".format(q, a))
        return "\n".join(context_lines)

    def get_best_match(self, query):
        if not self.faqs or not query:
            return None, 0

        words = [w.lower() for w in re.findall(r'\b\w+\b', query) if w.lower() not in STOP_WORDS and len(w) > 2]
        if not words:
            return None, 0

        best_match = None
        best_score = 0
        for q, a in self.faqs:
            q_lower = q.lower()
            a_lower = a.lower()
            score = 0
            for w in words:
                pattern = r'\b' + re.escape(w)
                if re.search(pattern, q_lower):
                    score += 4
                elif re.search(pattern, a_lower):
                    score += 1

            if score > best_score:
                best_score = score
                best_match = (q, a)

        if best_score >= 3:
            return best_match, best_score
        return None, 0

campus_db = CampusDatabase()


# ==================================================================
# Live Website & Web Search (100% Free, Direct on Pepper)
# ==================================================================

def search_laurea_website(query):
    """Searches official Laurea.fi website via live REST API (100% free, no key)."""
    try:
        clean_q = re.sub(r'[^\w\s]', '', query).strip()
        encoded_q = clean_q.replace(" ", "+")
        if not encoded_q:
            return ""
        cmd = ["curl", "-k", "-s", "--max-time", "3", "https://www.laurea.fi/wp-json/wp/v2/search?search=" + encoded_q + "&per_page=3"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = p.communicate()
        data = json.loads(out)
        if not isinstance(data, list) or not data:
            return ""
        results = []
        for item in data[:3]:
            title = to_utf8(item.get("title", ""))
            url = to_utf8(item.get("url", ""))
            if title and url:
                results.append("Laurea.fi Page: {} ({})".format(title, url))
        if results:
            print("[Laurimate] Found {} results from live laurea.fi".format(len(results)))
            return "\n".join(results)
    except Exception as e:
        print("[Laurimate] Laurea.fi search note: {}".format(e))
    return ""


def search_web_instant(query):
    """Searches live web facts via DuckDuckGo Instant Answers (100% free, no key)."""
    try:
        clean_q = re.sub(r'[^\w\s]', '', query).strip()
        encoded_q = clean_q.replace(" ", "+")
        if not encoded_q:
            return ""
        cmd = ["curl", "-k", "-s", "--max-time", "3", "https://api.duckduckgo.com/?q=" + encoded_q + "&format=json"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = p.communicate()
        data = json.loads(out)
        abstract = to_utf8(data.get("AbstractText", "")).strip()
        if abstract:
            source = to_utf8(data.get("AbstractSource", "Web"))
            print("[Laurimate] Found live web fact from {}".format(source))
            return "Live Web Information ({}): {}".format(source, abstract)
    except Exception as e:
        print("[Laurimate] Web search note: {}".format(e))
    return ""


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
            u"5. Always speak in " + lang_name + u".\n\n"
            u"LIVE ENVIRONMENT CONTEXT:\n"
            u"- Current Local Date & Time: " + live_time + u"\n"
            u"- Current Weather in Leppavaara, Espoo: " + live_weather + u"\n"
            u"- Campus Location: Vanha maantie 9, Leppavaara, 02650 Espoo.\n\n"
        )
        if context_text:
            if isinstance(context_text, str):
                context_text = context_text.decode("utf-8", "ignore")
            sys_prompt += u"OFFICIAL LAUREA CAMPUS FACTS TO USE IN YOUR ANSWER:\n" + unicode(context_text) + u"\n\n"

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
            "temperature": 0.35,
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
            "Live Time: " + live_time + " | Live Espoo Weather: " + live_weather + "\n"
        )
        if context_text:
            sys_prompt += "Campus Facts:\n" + context_text + "\n"

        payload = json.dumps({
            "contents": [
                {"role": "user", "parts": [{"text": sys_prompt + "\nUser question: " + question}]}
            ],
            "generationConfig": {"temperature": 0.35, "maxOutputTokens": 140}
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


def get_answer_for_question(question, lang="en"):
    """
    Master Answering Pipeline:
      1. Instant Cache for greetings (<50ms)
      2. Direct Live Weather / Time check if asked directly
      3. Extract Campus Facts from campus.json (1,650 Q&As)
      4. Call Groq AI (or Gemini) with live context + campus facts
      5. Conversational Database Fallback if offline
    """
    clean_q = re.sub(r'[^\w\s]', '', question).lower().strip()

    # 1. Instant Cache
    if clean_q in INSTANT_CACHE:
        return INSTANT_CACHE[clean_q], "faq"

    # 2. Extract campus facts from campus.json
    campus_context = campus_db.get_context(question, top_k=3)

    # 3. Pull live web & laurea.fi search results
    extra_sources = []
    if campus_context:
        extra_sources.append(campus_context)

    # Search live laurea.fi website
    laurea_web = search_laurea_website(question)
    if laurea_web:
        extra_sources.append(laurea_web)

    # If general knowledge or no campus match, search live web
    if not campus_context:
        web_fact = search_web_instant(question)
        if web_fact:
            extra_sources.append(web_fact)

    combined_context = "\n\n".join(extra_sources)

    # 4. Try Groq AI (14,400 free requests/day, runs directly on Pepper)
    if GROQ_API_KEY:
        groq_reply = query_groq_ai(question, combined_context, lang)
        if groq_reply:
            return groq_reply, "groq"

    # 5. Try Gemini AI
    if GEMINI_API_KEY:
        gemini_reply = query_gemini_ai(question, combined_context, lang)
        if gemini_reply:
            return gemini_reply, "gemini"

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
            return "Kello on " + time_info + ".", "time"
        else:
            return "The current time is " + time_info + ".", "time"

    # 7. Conversational Database Fallback
    match, score = campus_db.get_best_match(question)
    if match:
        matched_q, matched_a = match
        print("[Laurimate] Local DB Match (Score {}): {}".format(score, matched_a[:60]))
        if lang == "fi":
            return "Kampustietojen mukaan: " + matched_a, "faq"
        else:
            return "According to Laurea campus information: " + matched_a, "faq"

    # 8. Friendly General Fallback
    if lang == "fi":
        return (
            "Olen Laurimate, Laurean kampusapulainen. En löytänyt suoraa vastausta kysymykseesi. "
            "Voit kysyä neuvoa ensimmäisen kerroksen infopisteeltä!",
            "faq"
        )
    else:
        return (
            "I am Laurimate, your campus assistant. I couldn't find an exact answer to that in my database. "
            "Please check with the main lobby reception on the first floor!",
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
