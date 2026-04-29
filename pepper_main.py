# -*- coding: utf-8 -*-
"""
Laurimate - Campus Assistant
SoftBank Pepper | NAOqi | Python 2.7

Flow:
  1. ALSpeechRecognition (broad vocab + word-spotting) detects ANY speech
  2. Speech detected  ->  pause recognizer  ->  start ALAudioRecorder
  3. Record for RECORD_SECONDS seconds (full utterance captured)
  4. Stop recorder  ->  send WAV to Google Speech-to-Text  ->  full transcript
  5. Transcript POSTed to Firebase / Gemini  ->  natural answer
  6. ALTextToSpeech speaks  +  ALTabletService updates UI
  7. Resume recognizer  ->  ready for next question
"""

import sys
import time
import json
import base64
import urllib2
import threading
import random
import threading
import re

from naoqi import ALProxy, ALModule, ALBroker

# ------------------------------------------------------------------
# Python 2 unicode safety
# ------------------------------------------------------------------
try:
    string_types = (str, unicode)
except NameError:
    string_types = (str,)

# ------------------------------------------------------------------
# Config  —  edit before deploying
# ------------------------------------------------------------------
PEPPER_IP         = "192.168.0.118"
PEPPER_PORT       = 9559
TABLET_URL_BASE   = "http://198.18.0.1/apps/laurimate-1e47c7/index.html"
FIREBASE_URL      = "https://chatwithgemini-wfqmz3bdja-uc.a.run.app"
GOOGLE_STT_KEY  = "AIzaSyBf23uxEGc9upLpirqrdtnfUPKD5um5sDY"   # <-- paste your key here

AUDIO_PATH        = "/tmp/laurimate_input.wav" # temp WAV on robot
AUDIO_CHUNK_A     = "/tmp/laurimate_chunk_a.wav" # alternating chunk files
AUDIO_CHUNK_B     = "/tmp/laurimate_chunk_b.wav"
SAMPLE_RATE       = 16000                       # Hz — Pepper front mic
CHUNK_DURATION    = 2.0   # seconds per live-transcription chunk
MIN_RECORD_SEC    = 1.0   # always record at least this long
MAX_RECORD_SEC    = 600   # essentially infinite — record until silence
SILENCE_TIMEOUT   = 1.5   # seconds of continuous silence before stopping
STT_LANGUAGE      = "fi-FI"                     # Primary language (Finnish)
# ------------------------------------------------------------------
# Gesture configuration
# ------------------------------------------------------------------
# Built-in animation paths (posture = Stand for Pepper)
GESTURE_HEY       = ["animations/Stand/Gestures/Hey_1", "animations/Stand/Gestures/Hey_4", "animations/Stand/Gestures/Hey_6"]
GESTURE_WAVE      = ["animations/Stand/Gestures/Hey_3", "animations/Stand/Gestures/Hey_1"]
GESTURE_BYE       = ["animations/Stand/Gestures/Hey_2"]
GESTURE_YES       = ["animations/Stand/Gestures/Yes_1", "animations/Stand/Gestures/Yes_2", "animations/Stand/Gestures/Yes_3"]
GESTURE_NO        = ["animations/Stand/Gestures/No_1", "animations/Stand/Gestures/No_3", "animations/Stand/Gestures/No_8", "animations/Stand/Gestures/No_9"]
GESTURE_EXPLAIN   = ["animations/Stand/Gestures/Explain_1", "animations/Stand/Gestures/Explain_2", "animations/Stand/Gestures/Explain_3", "animations/Stand/Gestures/Explain_4", "animations/Stand/Gestures/Explain_5", "animations/Stand/Gestures/Explain_6", "animations/Stand/Gestures/Explain_7", "animations/Stand/Gestures/Explain_8"]
GESTURE_THINK     = ["animations/Stand/Gestures/Thinking_1", "animations/Stand/Gestures/Thinking_3", "animations/Stand/Gestures/Thinking_4"]
GESTURE_SHOW      = ["animations/Stand/Gestures/ShowTablet_1", "animations/Stand/Gestures/ShowTablet_2", "animations/Stand/Gestures/ShowTablet_3"]
GESTURE_ENTHUSE   = ["animations/Stand/Gestures/Enthusiastic_4", "animations/Stand/Gestures/Enthusiastic_5"]
# Map trigger words → specific gesture path (for instant responses)
GREETING_GESTURES = {
    "hello":        GESTURE_WAVE,
    "hi":           GESTURE_WAVE,
    "hey":          GESTURE_WAVE,
    "hey laurimate": GESTURE_HEY,
    "ello":         GESTURE_HEY,
    "llo":          GESTURE_HEY,
    "ey":           GESTURE_WAVE,
    "hey lauri":    GESTURE_HEY,
    "hey laura":    GESTURE_HEY,
    "i":            GESTURE_HEY,
    "thank you":    GESTURE_YES,
    "thanks":       GESTURE_YES,
    "bye":          GESTURE_BYE,
    "goodbye":      GESTURE_BYE,
    "see you":      GESTURE_BYE,
}

