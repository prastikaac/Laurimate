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
MIN_RECORD_SEC    = 1.5   # always record at least this long
MAX_RECORD_SEC    = 10    # hard cap for very long questions
SILENCE_TIMEOUT   = 1.2  # seconds of silence before stopping early
STT_LANGUAGE      = "en-US"                     # "fi-FI" for Finnish

# Instant responses — bypass STT + Firebase for speed (<100 ms)
INSTANT_CACHE = {
    "hello":        "Hello! I am Laurimate, your campus assistant. How can I help you?",
    "hi":           "Hi there! How can I help you today?",
    "hey":          "Hey! What can I help you with?",
    "hey laurimate": "Yes, I am here! How can I help you?",
    "thank you":    "You are welcome! Is there anything else I can help you with?",
    "thanks":       "Happy to help! Let me know if you need anything else.",
    "bye":          "Goodbye! Have a wonderful day!",
    "goodbye":      "See you later! Have a great day!",
    "see you":      "Take care! Have a great day!",
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
    "hello", "hi", "hey", "excuse me", "sorry", "hey laurimate"
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
        print("[Laurimate] -> Firebase: '{}'".format(question))
        payload = json.dumps({"message": question})
        req = urllib2.Request(
            FIREBASE_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        resp   = urllib2.urlopen(req, timeout=15)
        data   = json.loads(resp.read())
        reply  = data.get("reply", "").strip()
        source = data.get("source", "gemini")
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

    tts.say(answer)


# ==================================================================
# NAOqi event module
# ==================================================================

class WordModule(ALModule):
    """
    Uses ALSpeechRecognition as a trigger ONLY.
    When any speech is detected, a background thread records audio,
    sends to Google STT, then forwards the full transcript to Firebase.
    """

    def __init__(self, name, tablet_proxy):
        ALModule.__init__(self, name)
        self.tablet   = tablet_proxy
        self.tts      = ALProxy("ALTextToSpeech",      PEPPER_IP, PEPPER_PORT)
        self.speech   = ALProxy("ALSpeechRecognition", PEPPER_IP, PEPPER_PORT)
        self.recorder = ALProxy("ALAudioRecorder",     PEPPER_IP, PEPPER_PORT)
        self.memory   = ALProxy("ALMemory",            PEPPER_IP, PEPPER_PORT)
        self.busy     = False   # prevent overlapping captures

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

        # Hand off to a background thread so the NAOqi callback returns fast
        self.busy = True
        t = threading.Thread(target=self._handle_speech, args=(trigger_word,))
        t.daemon = True
        t.start()

    # ----------------------------------------------------------
    def _handle_speech(self, trigger_word):
        """
        Background thread:
          0. Check instant cache  ->  speak immediately (no STT/Firebase)
          1. Pause speech recognizer
          2. Record with silence detection (stops early when user goes quiet)
          3. Google STT  ->  Firebase  ->  speak
          4. Resume recognizer
        """
        try:
            # ---- 0. Instant cache — answer greetings in <100 ms ----
            instant = INSTANT_CACHE.get(trigger_word)
            if instant:
                print("[Laurimate] Instant cache hit for '{}'".format(trigger_word))
                say_and_show(self.tts, self.tablet, trigger_word, instant, "faq")
                return

            # ---- 1. Pause recognizer, start recording ----
            self.speech.pause(True)
            set_listening(self.tablet)

            try:
                # Channel tuple: (left_ear, right_ear, front_mic, rear_mic)
                self.recorder.startMicrophonesRecording(
                    AUDIO_PATH, "wav", SAMPLE_RATE, (0, 0, 1, 0)
                )
                print("[Laurimate] Recording (max {}s, silence detection on)...".format(
                    MAX_RECORD_SEC))

                # ---- 2. Silence detection loop ----
                elapsed        = 0.0
                silence_secs   = 0.0
                poll_interval  = 0.3   # check every 300 ms

                while elapsed < MAX_RECORD_SEC:
                    time.sleep(poll_interval)
                    elapsed += poll_interval

                    # Only check for silence after the minimum record time
                    if elapsed >= MIN_RECORD_SEC:
                        try:
                            speaking = self.memory.getData("SpeechDetected")
                        except Exception:
                            speaking = 1  # assume still speaking on error

                        if speaking == 0:
                            silence_secs += poll_interval
                        else:
                            silence_secs = 0  # reset on new speech burst

                        if silence_secs >= SILENCE_TIMEOUT:
                            print("[Laurimate] Silence detected after {:.1f}s, stopping.".format(
                                elapsed))
                            break

                self.recorder.stopMicrophonesRecording()
                print("[Laurimate] Recording complete ({:.1f}s).".format(elapsed))

            except Exception as e:
                print("[Laurimate] Recording error: {}".format(e))
                self.speech.pause(False)
                return

            # Small pause so WAV file is fully flushed to disk
            time.sleep(0.3)

            # ---- 3. Transcribe with Google STT ----
            set_thinking(self.tablet)
            transcript = transcribe_audio(AUDIO_PATH)

            if not transcript:
                self.tts.say("Sorry, I did not catch that. Please try again.")
                return

            # ---- Ask Gemini via Firebase ----
            reply, source = ask_firebase(transcript)

            if reply:
                say_and_show(self.tts, self.tablet, transcript, reply, source)
            else:
                self.tts.say(
                    "I am sorry, I could not reach my knowledge base. "
                    "Please try again or ask a staff member."
                )

        finally:
            # Always resume the recognizer and clear busy flag
            try:
                self.speech.pause(False)
            except Exception:
                pass
            self.busy = False
            print("[Laurimate] Ready for next question.")


# ==================================================================
# Speech recognition setup
# ==================================================================

def setup_speech(speech):
    """Clean up any stale subscription then configure vocabulary."""
    try:
        speech.unsubscribe("Laurimate")
        print("[Laurimate] Cleaned up stale speech subscriber.")
    except Exception:
        pass
    try:
        speech.pause(True)
    except Exception:
        pass
    # wordSpottingEnabled=True fires even for words OUTSIDE the vocab
    speech.setVocabulary(TRIGGER_VOCAB, True)
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