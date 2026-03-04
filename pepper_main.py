# -*- coding: utf-8 -*-
from naoqi import ALProxy
import json
import time

# -------------------------------
# CONFIGURATION
# -------------------------------
PEPPER_IP = "192.168.0.118"
PEPPER_PORT = 9559

# Vocabulary: words Pepper will recognize
VOCABULARY = ["hello", "wifi password", "library hours", "campus map", "opening hours"]

# Local JSON knowledge file
KNOWLEDGE_FILE = "campus_faq.json"

# -------------------------------
# CONNECT TO SERVICES
# -------------------------------
tts = ALProxy("ALTextToSpeech", PEPPER_IP, PEPPER_PORT)
sr = ALProxy("ALSpeechRecognition", PEPPER_IP, PEPPER_PORT)
mem = ALProxy("ALMemory", PEPPER_IP, PEPPER_PORT)
tablet = ALProxy("ALTabletService", PEPPER_IP, PEPPER_PORT)

# -------------------------------
# LOAD LOCAL KNOWLEDGE
# -------------------------------
try:
    with open(KNOWLEDGE_FILE, "r") as f:
        knowledge = json.load(f)
except Exception as e:
    print("Failed to load JSON knowledge:", e)
    knowledge = {}

# -------------------------------
# HELPER FUNCTIONS
# -------------------------------
def send_to_tablet(text):
    """Update tablet UI via JS function"""
    try:
        js_code = 'updateBubble("{}");'.format(text.replace('"', '\\"'))
        tablet.executeJS(js_code)
    except Exception as e:
        print("Tablet update failed:", e)

def call_ai_fallback(query):
    """Fallback AI response (replace with Gemini/OpenAI call)"""
    return "Sorry, I don't have that information yet."

def respond_to_query(query):
    """Respond using JSON first, then AI fallback"""
    query_lower = query.lower()
    answer = knowledge.get(query_lower)
    if not answer:
        answer = call_ai_fallback(query_lower)
    tts.say(answer)
    send_to_tablet(answer)

# -------------------------------
# SPEECH CALLBACK
# -------------------------------
def on_word_recognized(value):
    """
    value[0] = recognized word
    value[1] = confidence (0-1)
    """
    try:
        word, confidence = value[0], value[1]
        if confidence > 0.4:
            print("Heard:", word)
            respond_to_query(word)
    except Exception as e:
        print("Callback error:", e)

# -------------------------------
# SETUP SPEECH RECOGNITION
# -------------------------------

# Stop ASR before changing vocabulary
try:
    sr.unsubscribe("Laurimate")
except Exception:
    pass

# Pause ASR engine
try:
    sr.pause(True)
except Exception:
    pass

# Set vocabulary safely
sr.setVocabulary(VOCABULARY, False)

# Resume ASR engine
try:
    sr.pause(False)
except Exception:
    pass

# Subscribe to start listening
sr.subscribe("Laurimate")

# Connect memory signal
try:
    sub = mem.subscriber("WordRecognized")
    sub.signal.connect(lambda v: on_word_recognized(list(v)))
except Exception as e:
    print("Subscription failed:", e)

# -------------------------------
# WELCOME MESSAGE
# -------------------------------
welcome_msg = "Hello! I am Laurimate, your campus assistant."
tts.say(welcome_msg)

# Load tablet UI and show welcome
tablet.showWebview("file:///home/nao/Laurimate/index.html")
send_to_tablet(welcome_msg)

print("Laurimate is ready and listening...")

# -------------------------------
# KEEP SCRIPT RUNNING
# -------------------------------
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Unsubscribing...")
    sr.unsubscribe("Laurimate")