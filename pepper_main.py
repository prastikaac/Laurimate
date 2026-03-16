# -*- coding: utf-8 -*-
"""
Laurimate - Campus Assistant
SoftBank Pepper | NAOqi | Python 2.7

Flow:
  1. Hear keyword
  2. Look up campus_faq.json  -> answer immediately if found
  3. Otherwise POST to Firebase / Gemini -> speak + show AI answer
"""

import os
import sys
import time
import json
import urllib2

from naoqi import ALProxy, ALModule, ALBroker

# ------------------------------------------------------------------
# Python 2/3 compat
# ------------------------------------------------------------------
try:
    string_types = (str, unicode)
except NameError:
    string_types = (str,)

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

PEPPER_IP    = "192.168.0.118"
PEPPER_PORT  = 9559
FAQ_PATH     = "/home/nao/Laurimate/campus_faq.json"
TABLET_URL   = "http://198.18.0.1/apps/laurimate-1e47c7/index.html"
FIREBASE_URL = "https://chatwithgemini-wfqmz3bdja-uc.a.run.app"

# ------------------------------------------------------------------
# NAOqi rule:
#   global variable name == ALModule name string == subscribeToEvent name
# ------------------------------------------------------------------
LaurimateModule = None

# ------------------------------------------------------------------
# Vocabulary
# ------------------------------------------------------------------
VOCABULARY = [
    "hello", "hi", "hey",
    "good morning", "good afternoon", "good evening",
    "how are you",
    "thank you", "thanks", "bye", "goodbye", "see you",
    "help", "what can you do",
    "wifi password", "what is the wifi password", "whats the wifi password",
    "how do i connect to wifi", "internet",
    "library hours", "when does the library open", "when does the library close",
    "library",
    "canteen menu", "whats for lunch", "food", "canteen", "cafeteria",
    "where is the toilet", "where is the bathroom", "where is the restroom",
    "where is room", "classroom",
    "printing", "how do i print", "student card",
    "student services", "reception",
    "opening hours", "campus hours", "parking", "bus",
    "emergency",
]

# Instant responses — no network call needed
INSTANT_CACHE = {
    "hello":     "Hello! I am Laurimate, your campus assistant. How can I help you?",
    "hi":        "Hi there! How can I help you today?",
    "hey":       "Hey! What can I help you with?",
    "thank you": "You are welcome! Is there anything else I can help you with?",
    "thanks":    "Happy to help! Let me know if you need anything else.",
    "bye":       "Goodbye! Have a wonderful day!",
    "goodbye":   "See you later! Have a great day!",
    "see you":   "Take care! Have a great day!",
}


# ------------------------------------------------------------------
# Knowledge base
# ------------------------------------------------------------------

def load_faq(path):
    fallback = {
        "hello": "Hello! I am Laurimate, your campus assistant. How can I help you?",
    }
    if not os.path.isfile(path):
        print("[Laurimate] FAQ file not found, using fallback.")
        return fallback
    try:
        with open(path, "r") as f:
            data = json.load(f)
        faq = {k.lower().strip(): v for k, v in data.items()}
        print("[Laurimate] Loaded {} FAQ entries.".format(len(faq)))
        return faq
    except Exception as e:
        print("[Laurimate] Could not load FAQ: {}. Using fallback.".format(e))
        return fallback


# ------------------------------------------------------------------
# Speech recognition — clean setup
# Handles the "modifiable_grammar already exists" error that occurs
# when a previous run crashed without unsubscribing properly.
# ------------------------------------------------------------------

def setup_speech(speech):
    """
    Safely reset ALSpeechRecognition before configuring vocabulary.
    Unsubscribes any stale subscribers then sets vocabulary fresh.
    """
    # Step 1 — unsubscribe any leftover subscriber from a previous crash
    try:
        speech.unsubscribe("Laurimate")
        print("[Laurimate] Cleaned up stale speech subscriber.")
    except Exception:
        pass  # not subscribed — that's fine

    # Step 2 — pause before touching vocabulary
    try:
        speech.pause(True)
    except Exception:
        pass

    # Step 3 — set vocabulary (with word spotting enabled)
    speech.setVocabulary(VOCABULARY, True)

    # Step 4 — unpause
    try:
        speech.pause(False)
    except Exception:
        pass


# ------------------------------------------------------------------
# Firebase / Gemini
# ------------------------------------------------------------------

