# 🤖 Laurimate — Pepper Robot Campus Assistant

> A voice-first, AI-powered campus assistant running on the **SoftBank Pepper** humanoid robot, built for **Laurea University of Applied Sciences** (Finland).

Laurimate helps students and visitors by answering questions through natural speech — from Wi-Fi passwords and library locations to general knowledge — all through a seamless voice conversation with an animated tablet UI.

---

## 📸 Overview

| Feature                 | Description                                                              |
|-------------------------|--------------------------------------------------------------------------|
| **Robot**               | SoftBank Pepper (humanoid, ~120 cm)                                      |
| **Interaction**         | Voice-first — user speaks, Pepper listens, thinks, and answers aloud     |
| **Knowledge**           | Campus FAQ database + Google Gemini AI fallback for any topic            |
| **Tablet UI**           | Animated voice-bubble interface on Pepper's built-in chest tablet        |
| **Session Management**  | 60-second idle timeout — returns to welcome screen after inactivity      |

---

## 🏗️ Architecture

```
┌──────────────┐         ┌──────────────────┐         ┌──────────────────────┐
│   User       │  voice  │  Pepper Robot    │  HTTP   │  Firebase Cloud      │
│   speaks     │ ──────► │  (pepper_main.py)│ ──────► │  Functions           │
│              │         │                  │         │  (index.js)          │
│              │ ◄────── │  ALTextToSpeech  │ ◄────── │  Gemini 2.5 Flash    │
│   hears      │  voice  │  + Tablet UI     │  JSON   │  + campus.json       │
└──────────────┘         └──────────────────┘         └──────────────────────┘
```

### Interaction Flow

1. **Speech Detection** — `ALSpeechRecognition` (word-spotting mode) detects the user speaking
2. **Audio Recording** — Pepper records the full utterance via `ALAudioRecorder` with silence detection
3. **Transcription** — WAV audio is sent to **Google Speech-to-Text API** for accurate transcription
4. **AI Response** — Transcript is POSTed to a **Firebase Cloud Function** that queries **Google Gemini 2.5 Flash**, enriched with campus FAQ context
5. **Response** — Pepper speaks the answer via `ALTextToSpeech` and updates the tablet UI simultaneously
6. **Loop** — Immediately ready for the next question; session ends after 60s of silence

---

## 🛠️ Tech Stack

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
| **AI Model**           | Google Gemini 2.5 Flash                              |
| **Knowledge Base**     | JSON FAQ database (`campus.json`)                    |

### Tablet UI

| Component              | Technology                                          |
|------------------------|-----------------------------------------------------|
| **Markup**             | HTML5                                                |
| **Styling**            | CSS3 (animations, gradients — compatible with older Android WebView) |
| **Logic**              | Vanilla JavaScript                                   |
| **States**             | Welcome → Listening → Thinking → Answer display      |

---

## 📁 Project Structure

```
Laurimate/
├── pepper_main.py            # Main robot brain — runs on Pepper via SSH
├── concept.txt               # Design concept & architecture notes
├── campus_faq.json           # Local FAQ reference
│
├── tablet/                   # Tablet UI (deployed to Pepper's web server)
│   ├── index.html            # Main UI — voice bubble, animations, answer display
│   ├── style.css             # Additional styles
│   └── laurea.png            # Laurea logo
│
├── functions/                # Firebase Cloud Functions (backend)
│   ├── index.js              # Gemini AI endpoint — processes questions
│   ├── package.json          # Node.js dependencies
│   └── data/
│       └── campus.json       # Campus FAQ knowledge base
│
├── firebase.json             # Firebase project configuration
├── .firebaserc               # Firebase project alias
└── README.md                 # This file
```

---

## 🚀 Setup & Deployment

### Prerequisites

- **Pepper robot** connected to the same Wi-Fi network as your PC
- **SSH access** to Pepper (default user: `nao`)
- **Google Cloud** API key for Speech-to-Text
- **Firebase** project with Cloud Functions and a Gemini API key stored as a secret
- **Node.js** (for deploying Firebase functions)

### 1. Deploy the Cloud Backend

```bash
# Install dependencies
cd functions
npm install

# Set your Gemini API key as a Firebase secret
firebase functions:secrets:set GEMINI_API_KEY

# Deploy
firebase deploy --only functions
```

### 2. Upload the Robot Script

```bash
# From your project root, upload the Python brain
scp pepper_main.py nao@<PEPPER_IP>:/home/nao/Laurimate/pepper_main.py
```

### 3. Upload the Tablet UI

```bash
# Upload the HTML interface to Pepper's app directory
scp tablet/index.html nao@<PEPPER_IP>:/home/nao/.local/share/PackageManager/apps/laurimate-1e47c7/index.html
```

### 4. Run Laurimate

```bash
# SSH into Pepper
ssh nao@<PEPPER_IP>

# Run the main script
python2.7 /home/nao/Laurimate/pepper_main.py
```

Pepper will say *"Hello! I am Laurimate, your campus assistant. How can I help you?"* and start listening.

---

## ⚙️ Configuration

Key configuration values in `pepper_main.py`:

| Variable             | Description                          | Default                     |
|----------------------|--------------------------------------|-----------------------------|
| `PEPPER_IP`          | Pepper's IP address                  | `192.168.0.118`             |
| `PEPPER_PORT`        | NAOqi port                           | `9559`                      |
| `FIREBASE_URL`       | Cloud Function endpoint              | *(your Firebase URL)*       |
| `GOOGLE_STT_KEY`     | Google Speech-to-Text API key        | *(your API key)*            |
| `MIN_RECORD_SEC`     | Minimum recording duration           | `4.0` seconds               |
| `SILENCE_TIMEOUT`    | Silence before stopping recording    | `3.0` seconds               |
| `STT_LANGUAGE`       | Speech recognition language          | `en-US`                     |

---

## 💬 How It Works — Detailed

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
- Records for at least 4 seconds (to capture full questions)
- Monitors `SpeechDetected` memory key from NAOqi
- Stops after 3 seconds of continuous silence
- Maximum recording: 10 minutes (for long queries)

### Tablet UI States

| State        | Visual                                      |
|--------------|---------------------------------------------|
| **Welcome**  | Animated logo + "How can I help?" prompt     |
| **Listening**| Pulsing voice bubble with sound waves        |
| **Thinking** | Rotating dots animation                      |
| **Answer**   | Question + answer display with source badge  |

---

## 👥 Authors

- **Rakesh** & **Prasiddha**
- Built for **Laurea University of Applied Sciences**, Finland

---

## 📝 License

This project was developed as part of an academic project at Laurea University of Applied Sciences.
