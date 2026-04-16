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
SAMPLE_RATE       = 16000                       # Hz — Pepper front mic
MIN_RECORD_SEC    = 2.0   # always record at least this long
MAX_RECORD_SEC    = 600   # essentially infinite — record until silence
SILENCE_TIMEOUT   = 2.0   # seconds of continuous silence before stopping
STT_LANGUAGE      = "en-US"                     # "fi-FI" for Finnish

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
    # common openers — most questions start with one of these
    "hello", "hi", "hey", "excuse me", "sorry", "hey laurimate",
    "ello", "llo", "ey", "hey lauri", "hey laura",
    "what", "where", "when", "how", "who", "why", "is", "are", "can",
    "do", "does", "tell", "show", "help", "i", "the", "a",
    # campus topics
    "wifi", "internet", "library", "canteen", "food", "toilet",
    "bathroom", "room", "classroom", "bus", "parking", "emergency",
    "student", "printing", "password", "card", "schedule", "exam",
    "moodle", "campus", "laurea", "laptop", "computer",
    # farewells
    "thank", "thanks", "bye", "goodbye",
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
                "model":           "default",
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
        confidence = alt.get("confidence", 0.0)
        print("[Laurimate] STT transcript: '{}' ({:.0%})".format(transcript, confidence))
        return transcript if transcript else None

    except urllib2.URLError as e:
        print("[Laurimate] STT network error: {}".format(e))
        return None
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

def say_and_show(tts, tablet, question, answer, source="ai"):
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

    tts.say(answer)  # blocking — returns only when speech finishes
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
        self.busy           = False   # prevent overlapping captures
        self.session_active = False   # True while in a conversation session
        self.idle_timer     = None    # threading.Timer for 60 s idle end

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
            poll_interval = 0.2
            
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
    def _handle_speech(self, trigger_word):
        """
        Background thread:
          0. Instant cache → speak, then drop straight into the recording loop
          1. Otherwise → recording loop immediately (captures the trigger + rest of question)

        Recording loop (runs while session_active):
          a. Show listening on tablet
          b. Record until silence or MAX_RECORD_SEC
          c. STT → if transcript: Firebase → respond; if none: stay listening
          d. Reset idle timer after each response, loop back to (a)
        """
        try:
            # ---- 0. Instant cache — answer without going through STT ----
            instant = INSTANT_CACHE.get(trigger_word)
            if instant:
                print("[Laurimate] Instant cache hit for '{}'".format(trigger_word))
                say_and_show(self.tts, self.tablet, trigger_word, instant, "faq")
                self._reset_idle_timer()

            # ---- Note on VAD (Voice Activity Detection) ----
            # We explicitly do NOT pause ALSpeechRecognition here anymore.
            # If we pause it, NAOqi stops updating the "SpeechDetected" memory key,
            # which causes our silence-detection loop to always falsely detect silence.
            # overlapping word-spotter triggers are safely ignored by 'self.busy = True'.

            # ---- Continuous recording loop ----
            while self.session_active:
                set_listening(self.tablet)

                elapsed = self._record_once()
                if elapsed < 0:          # recording error
                    break
                if not self.session_active:  # idle timer fired during recording
                    break

                # Flush WAV to disk
                time.sleep(0.3)

                # Transcribe
                set_thinking(self.tablet)
                transcript = transcribe_audio(AUDIO_PATH)

                if not transcript:
                    # No speech detected — stay listening, idle timer handles session end
                    print("[Laurimate] No speech in recording — staying in session.")
                    continue

                # Got a real utterance — suspend idle timer so it doesn't timeout mid-speech
                self._cancel_idle_timer()

                reply, source = ask_firebase(transcript)
                if reply:
                    say_and_show(self.tts, self.tablet, transcript, reply, source)
                else:
                    self.tts.say(
                        "I am sorry, I could not reach my knowledge base. "
                        "Please try again or ask a staff member."
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

    # 2. Tablet (optional)
    tablet = None
    try:
        tablet = ALProxy("ALTabletService", PEPPER_IP, PEPPER_PORT)
        url_with_cache_bust = "{}?t={}".format(TABLET_URL_BASE, int(time.time()))
        tablet.showWebview(url_with_cache_bust)
        print("[Laurimate] Tablet showing: {}".format(url_with_cache_bust))
    except Exception as e:
        print("[Laurimate] Tablet not available: {}".format(e))

    # 3. Create module
    LaurimateModule = WordModule("LaurimateModule", tablet)

    # 4. Set up speech recognition (trigger only)
    speech = ALProxy("ALSpeechRecognition", PEPPER_IP, PEPPER_PORT)
    setup_speech(speech)

    # 5. Subscribe to WordRecognized event
    memory = ALProxy("ALMemory", PEPPER_IP, PEPPER_PORT)
    memory.subscribeToEvent(
        "WordRecognized",
        "LaurimateModule",
        "on_word_recognized",
    )

    # 6. Start recognizer
    speech.subscribe("Laurimate")

    # 7. Welcome
    tts = ALProxy("ALTextToSpeech", PEPPER_IP, PEPPER_PORT)
    if tablet:
        try: tablet.executeJS("showWelcome();")
        except Exception: pass

    speech.pause(True)
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