def ask_firebase(question):
    try:
        print("[Laurimate] -> Firebase: '{}'".format(question))
        payload = json.dumps({"message": question})
        req = urllib2.Request(
            FIREBASE_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        response = urllib2.urlopen(req, timeout=10)
        body = response.read()
        data = json.loads(body)
        reply  = data.get("reply", "").strip()
        source = data.get("source", "gemini")
        print("[Laurimate] <- Firebase ({}): {}".format(source, reply[:80]))
        return reply if reply else None, source
    except urllib2.URLError as e:
        print("[Laurimate] Firebase network error: {}".format(e))
        return None, None
    except Exception as e:
        print("[Laurimate] Firebase error: {}".format(e))
        return None, None


# ------------------------------------------------------------------
# Tablet + TTS helpers
# ------------------------------------------------------------------

def set_thinking(tablet_proxy):
    if tablet_proxy:
        try:
            tablet_proxy.executeJS("showThinking();")
        except Exception:
            pass


def say_and_show(speech_proxy, tts_proxy, tablet_proxy, question, answer, source="faq"):
    if isinstance(answer, unicode):
        answer_str = answer.encode("utf-8")
    else:
        answer_str = str(answer)

    if isinstance(question, unicode):
        question_str = question.encode("utf-8")
    else:
        question_str = str(question)

    speech_proxy.pause(True)
    try:
        q_js = question_str.replace("\\", "\\\\").replace("'", "\\'")
        a_js = answer_str.replace("\\", "\\\\").replace("'", "\\'")

        if tablet_proxy:
            try:
                tablet_proxy.executeJS(
                    "showAnswer('{}', '{}', '{}');".format(q_js, a_js, source)
                )
            except Exception as e:
                print("[Laurimate] Tablet JS error: {}".format(e))

        tts_proxy.say(answer_str)
    finally:
        speech_proxy.pause(False)


# ------------------------------------------------------------------
# Event module
# ------------------------------------------------------------------

class WordModule(ALModule):
    """
    Confidence >= 0.40  -> instant cache, then FAQ, then Firebase
    Confidence >= 0.15  -> send straight to Firebase (low conf = unknown word)
    Confidence <  0.15  -> ignore (noise)
    """

    def __init__(self, name, faq, tablet_proxy):
        ALModule.__init__(self, name)
        self.faq    = faq
        self.tablet = tablet_proxy
        self.tts    = ALProxy("ALTextToSpeech",      PEPPER_IP, PEPPER_PORT)
        self.speech = ALProxy("ALSpeechRecognition", PEPPER_IP, PEPPER_PORT)

    def on_word_recognized(self, key, value):
        if not value or len(value) < 2:
            return

        pairs = []
        for i in range(0, len(value) - 1, 2):
            w = value[i]
            c = value[i + 1]
            if isinstance(w, string_types) and isinstance(c, float):
                pairs.append((w.lower().strip(), c))

        if not pairs:
            return

        word, conf = max(pairs, key=lambda x: x[1])

        if conf < 0.15:
            return  # noise

        print("[Laurimate] Heard: '{}' ({:.0%})".format(word, conf))

        if conf >= 0.40:
            # 1. Instant cache
            instant = INSTANT_CACHE.get(word)
            if instant:
                print("[Laurimate] Instant cache hit.")
                say_and_show(self.speech, self.tts, self.tablet,
                             word, instant, source="faq")
                return

            # 2. Local FAQ
            answer = self.faq.get(word)
            if answer:
                print("[Laurimate] FAQ hit.")
                say_and_show(self.speech, self.tts, self.tablet,
                             word, answer, source="faq")
                return

        # 3. Firebase / Gemini (low confidence OR not in FAQ)
        print("[Laurimate] Asking Firebase...")
        set_thinking(self.tablet)
        reply, source = ask_firebase(word)

        if reply:
            say_and_show(self.speech, self.tts, self.tablet,
                         word, reply, source="ai")
        else:
            say_and_show(self.speech, self.tts, self.tablet, word,
                         "I am sorry, I could not reach my knowledge base. Please ask a staff member.",
                         source="faq")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    global LaurimateModule

    faq = load_faq(FAQ_PATH)

    # 1. Broker first
    broker = ALBroker("PythonBroker", "0.0.0.0", 0, PEPPER_IP, PEPPER_PORT)

    # 2. Tablet (optional)
    tablet = None
    try:
        tablet = ALProxy("ALTabletService", PEPPER_IP, PEPPER_PORT)
        tablet.showWebview(TABLET_URL)
        print("[Laurimate] Tablet showing: {}".format(TABLET_URL))
    except Exception as e:
        print("[Laurimate] Tablet not available: {}".format(e))

    # 3. Module
    LaurimateModule = WordModule("LaurimateModule", faq, tablet)

    # 4. Set up speech recognition safely (handles stale grammar error)
    speech = ALProxy("ALSpeechRecognition", PEPPER_IP, PEPPER_PORT)
    setup_speech(speech)

    # 5. Subscribe event
    memory = ALProxy("ALMemory", PEPPER_IP, PEPPER_PORT)
    memory.subscribeToEvent(
        "WordRecognized",
        "LaurimateModule",
        "on_word_recognized",
    )

    # 6. Start recognition engine
    speech.subscribe("Laurimate")

    # 7. Welcome
    tts = ALProxy("ALTextToSpeech", PEPPER_IP, PEPPER_PORT)
    if tablet:
        try:
            tablet.executeJS("showWelcome();")
        except Exception:
            pass

    speech.pause(True)
    tts.say("Hello! I am Laurimate, your campus assistant. How can I help you?")
    speech.pause(False)

    print("[Laurimate] Listening. Press Ctrl+C to stop.")

    # 8. Keep alive
    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[Laurimate] Shutting down...")

    finally:
        try:
            memory.unsubscribeToEvent("WordRecognized", "LaurimateModule")
        except Exception:
            pass
        try:
            speech.unsubscribe("Laurimate")
        except Exception:
            pass
        if tablet:
            try:
                tablet.hideWebview()
            except Exception:
                pass
        broker.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()