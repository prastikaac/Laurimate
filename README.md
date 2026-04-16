# Laurimate — Pepper Robot Campus Assistant

> A voice-first, AI-powered campus assistant running on the **SoftBank Pepper** humanoid robot, built for **Laurea University of Applied Sciences** (Finland).

Laurimate helps students and visitors by answering questions through natural speech — from Wi-Fi passwords and library locations to general knowledge — all through a seamless voice conversation with an animated tablet UI.

---

## Overview

| Feature                 | Description                                                              |
|-------------------------|--------------------------------------------------------------------------|
| **Robot**               | SoftBank Pepper (humanoid, ~120 cm)                                      |
| **Interaction**         | Voice-first — user speaks, Pepper listens, thinks, and answers aloud     |
| **Knowledge**           | Campus FAQ database + custom-built conversational AI fallback            |
| **Tablet UI**           | Animated voice-bubble interface on Pepper's built-in chest tablet        |
| **Session Management**  | 60-second idle timeout — returns to welcome screen after inactivity      |

---

## Architecture

```
┌──────────────┐         ┌──────────────────┐         ┌──────────────────────┐
│   User       │  voice  │  Pepper Robot    │  HTTP   │  Firebase Cloud      │
│   speaks     │ ──────► │  (pepper_main.py)│ ──────► │  Functions           │
│              │         │                  │         │  (index.js)          │
│              │ ◄────── │  ALTextToSpeech  │ ◄────── │  Custom Built AI     │
│   hears      │  voice  │  + Tablet UI     │  JSON   │  + campus.json       │
└──────────────┘         └──────────────────┘         └──────────────────────┘
```

### Interaction Flow

1. **Speech Detection** — `ALSpeechRecognition` (word-spotting mode) detects the user speaking
2. **Audio Recording** — Pepper records the full utterance via `ALAudioRecorder` with silence detection
3. **Transcription** — WAV audio is sent to **Google Speech-to-Text API** for accurate transcription
4. **AI Response** — Transcript is POSTed to a **Firebase Cloud Function** that queries our **custom-built reasoning AI**, enriched with campus FAQ context
5. **Response** — Pepper speaks the answer via `ALTextToSpeech` and updates the tablet UI simultaneously
6. **Loop** — Immediately ready for the next question; session ends after 60s of silence

---

## Tech Stack

### Robot (On-Device)

| Component              | Technology                                          |
|------------------------|-----------------------------------------------------|
| **Robot OS**           | NAOqi OS (Linux-based, custom SoftBank Robotics OS)  |
| **Programming Language** | Python 2.7 (NAOqi SDK requirement)                 |
| **Framework**          | NAOqi Framework + ALModules                          |
| **Speech Recognition** | ALSpeechRecognition (trigger) + Google STT (transcription) |
| **Text-to-Speech**     | ALTextToSpeech (built-in Pepper TTS)                 |
| **Audio Recording**    | ALAudioRecorder (16 kHz, WAV, front microphone)      |
| **Tablet Display**     | ALTabletService (serves HTML/CSS/JS on built-in Android tablet) |

### Cloud Backend

| Component              | Technology                                          |
|------------------------|-----------------------------------------------------|
| **Hosting**            | Google Firebase (Cloud Functions v2)                 |
| **Runtime**            | Node.js 24                                          |
| **AI Model**           | Custom-trained conversational AI                     |
| **Knowledge Base**     | JSON FAQ database (`campus.json`)                    |

### Tablet UI

| Component              | Technology                                          |
|------------------------|-----------------------------------------------------|
| **Markup**             | HTML5                                                |
| **Styling**            | CSS3 (animations, gradients — compatible with older Android WebView) |
| **Logic**              | Vanilla JavaScript                                   |
| **States**             | Welcome → Listening → Thinking → Answer display      |

---

## How It Works — Detailed

### Instant Cache (< 100ms response)
Common greetings and farewells (`hello`, `hi`, `thank you`, `bye`) are answered instantly without going through STT or the cloud, keeping interaction snappy.

### Continuous Session Mode
Once the user speaks, Laurimate enters a **conversation session**:
- Pepper continuously listens for follow-up questions
- A 60-second idle timer runs in the background
- If no speech is detected for 60 seconds, the tablet returns to the welcome screen
- Each new utterance resets the timer

### Silence Detection
Recording uses a smart silence-detection loop:
- Records for at least 2 seconds (to capture full questions)
- Monitors `SpeechDetected` memory key from NAOqi
- Stops after 2 seconds of continuous silence
- Maximum recording: 10 minutes (for long queries)

### Tablet UI States

| State        | Visual                                      |
|--------------|---------------------------------------------|
| **Welcome**  | Animated logo + "How can I help?" prompt     |
| **Listening**| Pulsing voice bubble with sound waves        |
| **Thinking** | Rotating dots animation                      |
| **Answer**   | Question + answer display with source badge  |

---

## Authors

- **Rakesh** & **Prasiddha**
- Built for **Laurea University of Applied Sciences**, Finland

---

## License

This project was developed as part of an academic project at Laurea University of Applied Sciences.