# Instant responses — bypass STT + Firebase for speed (<100 ms)
INSTANT_CACHE = {
    "hello":        "Hello, I'm listening.",
    "hi":           "Hi there, how can I help?",
    "hey":          "Hey! What's your question?",
    "hey laurimate": "Yes, I am here.",
    
    # Aliases for mispronunciations / variants
    "ello":         "Hello, I'm listening.",
    "llo":          "Hello, I'm listening.",
    "ey":           "Hey! What's your question?",
    "hey lauri":    "Yes, I am here.",
    "hey laura":    "Yes, I am here.",
    "i":            "Yes, I am listening.",

    "thank you":    "You are welcome!",
    "thanks":       "Happy to help!",
    "bye":          "Goodbye!",
    "goodbye":      "See you later!",
    "see you":      "Take care!",
}

GOOGLE_STT_URL  = (
    "https://speech.googleapis.com/v1/speech:recognize?key=" + GOOGLE_STT_KEY
)

# ------------------------------------------------------------------
# Broad vocabulary — used ONLY as a trigger to detect any speech.
# Google STT handles the actual transcription so this list just needs
# to be wide enough that word-spotting fires when the user speaks.
# ------------------------------------------------------------------
TRIGGER_VOCAB = [
    # common openers (English)
    "hello", "hi", "hey", "excuse me", "sorry", "hey laurimate",
    "ello", "llo", "ey", "hey lauri", "hey laura",
    "what", "where", "when", "how", "who", "why", "is", "are", "can",
    "do", "does", "tell", "show", "help", "i", "the", "a",
    # common openers (Finnish)
    "hei", "moi", "terve", "huomenta", "anteeksi", "laurimate",
    "mitä", "missä", "milloin", "miten", "kuka", "miksi", "onko", "voitko",
    "kerro", "näytä", "auta", "minä", "se",
    # campus topics
    "wifi", "internet", "library", "canteen", "food", "toilet",
    "bathroom", "room", "classroom", "bus", "parking", "emergency",
    "student", "printing", "password", "card", "schedule", "exam",
    "moodle", "campus", "laurea", "laptop", "computer",
    "kirjasto", "ruokala", "vessa", "luokka", "bussi", "pysäköinti",
    # farewells
    "thank", "thanks", "bye", "goodbye", "kiitos", "hei hei", "näkemiin",
]

# NAOqi global (required by NAOqi event system)
LaurimateModule = None


# ==================================================================
# Google Speech-to-Text
# ==================================================================

