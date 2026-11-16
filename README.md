# Laurimate

Laurimate is an AI campus assistant on the SoftBank Pepper robot at Laurea University of Applied Sciences, created by Rakesh and Prasiddha.

## Video script

Hi everyone, this is Laurimate, our AI campus assistant on the Pepper robot.

Here is how it works. You just walk up to Pepper and speak in English or Finnish. Pepper listens through its microphone and turns your voice into text.

First, it checks our Laurea campus database, which has 1,650 questions and answers about campus life, Wi-Fi, rooms, and student services. The AI takes that data and turns it into a natural spoken answer.

If you ask something outside the campus database, like a joke, the weather, the current time, or a general question, the AI answers it directly and checks the internet when needed. It also remembers your conversation so you can ask follow-up questions, and it shows everything on the chest tablet while speaking with hand gestures.

## SDK and technologies used

- Robot SDK: SoftBank Robotics NAOqi Python 2.7 SDK (`pynaoqi`)
- Robot modules: `ALAudioDevice`, `ALTextToSpeech`, `ALAnimatedSpeech`, `ALAnimationPlayer`, and `ALTabletService`
- Speech recognition: Google Cloud Speech-to-Text API
- AI models: Groq API (`openai/gpt-oss-120b`) and Google Gemini API (`gemini-2.5-flash`)
- Campus database: Local JSON knowledge base (`campus.json` with 1,650 Q&As)
- Live data APIs: Open-Meteo API for weather, `timeapi.io` for Helsinki time, plus Laurea website and Wikipedia APIs
- Cloud backend: Google Firebase Cloud Functions (Node.js)
- Tablet UI: HTML, CSS, JavaScript, and HTML5 Canvas animations