def transcribe_audio(wav_path):
    """
    Read WAV file, base64-encode, POST to Google STT.
    Returns transcript string or None.
    """
    try:
        with open(wav_path, "rb") as f:
            audio_bytes = f.read()

        # Skip very short / silent recordings
        if len(audio_bytes) < 5000:
            print("[Laurimate] Audio too short — likely silence.")
            return None

        encoded = base64.b64encode(audio_bytes)

        payload = json.dumps({
            "config": {
                "encoding":        "LINEAR16",
                "sampleRateHertz": SAMPLE_RATE,
                "languageCode":    STT_LANGUAGE,
                "alternativeLanguageCodes": ["en-US"],
                "model":           "default",
                "speechContexts": [{
                    "phrases": [
                        "laurimate", "laurea", "leppävaara", "campus", "wifi",
                        "minä", "mitä", "missä", "milloin", "ruokala", "kirjasto",
                        "vessa", "opiskelija", "tietokone", "moi", "hei", "terve"
                    ]
                }]
            },
            "audio": {
                "content": encoded
            }
        })

        req = urllib2.Request(
            GOOGLE_STT_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        resp   = urllib2.urlopen(req, timeout=15)
        data   = json.loads(resp.read())
        results = data.get("results", [])

        if not results:
            print("[Laurimate] STT: no speech in audio.")
            return None

        alt        = results[0].get("alternatives", [{}])[0]
        transcript = alt.get("transcript", "").strip()
        if isinstance(transcript, unicode):
            transcript = transcript.encode("utf-8")
            
        confidence = alt.get("confidence", 0.0)
        lang_code  = results[0].get("languageCode", STT_LANGUAGE)
        print("[Laurimate] STT transcript: '{}' ({:.0%} - {})".format(transcript, confidence, lang_code))
        return (transcript, lang_code) if transcript else (None, lang_code)

    except urllib2.URLError as e:
        print("[Laurimate] STT network error: {}".format(e))
        return (None, STT_LANGUAGE)
    except Exception as e:
        print("[Laurimate] STT error: {}".format(e))
        return None


# ==================================================================
# Firebase / Gemini
# ==================================================================

def ask_firebase(question):
    """POST full transcript to Firebase, return (reply, source)."""
    try:
        if isinstance(question, unicode):
            question = question.encode("utf-8")
        print("[Laurimate] -> Firebase: '{}'".format(question))
        payload = json.dumps({"message": question})
        req = urllib2.Request(
            FIREBASE_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        resp   = urllib2.urlopen(req, timeout=15)
        data   = json.loads(resp.read())
        reply  = data.get("reply", u"").strip()
        source = data.get("source", "gemini")
        if isinstance(reply, unicode):
            reply = reply.encode("utf-8")
        print("[Laurimate] <- Firebase: {}".format(reply[:80]))
        return (reply if reply else None), source
    except urllib2.URLError as e:
        print("[Laurimate] Firebase network error: {}".format(e))
        return None, None
    except Exception as e:
        print("[Laurimate] Firebase error: {}".format(e))
        return None, None


# ==================================================================
# Tablet helpers
# ==================================================================

def set_listening(tablet):
    if tablet:
        try: tablet.executeJS("showListening();")
        except Exception: pass

def set_thinking(tablet):
    if tablet:
        try: tablet.executeJS("showThinking();")
        except Exception: pass

def set_no_speech(tablet):
    if tablet:
        try: tablet.executeJS("showNoSpeech();")
        except Exception: pass

def set_transcript(tablet, transcript):
    """Show user's transcribed question on tablet immediately."""
    if tablet:
        try:
            t_js = transcript.replace("\\", "\\\\").replace("'", "\\'")
            tablet.executeJS("showTranscript('{}');".format(t_js))
        except Exception: pass

def set_live_text(tablet, text):
    """Show live-building transcript on tablet while user is still speaking."""
    if tablet:
        try:
            t_js = text.replace("\\", "\\\\").replace("'", "\\'")
            tablet.executeJS("showLiveText('{}');".format(t_js))
        except Exception: pass

def play_gesture(animation_player, gesture_path):
    """Run a gesture animation in a background thread (non-blocking)."""
    if not gesture_path: return
    if isinstance(gesture_path, list):
        gesture_path = random.choice(gesture_path)

    def _run():
        try:
            animation_player.run(gesture_path)
        except Exception as e:
            print("[Laurimate] Gesture '{}' error: {}".format(gesture_path, e))
    t = threading.Thread(target=_run)
    t.daemon = True
    t.start()

def say_and_show(tts, tablet, question, answer, source="ai",
                 gesture=None, animation_player=None, animated_speech=None):
    """
    Show answer on tablet and speak with body movement.
    Uses ALAnimatedSpeech (if provided) to ensure continuous movement
    throughout the response without locking the robot's arms.
    """
    if isinstance(answer, unicode):
        answer = answer.encode("utf-8")
    else:
        answer = str(answer)
    if isinstance(question, unicode):
        question = question.encode("utf-8")
    else:
        question = str(question)

    q_js = question.replace("\\", "\\\\").replace("'", "\\'")
    a_js = answer.replace("\\", "\\\\").replace("'", "\\'")

    if tablet:
        try:
            tablet.executeJS("showAnswer('{}', '{}', '{}');".format(q_js, a_js, source))
        except Exception as e:
            print("[Laurimate] Tablet JS error: {}".format(e))

    # Speak using ALAnimatedSpeech to prevent arm locking and enable continuous movement
    if animated_speech:
        if gesture:
            if isinstance(gesture, list):
                gesture = random.choice(gesture)
            text_to_say = "^start({}) {}".format(gesture, answer)
        else:
            text_to_say = answer
        animated_speech.say(text_to_say)
    else:
        # Fallback to older mechanism if animated_speech is not provided
        if gesture and animation_player:
            play_gesture(animation_player, gesture)
        tts.say(answer)
    # Session manager in _handle_speech will decide next tablet state


# ==================================================================
# NAOqi event module
# ==================================================================

class WordModule(ALModule):
    """
    Uses ALSpeechRecognition as a trigger ONLY.
    When any speech is detected, a background thread records audio,
    sends to Google STT, then forwards the full transcript to Firebase.
    """

    IDLE_TIMEOUT = 60   # seconds of silence before returning to welcome

    def __init__(self, name, tablet_proxy):
        ALModule.__init__(self, name)
        self.tablet         = tablet_proxy
        self.tts            = ALProxy("ALTextToSpeech",      PEPPER_IP, PEPPER_PORT)
        self.speech         = ALProxy("ALSpeechRecognition", PEPPER_IP, PEPPER_PORT)
        self.recorder       = ALProxy("ALAudioRecorder",     PEPPER_IP, PEPPER_PORT)
        self.memory         = ALProxy("ALMemory",            PEPPER_IP, PEPPER_PORT)
        self.motion         = ALProxy("ALMotion",            PEPPER_IP, PEPPER_PORT)
        self.animation      = ALProxy("ALAnimationPlayer",   PEPPER_IP, PEPPER_PORT)
        self.animated_speech = ALProxy("ALAnimatedSpeech",   PEPPER_IP, PEPPER_PORT)
        self.busy           = False   # prevent overlapping captures
        self.session_active = False   # True while in a conversation session
        self.idle_timer     = None    # threading.Timer for 60 s idle end

        # Wake up the robot — enables motor stiffness so it can move
        try:
            self.motion.wakeUp()
            print("[Laurimate] Robot woken up — motors enabled.")
        except Exception as e:
            print("[Laurimate] Could not wake up robot: {}".format(e))

        # Enable speaking movement (Pepper moves while talking)
        try:
            speaking_move = ALProxy("ALSpeakingMovement", PEPPER_IP, PEPPER_PORT)
            speaking_move.setEnabled(True)
            speaking_move.setMode("contextual")
            print("[Laurimate] Speaking movement enabled (contextual mode).")
        except Exception as e:
            print("[Laurimate] Could not enable speaking movement: {}".format(e))

    # ----------------------------------------------------------
    def _cancel_idle_timer(self):
        """Pause the idle countdown (used when Pepper is giving a long answer)."""
        if self.idle_timer:
            self.idle_timer.cancel()
            self.idle_timer = None
        print("[Laurimate] Idle timer paused during speech.")

    def _reset_idle_timer(self):
        """Cancel existing idle timer and start a fresh 60-second countdown."""
        if self.idle_timer:
            self.idle_timer.cancel()
        self.idle_timer = threading.Timer(self.IDLE_TIMEOUT, self._end_session)
        self.idle_timer.daemon = True
        self.idle_timer.start()
        print("[Laurimate] Idle timer reset — {} s to welcome screen.".format(self.IDLE_TIMEOUT))

    def _start_session(self):
        """Begin a new 1-minute conversation session."""
        self.session_active = True
        print("[Laurimate] Session started — {} s idle timeout active.".format(self.IDLE_TIMEOUT))
        self._reset_idle_timer()

    def _end_session(self):
        """Called by idle timer when 60 s of silence passes — return to welcome."""
        self.session_active = False
        self.idle_timer = None
        print("[Laurimate] Session ended — idle timeout reached. Returning to welcome.")
        if self.tablet:
            try: self.tablet.executeJS("showWelcome();")
            except Exception: pass

    # ----------------------------------------------------------
    def on_word_recognized(self, key, value):
        """NAOqi calls this on the WordRecognized event."""
        # Re-entry guard — if already processing, ignore new trigger
        if self.busy:
            return
        if not value or len(value) < 2:
            return

        # Find highest-confidence word in the result list
        pairs = []
        for i in range(0, len(value) - 1, 2):
            w = value[i]
            c = value[i + 1]
            if isinstance(w, string_types) and isinstance(c, float):
                pairs.append((re.sub(r'<[^>]*>', '', w).lower().strip(), c))

        if not pairs:
            return

        trigger_word, conf = max(pairs, key=lambda x: x[1])

        # Ignore genuine noise
        if conf < 0.10:
            return

        print("[Laurimate] Speech trigger: '{}' ({:.0%})".format(trigger_word, conf))

        # Start session on first word; reset idle timer if already active
        if not self.session_active:
            self._start_session()
        else:
            self._reset_idle_timer()

        # Hand off to a background thread so the NAOqi callback returns fast
        self.busy = True
        t = threading.Thread(target=self._handle_speech, args=(trigger_word,))
        t.daemon = True
        t.start()

    # ----------------------------------------------------------
    def _record_once(self):
        """
        Record one utterance using silence detection.
        Returns elapsed seconds, or -1 on error.
        """
        try:
            self.recorder.startMicrophonesRecording(
                AUDIO_PATH, "wav", SAMPLE_RATE, (0, 0, 1, 0)
            )
            elapsed       = 0.0
            poll_interval = 0.15
            
            # Track how long it has been since we LAST saw speech
            time_since_last_speech = 0.0

            while elapsed < MAX_RECORD_SEC and self.session_active:
                time.sleep(poll_interval)
                elapsed += poll_interval
                
                # Start evaluating silence only after MIN_RECORD_SEC
                if elapsed >= MIN_RECORD_SEC:
                    try:
                        speaking = self.memory.getData("SpeechDetected")
                    except Exception:
                        speaking = 1
                        
                    if speaking == 1:
                        # User is speaking right now — reset the silence completely
                        time_since_last_speech = 0.0
                    else:
                        # User is currently silent — accumulate time
                        time_since_last_speech += poll_interval
                        
                    # Stop if they've been continuously silent for the timeout duration
                    if time_since_last_speech >= SILENCE_TIMEOUT:
                        print("[Laurimate] Silence detected ({}s continuous), stopping.".format(SILENCE_TIMEOUT))
                        break

            self.recorder.stopMicrophonesRecording()
            print("[Laurimate] Recording complete ({:.1f}s).".format(elapsed))
            return elapsed
        except Exception as e:
            print("[Laurimate] Recording error: {}".format(e))
            try: self.recorder.stopMicrophonesRecording()
            except Exception: pass
            return -1

    # ----------------------------------------------------------
    def _record_live(self):
        """
        Record in 2-second chunks using two alternating WAV files.
        Each chunk is sent to Google STT in a background thread.
        Live transcript is shown on the tablet as it builds up.
        Returns the full accumulated transcript, or None.
        """
        paths = [AUDIO_CHUNK_A, AUDIO_CHUNK_B]
        accumulated = []          # list of transcribed chunk texts
        chunk_idx = 0
        silent_after_speech = 0   # consecutive empty chunks after speech
        prev_thread = None
        prev_result = [None]      # mutable container for thread return
        last_lang = STT_LANGUAGE

        # Ensure not already recording from a previous crashed session
        try:
            self.recorder.stopMicrophonesRecording()
        except Exception:
            pass

        # Start the FIRST chunk recording immediately
        path = paths[0]
        try:
            self.recorder.startMicrophonesRecording(path, "wav", SAMPLE_RATE, (0, 0, 1, 0))
        except Exception as e:
            print("[Laurimate] Initial chunk start error: {}".format(e))
            try: self.recorder.stopMicrophonesRecording()
            except Exception: pass
            time.sleep(0.2)
            try: self.recorder.startMicrophonesRecording(path, "wav", SAMPLE_RATE, (0, 0, 1, 0))
            except Exception: pass

        while self.session_active and chunk_idx < 30:
            time.sleep(CHUNK_DURATION)

            # Stop current chunk
            try: self.recorder.stopMicrophonesRecording()
            except Exception: pass

            # IMMEDIATELY start the next chunk to prevent audio gaps
            next_path = paths[(chunk_idx + 1) % 2]
            if chunk_idx + 1 < 30 and self.session_active:
                try:
                    self.recorder.startMicrophonesRecording(next_path, "wav", SAMPLE_RATE, (0, 0, 1, 0))
                except Exception as e:
                    print("[Laurimate] Next chunk start error: {}".format(e))

            # ---- Collect result from PREVIOUS chunk's STT ----
            if prev_thread is not None:
                prev_thread.join(timeout=5)
                res_transcript, res_lang = prev_result[0] if prev_result[0] else (None, STT_LANGUAGE)
                if res_transcript:
                    accumulated.append(res_transcript)
                    last_lang = res_lang
                    live_text = " ".join(accumulated)
                    set_live_text(self.tablet, live_text)
                    print("[Laurimate] Live: '{}'".format(live_text))
                    silent_after_speech = 0
                else:
                    if accumulated:
                        silent_after_speech += 1

            # ---- User stopped speaking? ----
            # Require 2 consecutive empty chunks (4s) before assuming user is done
            if silent_after_speech >= 2 and accumulated:
                print("[Laurimate] Silence after speech — done recording.")
                break

            # ---- Start STT for THIS chunk in background ----
            prev_result = [None]
            chunk_path = path   # capture for closure
            chunk_res = prev_result
            def _stt(p=chunk_path, r=chunk_res):
                r[0] = transcribe_audio(p)
            prev_thread = threading.Thread(target=_stt)
            prev_thread.daemon = True
            prev_thread.start()

            # Update path for the next loop iteration
            path = next_path
            chunk_idx += 1

        # ---- Collect last pending STT ----
        if prev_thread is not None:
            prev_thread.join(timeout=5)
            res_transcript, res_lang = prev_result[0] if prev_result[0] else (None, STT_LANGUAGE)
            if res_transcript:
                accumulated.append(res_transcript)
                last_lang = res_lang
                live_text = " ".join(accumulated)
                set_live_text(self.tablet, live_text)

        full = " ".join(accumulated).strip()
        return (full, last_lang) if full else (None, last_lang)

    # ----------------------------------------------------------
    def _handle_speech(self, trigger_word):
        """
        Background thread:
          0. Instant cache → speak, then drop straight into the recording loop
          1. Otherwise → live chunked recording with real-time STT display

        Recording loop (runs while session_active):
          a. Show listening on tablet
          b. Record in chunks with live STT → show text on tablet
          c. If transcript: Firebase → respond; if none: stay listening
          d. Reset idle timer after each response, loop back to (a)
        """
        try:
            # ---- 0. Instant cache — answer without going through STT ----
            instant = INSTANT_CACHE.get(trigger_word)
            if instant:
                print("[Laurimate] Instant cache hit for '{}'".format(trigger_word))
                gesture = GREETING_GESTURES.get(trigger_word)
                say_and_show(self.tts, self.tablet, trigger_word, instant, "faq",
                             gesture, self.animation, self.animated_speech)
                self._reset_idle_timer()

            # ---- Continuous recording loop ----
            while self.session_active:
                set_listening(self.tablet)

                transcript, lang = self._record_live()

                if not self.session_active:
                    break

                if not transcript:
                    print("[Laurimate] No speech in recording — staying in session.")
                    continue

                # Show final transcript + thinking state
                set_transcript(self.tablet, transcript)

                # Suspend idle timer so it doesn't timeout mid-response
                self._cancel_idle_timer()

                # Set TTS language based on STT detection
                if lang and "fi" in lang.lower():
                    try: self.tts.setLanguage("Finnish")
                    except: pass
                else:
                    try: self.tts.setLanguage("English")
                    except: pass

                reply, source = ask_firebase(transcript)
                if reply:
                    # Pick a contextual gesture for the start of long answers
                    resp_gesture = None
                    lower_t = transcript.lower()
                    if any(g in lower_t for g in ["where", "show", "find", "location"]):
                        resp_gesture = GESTURE_SHOW
                    elif any(g in lower_t for g in ["how", "explain", "what is", "tell me"]):
                        resp_gesture = GESTURE_EXPLAIN
                    elif any(g in lower_t for g in ["thank", "great", "good", "awesome"]):
                        resp_gesture = GESTURE_ENTHUSE
                    else:
                        resp_gesture = GESTURE_EXPLAIN  # default gesture for answers
                    say_and_show(self.tts, self.tablet, transcript, reply, source,
                                 resp_gesture, self.animation, self.animated_speech)
                else:
                    g = random.choice(GESTURE_NO) if isinstance(GESTURE_NO, list) else GESTURE_NO
                    self.animated_speech.say(
                        "^start({}) I am sorry, I could not reach my knowledge base. "
                        "Please try again or ask a staff member.".format(g)
                    )

                self._reset_idle_timer()
                # Loop immediately — start recording for the next follow-up

        finally:
            self.busy = False
            print("[Laurimate] Session loop ended — ready for next session.")


# ==================================================================
# Speech recognition setup
# ==================================================================

def setup_speech(speech):
    """Clean up any stale subscription then configure vocabulary."""

    # 1. Unsubscribe ALL existing subscribers — not just ours.
    #    NAOqi keeps the grammar alive as long as ANY subscriber exists.
    try:
        subs = speech.getSubscribersInfo()
        for sub in subs:
            name = sub[0] if isinstance(sub, (list, tuple)) else str(sub)
            try:
                speech.unsubscribe(name)
                print("[Laurimate] Unsubscribed stale subscriber: {}".format(name))
            except Exception:
                pass
    except Exception:
        # Fallback: just try our own name
        try:
            speech.unsubscribe("Laurimate")
            print("[Laurimate] Cleaned up stale Laurimate subscriber.")
        except Exception:
            pass

    try:
        speech.pause(True)
    except Exception:
        pass

    # 2. Set vocabulary — should succeed now that all subscribers are gone
    try:
        speech.setVocabulary(TRIGGER_VOCAB, True)
        print("[Laurimate] Vocabulary set successfully.")
    except RuntimeError as e:
        if "already exists" in str(e):
            print("[Laurimate] Grammar already loaded — reusing.")
        else:
            raise

    try:
        speech.pause(False)
    except Exception:
        pass


# ==================================================================
# Main
# ==================================================================

def main():
    global LaurimateModule

    # 1. NAOqi Broker
    broker = ALBroker("PythonBroker", "0.0.0.0", 0, PEPPER_IP, PEPPER_PORT)

    # 2. Wake up robot — MUST be done first so motors are stiffened
    motion = ALProxy("ALMotion", PEPPER_IP, PEPPER_PORT)
    try:
        motion.wakeUp()
        print("[Laurimate] Robot woken up — motors ON.")
    except Exception as e:
        print("[Laurimate] Could not wake robot: {}".format(e))

    # 2b. Enable autonomous life (basic awareness) so Pepper tracks people
    try:
        auto_life = ALProxy("ALAutonomousLife", PEPPER_IP, PEPPER_PORT)
        auto_life.setState("solitary")
        print("[Laurimate] Autonomous life set to 'solitary'.")
    except Exception as e:
        print("[Laurimate] Autonomous life not available: {}".format(e))

    # 2c. Enable speaking movement — Pepper moves arms/head while talking
    try:
        speaking_move = ALProxy("ALSpeakingMovement", PEPPER_IP, PEPPER_PORT)
        speaking_move.setEnabled(True)
        print("[Laurimate] Speaking movement ENABLED.")
    except Exception as e:
        print("[Laurimate] Speaking movement not available: {}".format(e))

    # 3. Tablet (optional)
    tablet = None
    try:
        tablet = ALProxy("ALTabletService", PEPPER_IP, PEPPER_PORT)
        url_with_cache_bust = "{}?t={}".format(TABLET_URL_BASE, int(time.time()))
        tablet.showWebview(url_with_cache_bust)
        print("[Laurimate] Tablet showing: {}".format(url_with_cache_bust))
    except Exception as e:
        print("[Laurimate] Tablet not available: {}".format(e))

    # 4. Create module
    LaurimateModule = WordModule("LaurimateModule", tablet)

    # 5. Set up speech recognition (trigger only)
    speech = ALProxy("ALSpeechRecognition", PEPPER_IP, PEPPER_PORT)
    setup_speech(speech)

    # 6. Subscribe to WordRecognized event
    memory = ALProxy("ALMemory", PEPPER_IP, PEPPER_PORT)
    memory.subscribeToEvent(
        "WordRecognized",
        "LaurimateModule",
        "on_word_recognized",
    )

    # 7. Start recognizer
    speech.subscribe("Laurimate")

    # 8. Welcome — play a wave gesture while speaking
    tts = ALProxy("ALTextToSpeech", PEPPER_IP, PEPPER_PORT)
    anim_player = ALProxy("ALAnimationPlayer", PEPPER_IP, PEPPER_PORT)
    if tablet:
        try: tablet.executeJS("showWelcome();")
        except Exception: pass

    speech.pause(True)
    # Fire wave gesture in background, then speak
    play_gesture(anim_player, GESTURE_HEY)
    tts.say("Hello! I am Laurimate, your campus assistant. How can I help you?")
    speech.pause(False)

    print("[Laurimate] Listening with Google Speech-to-Text. Press Ctrl+C to stop.")

    # 8. Keep alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Laurimate] Shutting down...")
    finally:
        try: memory.unsubscribeToEvent("WordRecognized", "LaurimateModule")
        except Exception: pass
        try: speech.unsubscribe("Laurimate")
        except Exception: pass
        if tablet:
            try: tablet.hideWebview()
            except Exception: pass
        broker.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()