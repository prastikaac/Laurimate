# -*- coding: utf-8 -*-
"""
Laurimate - Interactive Kids Entertainment Controller
(Spoken Voice + Real Songs on Dances + Sound Effects + Photo Booth + Pure Visual Tablet)
SoftBank Pepper | NAOqi | Python 2.7

Run from Windows PC:
  python kids_fun.py

Or on Pepper over SSH:
  python2.7 /home/nao/Laurimate/kids_fun.py
"""

import sys
import os
import time
import json
import math
import wave
import struct
import random
import threading

for _p in ["/opt/aldebaran/lib/python2.7/site-packages", "/usr/lib/python2.7/site-packages"]:
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from naoqi import ALProxy
    HAS_NAOQI = True
except ImportError:
    HAS_NAOQI = False

try:
    raw_input
except NameError:
    raw_input = input

PEPPER_IP        = "127.0.0.1" if os.path.exists("/home/nao") else "192.168.0.118"
REMOTE_SSH_IP    = "192.168.0.118"
REMOTE_USER      = "nao"
REMOTE_PASS      = "Dll#2025"
PEPPER_PORT      = 9559

KIDS_TABLET_URL  = "http://198.18.0.1/apps/laurimate-1e47c7/kids.html"
MAIN_TABLET_URL  = "http://198.18.0.1/apps/laurimate-1e47c7/index.html"

STATE_PATHS = [
    "/home/nao/.local/share/PackageManager/apps/laurimate-1e47c7/kids_state.json",
    "/home/nao/.local/share/PackageManager/apps/laurimate-1e47c7/html/kids_state.json"
]
WEBVIEW_FLAG = "/tmp/laurimate_kids_webview_v6.flag"

# Built-in real song & sound effect files on Pepper
SONG_TAICHI_MP3  = "/home/nao/.local/share/PackageManager/apps/laureaevent-9b7fba/behavior_1/swiftswords_ext.mp3"
SONG_DANCE_MP3   = "/tmp/kids_edm_festival_v2.wav"
SONG_EDM_WAV     = "/tmp/kids_edm_festival_v2.wav"
SONG_FUNK_WAV    = "/tmp/kids_electro_funk_v2.wav"
SONG_HYPER_WAV   = "/tmp/kids_hyper_arcade_v2.wav"
ENERGETIC_DANCE_SONGS = [SONG_EDM_WAV, SONG_FUNK_WAV, SONG_HYPER_WAV]
SONG_UPBEAT_OGG  = "/home/nao/.local/share/PackageManager/apps/boot-config/sounds/wait_music_update.ogg"
SONG_GUITAR_OGG  = "/home/nao/.local/share/PackageManager/apps/animations/Stand/Waiting/AirGuitar_1/heavyMetal1.ogg"
SONG_BDAY_OGG    = "/home/nao/.local/share/PackageManager/apps/animations/Stand/Waiting/HappyBirthday_1/happy_birthday_en.ogg"
SFX_ELEPHANT_OGG = "/home/nao/.local/share/PackageManager/apps/laureaevent-9b7fba/behavior_1/elephant.ogg"
SFX_CAMERA_OGG   = "/home/nao/.local/share/PackageManager/apps/laureaevent-9b7fba/behavior_1/camera1.ogg"
SFX_VACUUM_OGG   = "/home/nao/.local/share/PackageManager/apps/laureaevent-9b7fba/behavior_1/vacuum1.ogg"
SFX_GOLF_OGG     = "/home/nao/.local/share/PackageManager/apps/laureaevent-9b7fba/behavior_1/golf.ogg"
SFX_ROCKET_OGG   = "/home/nao/.local/share/PackageManager/apps/animations/Stand/Waiting/SpaceShuttle_1/rocket1.ogg"
SFX_HELI_OGG     = "/home/nao/.local/share/PackageManager/apps/animations/Stand/Waiting/Helicopter_1/helicopter_2.ogg"
SFX_MONSTER_OGG  = "/home/nao/.local/share/PackageManager/apps/animations/Stand/Waiting/Monster_1/monsterGrowl1.ogg"
SFX_GORILLA_OGG  = "/home/nao/.local/share/PackageManager/apps/animations/Stand/Emotions/Negative/Angry_2/angry5.ogg"
SFX_SNIFF_OGG    = "/home/nao/.local/share/PackageManager/apps/animations/Stand/Emotions/Positive/Hungry_1/sniffing1.ogg"
SFX_R2D2_OGG     = "/home/nao/.local/share/PackageManager/apps/animations/Stand/Waiting/Robot_1/r2d2.ogg"
SFX_MAGIC_OGG    = "/home/nao/.local/share/PackageManager/apps/animations/Stand/Waiting/MysticalPower_1/heaven1.ogg"
SFX_APPLAUSE_OGG = "/home/nao/.local/share/PackageManager/apps/animations/Stand/Emotions/Positive/Winner_1/applause1.ogg"


def _write_state_json(cmd_num):
    payload = json.dumps({
        "seq": int(time.time() * 1000),
        "cmd": str(cmd_num)
    })
    for p in STATE_PATHS:
        try:
            d = os.path.dirname(p)
            if os.path.exists(d):
                with open(p, "w") as f:
                    f.write(payload)
        except Exception:
            pass


def _build_energetic_track_wav(path, step_dur, pattern_steps, repeats=3):
    """
    Synthesizes a high-energy EDM/Electro dance track with:
      - Punchy 4-on-the-floor kick drum on every beat (step % 4 == 0)
      - Crisp electronic clap/snare on beats 2 & 4 (step % 8 == 4)
      - Off-beat metallic hi-hat on every eighth offbeat (step % 4 == 2)
      - Pumping sidechained octave synth bass + bright multi-oscillator supersaw lead & chord stab
    """
    if os.path.exists(path):
        return path
    try:
        rate = 22050
        loop_frames = []
        pi2 = 2.0 * math.pi
        for step_idx, (lead_f, chord_f, bass_f) in enumerate(pattern_steps):
            n_samples = int(rate * step_dur)
            is_kick = (step_idx % 4 == 0)
            is_snare = (step_idx % 8 == 4)
            is_hat = (step_idx % 4 == 2)
            for i in range(n_samples):
                t = float(i) / rate
                u = float(i) / float(max(1, n_samples))
                note_env = min(1.0, (1.0 - u) * 3.2) if lead_f > 0 else 0.0

                # Bright supersaw/pulse lead + harmony chord stab
                lead = 0.0
                if lead_f > 0:
                    s1 = math.sin(pi2 * lead_f * t)
                    s2 = 0.55 * math.sin(pi2 * (lead_f * 2.0) * t)
                    s3 = 0.35 * (1.0 if math.sin(pi2 * (lead_f * 1.004) * t) >= 0 else -1.0)
                    c1 = 0.40 * math.sin(pi2 * chord_f * t) if chord_f > 0 else 0.0
                    lead = note_env * (s1 + s2 + s3 + c1)

                # Pumping octave square/sub bassline
                bass = 0.0
                if bass_f > 0:
                    b_env = min(1.0, u * 4.5) * (1.0 - 0.35 * u)
                    b_sq = 1.0 if math.sin(pi2 * bass_f * t) >= 0 else -1.0
                    b_sub = math.sin(pi2 * (bass_f * 0.5) * t)
                    bass = b_env * (0.55 * b_sq + 0.50 * b_sub)

                # 4-on-the-floor punchy EDM kick drum
                kick = 0.0
                if is_kick and t < 0.095:
                    k_u = t / 0.095
                    k_f = 175.0 - 125.0 * (k_u ** 0.45)
                    kick = (1.0 - k_u) * 1.35 * math.sin(pi2 * k_f * t)

                # Crisp clap/snare on beats 2 & 4
                snare = 0.0
                if is_snare and t < 0.085:
                    s_u = t / 0.085
                    noise = math.sin(pi2 * 3417.0 * t) * math.cos(pi2 * 5119.0 * t) + 0.6 * math.sin(pi2 * 7331.0 * t)
                    body = math.sin(pi2 * (230.0 - 90.0 * s_u) * t)
                    snare = (1.0 - s_u) * (0.75 * noise + 0.55 * body)

                # Off-beat hi-hat shimmer
                hat = 0.0
                if is_hat and t < 0.055:
                    h_u = t / 0.055
                    hat = (1.0 - h_u) * 0.50 * (
                        math.sin(pi2 * 6143.0 * t) + math.sin(pi2 * 8291.0 * t) * math.cos(pi2 * 4177.0 * t)
                    )

                val = int(9600 * (lead + bass + kick + snare + hat))
                loop_frames.append(struct.pack("<h", max(-32000, min(32000, val))))

        loop_bytes = "".join(loop_frames)
        wf = wave.open(path, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(loop_bytes * repeats)
        wf.close()
    except Exception:
        pass
    return path


def _ensure_dance_song_wav():
    """Generates 3 loud, high-energy EDM / Electro-Funk / Hyper-Arcade dance songs on Pepper."""
    # Track 1: 138 BPM Festival EDM Eurodance Anthem (A minor / C major high-energy hook)
    edm_steps = [
        # Bar 1: Driving A-minor festival supersaw riff
        (440, 659, 110), (440, 0,   110), (523, 659, 220), (440, 0,   110),
        (587, 880, 110), (523, 659, 110), (440, 0,   220), (392, 587, 110),
        (349, 523,  87), (349, 0,    87), (440, 659, 175), (523, 698,  87),
        (587, 880,  98), (523, 784,  98), (494, 740, 196), (392, 587,  98),
        # Bar 2: High octave energy drop
        (880, 523, 110), (0,   0,   220), (880, 523, 220), (784, 494, 110),
        (659, 440, 110), (587, 392, 220), (523, 330, 220), (659, 440, 110),
        (587, 392,  87), (587, 0,   175), (659, 440, 175), (784, 523,  87),
        (880, 587,  98), (784, 523, 196), (988, 659, 196), (880, 523, 110)
    ]
    _build_energetic_track_wav(SONG_EDM_WAV, 0.11, edm_steps, repeats=3)

    # Track 2: 134 BPM Electro-Funk Party Boogie (Bouncy major-key synth brass + slap octave bass)
    funk_steps = [
        # Bar 1: Funky C-major / G-major electro brass bounce
        (523, 659, 131), (0,   0,   262), (659, 784, 262), (784, 988, 131),
        (880, 523, 147), (784, 523, 294), (659, 440, 262), (523, 392, 131),
        (587, 740, 147), (587, 0,   294), (659, 784, 294), (784, 988, 147),
        (1046,659, 196), (880, 587, 392), (784, 523, 392), (659, 494, 196),
        # Bar 2: Party synth drop
        (1046,784, 131), (1046,784, 262), (880, 659, 262), (784, 523, 131),
        (698, 523, 175), (784, 587, 349), (659, 523, 262), (523, 392, 131),
        (587, 440, 147), (659, 494, 294), (698, 523, 294), (784, 587, 196),
        (880, 659, 196), (988, 740, 392), (1046,784, 262), (1046,523, 131)
    ]
    _build_energetic_track_wav(SONG_FUNK_WAV, 0.112, funk_steps, repeats=3)

    # Track 3: 142 BPM Hyper Arcade Turbo Dance (Fast arpeggiated rave synth + heavy kick)
    hyper_steps = [
        (659, 988, 165), (784, 0,   165), (988, 659, 330), (1318,784, 165),
        (1175,740, 147), (988, 587, 294), (784, 494, 294), (659, 440, 147),
        (523, 784, 131), (659, 0,   131), (784, 523, 262), (1046,659, 131),
        (988, 587, 147), (784, 494, 294), (1175,740, 294), (988, 587, 147),
        (659, 988, 165), (988, 659, 330), (1318,988, 330), (1175,784, 165),
        (1046,659, 131), (988, 587, 262), (880, 523, 262), (784, 494, 131),
        (698, 880, 175), (880, 523, 349), (1046,698, 349), (1175,784, 196),
        (1318,988, 165), (1175,784, 330), (1318,988, 330), (1318,659, 165)
    ]
    _build_energetic_track_wav(SONG_HYPER_WAV, 0.105, hyper_steps, repeats=3)

    # Ensure /tmp/kids_party_song.wav also points to the energetic EDM track
    party_legacy = "/tmp/kids_party_song.wav"
    try:
        import shutil
        if os.path.exists(SONG_EDM_WAV):
            shutil.copyfile(SONG_EDM_WAV, party_legacy)
    except Exception:
        pass
    return SONG_EDM_WAV


def _ensure_animal_sound_wavs():
    """Generates loud Mouse Squeak and Gorilla Chest-Thump WAV sound effects on Pepper."""
    rate = 22050
    # 1. Cute high-pitched Mouse Squeaks (/tmp/kids_mouse_squeak.wav)
    mouse_path = "/tmp/kids_mouse_squeak.wav"
    if not os.path.exists(mouse_path):
        try:
            wf = wave.open(mouse_path, "wb")
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            frames = []
            # 6 rapid cute mouse squeaks with pitch glide (2100 Hz -> 3200 Hz -> 2300 Hz)
            pattern = [(0.11, 2200, 3200), (0.05, 0, 0), (0.10, 2400, 3400), (0.12, 0, 0),
                       (0.11, 2100, 3100), (0.05, 0, 0), (0.12, 2500, 3500), (0.14, 0, 0),
                       (0.10, 2300, 3300), (0.05, 0, 0), (0.13, 2400, 3400)]
            for dur, f0, f1 in pattern:
                n = int(rate * dur)
                for i in range(n):
                    if f0 <= 0:
                        val = 0
                    else:
                        u = float(i) / float(max(1, n))
                        t = float(i) / rate
                        freq = f0 + (f1 - f0) * math.sin(math.pi * u)
                        env = math.sin(math.pi * u)
                        val = int(18000 * env * math.sin(2.0 * math.pi * freq * t))
                    frames.append(struct.pack("<h", max(-32000, min(32000, val))))
            wf.writeframes("".join(frames))
            wf.close()
        except Exception:
            pass

    # 2. Booming Gorilla Chest-Thump & Grunt (/tmp/kids_gorilla_thump.wav)
    gorilla_path = "/tmp/kids_gorilla_thump.wav"
    if not os.path.exists(gorilla_path):
        try:
            wf = wave.open(gorilla_path, "wb")
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            frames = []
            # 8 rhythmic deep chest thumps + low gorilla roar harmonics
            for _ in range(8):
                n = int(rate * 0.28)
                for i in range(n):
                    u = float(i) / float(max(1, n))
                    t = float(i) / rate
                    # Punchy chest thud (160Hz -> 55Hz) + low vocal grunt (110Hz sawtooth)
                    thud_env = max(0.0, 1.0 - u * 2.2)
                    thud_f = 155.0 - 95.0 * u
                    thud = thud_env * math.sin(2.0 * math.pi * thud_f * t)
                    grunt_env = math.sin(math.pi * u)
                    grunt = 0.55 * grunt_env * (
                        math.sin(2.0 * math.pi * 95.0 * t) +
                        0.5 * math.sin(2.0 * math.pi * 190.0 * t) +
                        0.3 * (1.0 if math.sin(2.0 * math.pi * 47.5 * t) >= 0 else -1.0)
                    )
                    val = int(20000 * (thud + grunt))
                    frames.append(struct.pack("<h", max(-32000, min(32000, val))))
            wf.writeframes("".join(frames))
            wf.close()
        except Exception:
            pass

    def _write_wav(filepath, samples_list):
        if os.path.exists(filepath):
            return
        try:
            w = wave.open(filepath, "wb")
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes("".join(samples_list))
            w.close()
        except Exception:
            pass

    # 3. Playful Puppy Dog Barks ("Woof! Woof! Arf!") (/tmp/kids_dog_bark.wav)
    if not os.path.exists("/tmp/kids_dog_bark.wav"):
        frames = []
        for dur, f_start, f_end in [(0.16, 380, 180), (0.10, 0, 0), (0.18, 420, 190), (0.22, 0, 0), (0.15, 450, 210), (0.08, 0, 0), (0.20, 400, 170)]:
            n = int(rate * dur)
            for i in range(n):
                if f_start <= 0:
                    val = 0
                else:
                    u = float(i) / float(max(1, n))
                    t = float(i) / rate
                    f = f_start + (f_end - f_start) * u
                    env = math.sin(math.pi * min(1.0, u * 1.3))
                    sig = math.sin(2*math.pi*f*t) + 0.6*math.sin(2*math.pi*f*2*t) + 0.35*math.sin(2*math.pi*f*3*t)
                    val = int(16500 * env * sig)
                frames.append(struct.pack("<h", max(-32000, min(32000, val))))
        _write_wav("/tmp/kids_dog_bark.wav", frames)

    # 4. Cute Kitty Cat Meow ("Meee-oww!") (/tmp/kids_cat_meow.wav)
    if not os.path.exists("/tmp/kids_cat_meow.wav"):
        frames = []
        for dur, f0, fm, f1 in [(0.55, 620, 980, 520), (0.18, 0, 0, 0), (0.60, 660, 1050, 500)]:
            n = int(rate * dur)
            for i in range(n):
                if f0 <= 0:
                    val = 0
                else:
                    u = float(i) / float(max(1, n))
                    t = float(i) / rate
                    f = (f0 + (fm - f0)*(u*2.0)) if u < 0.5 else (fm + (f1 - fm)*((u-0.5)*2.0))
                    env = math.sin(math.pi * u)
                    sig = math.sin(2*math.pi*f*t) + 0.45*math.sin(2*math.pi*f*2*t)
                    val = int(16000 * env * sig)
                frames.append(struct.pack("<h", max(-32000, min(32000, val))))
        _write_wav("/tmp/kids_cat_meow.wav", frames)

    # 5. Songbird / Eagle Chirp & Whistle (/tmp/kids_bird_chirp.wav)
    if not os.path.exists("/tmp/kids_bird_chirp.wav"):
        frames = []
        for dur, f0, f1 in [(0.14, 1800, 2800), (0.04, 0, 0), (0.14, 2000, 3100), (0.08, 0, 0), (0.28, 2600, 1700), (0.10, 0, 0), (0.15, 1900, 3000), (0.22, 2900, 2100)]:
            n = int(rate * dur)
            for i in range(n):
                if f0 <= 0:
                    val = 0
                else:
                    u = float(i) / float(max(1, n))
                    t = float(i) / rate
                    f = f0 + (f1 - f0)*u + 120.0*math.sin(2*math.pi*28.0*t)
                    env = math.sin(math.pi * u)
                    val = int(16000 * env * math.sin(2*math.pi*f*t))
                frames.append(struct.pack("<h", max(-32000, min(32000, val))))
        _write_wav("/tmp/kids_bird_chirp.wav", frames)

    # 6. Jumping Frog Ribbit ("Rib-bit! Rib-bit!") (/tmp/kids_frog_ribbit.wav)
    if not os.path.exists("/tmp/kids_frog_ribbit.wav"):
        frames = []
        for dur, f0, f1 in [(0.12, 220, 340), (0.04, 0, 0), (0.22, 240, 480), (0.25, 0, 0), (0.12, 220, 340), (0.04, 0, 0), (0.24, 240, 500)]:
            n = int(rate * dur)
            for i in range(n):
                if f0 <= 0:
                    val = 0
                else:
                    u = float(i) / float(max(1, n))
                    t = float(i) / rate
                    f = f0 + (f1 - f0)*u
                    croak_mod = 0.55 + 0.45 * math.sin(2*math.pi*45.0*t)
                    env = math.sin(math.pi * u) * croak_mod
                    sig = math.sin(2*math.pi*f*t) + 0.6*math.sin(2*math.pi*f*2*t)
                    val = int(19000 * env * sig)
                frames.append(struct.pack("<h", max(-32000, min(32000, val))))
        _write_wav("/tmp/kids_frog_ribbit.wav", frames)

    # 7. Giant T-Rex Dinosaur Stomp & Roar (/tmp/kids_dino_stomp.wav)
    if not os.path.exists("/tmp/kids_dino_stomp.wav"):
        frames = []
        for step in range(4):
            n = int(rate * 0.42)
            for i in range(n):
                u = float(i) / float(max(1, n))
                t = float(i) / rate
                stomp = max(0.0, 1.0 - u*2.5) * math.sin(2*math.pi*(130.0 - 80.0*u)*t)
                roar  = math.sin(math.pi*u) * (0.5*math.sin(2*math.pi*(115.0 + 35.0*math.sin(20*t))*t) + 0.4*math.sin(2*math.pi*230.0*t))
                val = int(21000 * (stomp + roar))
                frames.append(struct.pack("<h", max(-32000, min(32000, val))))
        _write_wav("/tmp/kids_dino_stomp.wav", frames)

    # 8. Cristiano Ronaldo Stadium "SIUUUUUU!" Landing Boom & Roar (/tmp/kids_siuuu.wav)
    if not os.path.exists("/tmp/kids_siuuu.wav"):
        frames = []
        # 0.25s air-whoosh -> heavy landing boom + 1.3s stadium "SIUUUUU" vocal synth chord
        n1 = int(rate * 0.25)
        for i in range(n1):
            u = float(i) / float(max(1, n1))
            t = float(i) / rate
            val = int(12000 * u * math.sin(2*math.pi*(280.0 + 220.0*u)*t))
            frames.append(struct.pack("<h", max(-32000, min(32000, val))))
        n2 = int(rate * 1.25)
        for i in range(n2):
            u = float(i) / float(max(1, n2))
            t = float(i) / rate
            boom = max(0.0, 1.0 - u*5.0) * math.sin(2*math.pi*(140.0 - 90.0*u)*t)
            # Stadium crowd "SIUUUU" descending pitch glide (360Hz -> 210Hz)
            f = 360.0 - 150.0 * (u ** 0.7)
            env = min(1.0, (1.0 - u) * 2.5)
            chord = (
                math.sin(2*math.pi*f*t) +
                0.7*math.sin(2*math.pi*(f*1.5)*t) +
                0.5*math.sin(2*math.pi*(f*2.0)*t) +
                0.35*math.sin(2*math.pi*(f*0.5)*t)
            )
            val = int(14500 * env * (boom + chord))
            frames.append(struct.pack("<h", max(-32000, min(32000, val))))
        _write_wav("/tmp/kids_siuuu.wav", frames)

    # 9. Dairy Cow Lowing "Moooooo!" (/tmp/kids_cow_moo.wav)
    if not os.path.exists("/tmp/kids_cow_moo.wav"):
        frames = []
        for dur, f0, fm, f1 in [(1.15, 125.0, 158.0, 118.0), (0.18, 0, 0, 0), (0.95, 130.0, 162.0, 115.0)]:
            n = int(rate * dur)
            for i in range(n):
                if f0 <= 0:
                    val = 0
                else:
                    u = float(i) / float(max(1, n))
                    t = float(i) / rate
                    f = (f0 + (fm - f0)*(u*2.5)) if u < 0.4 else (fm - (fm - f1)*((u - 0.4)/0.6))
                    env = math.sin(math.pi * u)
                    # Rich nasal cow horn harmonics
                    sig = (
                        math.sin(2*math.pi*f*t) +
                        0.85*math.sin(2*math.pi*(f*2.0)*t) +
                        0.60*math.sin(2*math.pi*(f*3.0)*t) +
                        0.35*math.sin(2*math.pi*(f*4.0)*t)
                    )
                    val = int(10500 * env * sig)
                frames.append(struct.pack("<h", max(-32000, min(32000, val))))
        _write_wav("/tmp/kids_cow_moo.wav", frames)

    # 10. Fluffy Sheep Bleat "Baaaaa! Baaaaa!" (/tmp/kids_sheep_baa.wav)
    if not os.path.exists("/tmp/kids_sheep_baa.wav"):
        frames = []
        for dur, f_base in [(0.65, 310.0), (0.16, 0.0), (0.72, 330.0)]:
            n = int(rate * dur)
            for i in range(n):
                if f_base <= 0:
                    val = 0
                else:
                    u = float(i) / float(max(1, n))
                    t = float(i) / rate
                    # Characteristic 32Hz sheep vibrato/tremolo
                    f = f_base - 35.0*u + 18.0*math.sin(2*math.pi*32.0*t)
                    trem = 0.65 + 0.35*math.sin(2*math.pi*32.0*t)
                    env = math.sin(math.pi * u) * trem
                    sig = math.sin(2*math.pi*f*t) + 0.7*math.sin(2*math.pi*f*2*t) + 0.4*math.sin(2*math.pi*f*3*t)
                    val = int(13500 * env * sig)
                frames.append(struct.pack("<h", max(-32000, min(32000, val))))
        _write_wav("/tmp/kids_sheep_baa.wav", frames)

    # 11. Galloping Farm Horse Whinny "Neeeigh!" + Hoof Clops (/tmp/kids_horse_neigh.wav)
    if not os.path.exists("/tmp/kids_horse_neigh.wav"):
        frames = []
        # Whinny (high vibrato descending 1100Hz -> 480Hz)
        n_w = int(rate * 0.90)
        for i in range(n_w):
            u = float(i) / float(max(1, n_w))
            t = float(i) / rate
            f = 1080.0 - 580.0*u + 55.0*math.sin(2*math.pi*24.0*t)
            env = math.sin(math.pi * u)
            sig = math.sin(2*math.pi*f*t) + 0.5*math.sin(2*math.pi*f*2*t)
            val = int(14500 * env * sig)
            frames.append(struct.pack("<h", max(-32000, min(32000, val))))
        # 4 Galloping hoof clops ("Clop-clop, clop-clop!")
        for dur, f_clop in [(0.12, 520.0), (0.18, 390.0), (0.12, 520.0), (0.20, 390.0), (0.12, 520.0), (0.18, 390.0)]:
            n_c = int(rate * dur)
            for i in range(n_c):
                u = float(i) / float(max(1, n_c))
                t = float(i) / rate
                env = max(0.0, 1.0 - u*4.0)
                sig = math.sin(2*math.pi*f_clop*t) + 0.6*math.sin(2*math.pi*(f_clop*1.7)*t)
                val = int(18000 * env * sig)
                frames.append(struct.pack("<h", max(-32000, min(32000, val))))
        _write_wav("/tmp/kids_horse_neigh.wav", frames)

    # 12. Farm Duck "Quack! Quack! Quack! Quack!" (/tmp/kids_duck_quack.wav)
    if not os.path.exists("/tmp/kids_duck_quack.wav"):
        frames = []
        for dur, f0, f1 in [(0.18, 440, 290), (0.07, 0, 0), (0.18, 460, 300), (0.07, 0, 0), (0.18, 450, 290), (0.07, 0, 0), (0.24, 480, 280)]:
            n = int(rate * dur)
            for i in range(n):
                if f0 <= 0:
                    val = 0
                else:
                    u = float(i) / float(max(1, n))
                    t = float(i) / rate
                    f = f0 + (f1 - f0)*u
                    env = math.sin(math.pi * u)
                    sig = math.sin(2*math.pi*f*t) + 0.85*math.sin(2*math.pi*f*2*t) + 0.65*math.sin(2*math.pi*f*3*t)
                    val = int(12500 * env * sig)
                frames.append(struct.pack("<h", max(-32000, min(32000, val))))
        _write_wav("/tmp/kids_duck_quack.wav", frames)

    # 13. Farm Chicken / Rooster "Cluck, cluck, Cock-a-doodle-doo!" (/tmp/kids_chicken_cluck.wav)
    if not os.path.exists("/tmp/kids_chicken_cluck.wav"):
        frames = []
        for dur, f0, f1 in [(0.11, 580, 760), (0.05, 0, 0), (0.11, 600, 790), (0.05, 0, 0), (0.14, 620, 920), (0.10, 0, 0), (0.55, 880, 640)]:
            n = int(rate * dur)
            for i in range(n):
                if f0 <= 0:
                    val = 0
                else:
                    u = float(i) / float(max(1, n))
                    t = float(i) / rate
                    f = f0 + (f1 - f0)*u
                    env = math.sin(math.pi * u)
                    sig = math.sin(2*math.pi*f*t) + 0.6*math.sin(2*math.pi*f*2*t)
                    val = int(15500 * env * sig)
                frames.append(struct.pack("<h", max(-32000, min(32000, val))))
        _write_wav("/tmp/kids_chicken_cluck.wav", frames)

    # 14. Happy Farm Piggy "Oink! Oink! Oink!" (/tmp/kids_pig_oink.wav)
    if not os.path.exists("/tmp/kids_pig_oink.wav"):
        frames = []
        for dur, f0, f1 in [(0.18, 170, 290), (0.07, 0, 0), (0.18, 180, 310), (0.07, 0, 0), (0.20, 175, 320), (0.07, 0, 0), (0.22, 190, 340)]:
            n = int(rate * dur)
            for i in range(n):
                if f0 <= 0:
                    val = 0
                else:
                    u = float(i) / float(max(1, n))
                    t = float(i) / rate
                    f = f0 + (f1 - f0)*u
                    snort = 0.6 + 0.4*math.sin(2*math.pi*52.0*t)
                    env = math.sin(math.pi * u) * snort
                    sig = math.sin(2*math.pi*f*t) + 0.75*math.sin(2*math.pi*f*2*t) + 0.45*math.sin(2*math.pi*f*3*t)
                    val = int(14500 * env * sig)
                frames.append(struct.pack("<h", max(-32000, min(32000, val))))
        _write_wav("/tmp/kids_pig_oink.wav", frames)


class KidsEntertainer(object):
    def __init__(self, ip=PEPPER_IP, port=PEPPER_PORT):
        self.tts    = ALProxy("ALTextToSpeech", ip, port)
        self.speech = ALProxy("ALAnimatedSpeech", ip, port)
        self.anim   = ALProxy("ALAnimationPlayer", ip, port)
        self.leds   = ALProxy("ALLeds", ip, port)
        self.motion = ALProxy("ALMotion", ip, port)
        self.audio  = None
        self.adevice = None
        self.photo  = None
        self.tablet = None
        self.memory = None
        self.busy   = False

        try:
            self.audio = ALProxy("ALAudioPlayer", ip, port)
        except Exception:
            self.audio = None

        try:
            self.adevice = ALProxy("ALAudioDevice", ip, port)
            # Ensure Pepper's speaker volume is loud and clear for the kids
            vol = self.adevice.getOutputVolume()
            if vol < 80:
                self.adevice.setOutputVolume(85)
        except Exception:
            pass

        try:
            self.photo = ALProxy("ALPhotoCapture", ip, port)
            self.photo.setCameraID(0)
            self.photo.setResolution(2)
            self.photo.setPictureFormat("jpg")
        except Exception:
            self.photo = None

        try:
            self.tablet = ALProxy("ALTabletService", ip, port)
        except Exception:
            self.tablet = None

        try:
            self.memory = ALProxy("ALMemory", ip, port)
        except Exception:
            self.memory = None

        try:
            self.motion.wakeUp()
            # Allow gentle small movements on stage even when kids are standing nearby
            try:
                self.motion.setOrthogonalSecurityDistance(0.15)
                self.motion.setTangentialSecurityDistance(0.06)
            except Exception:
                pass
            self.tts.setLanguage("English")
            self.tts.setVolume(1.0)
        except Exception:
            pass

        _ensure_dance_song_wav()
        _ensure_animal_sound_wavs()

    # --------------------------------------------------------------
    # Pure Visual Tablet Control
    # --------------------------------------------------------------
    def ensure_webview_open(self, force=False):
        if not self.tablet:
            return
        try:
            if force or not os.path.exists(WEBVIEW_FLAG):
                with open(WEBVIEW_FLAG, "w") as f:
                    f.write(str(int(time.time())))
                # Pause pepper_main.py while Kids Fun mode is active
                os.system("pkill -f '[p]epper_main.py' >/dev/null 2>&1")
                url = "{}?v={}".format(KIDS_TABLET_URL, int(time.time()))
                self.tablet.showWebview(url)
                time.sleep(0.55)
        except Exception:
            pass

    def set_tablet_command(self, cmd_num, force_open=False):
        cmd_str = str(cmd_num)
        _write_state_json(cmd_str)
        self.ensure_webview_open(force=force_open)
        if self.tablet:
            try:
                ts = int(time.time() * 1000)
                self.tablet.executeJS("setCommand('{}', '', '', {});".format(cmd_str, ts))
            except Exception:
                pass

    def restore_main_tablet(self):
        try:
            if os.path.exists(WEBVIEW_FLAG):
                os.remove(WEBVIEW_FLAG)
        except Exception:
            pass
        if self.tablet:
            try:
                url = "{}?t={}".format(MAIN_TABLET_URL, int(time.time()))
                self.tablet.showWebview(url)
                print("[Kids Fun] Restored main Laurimate screen on tablet.")
            except Exception:
                pass

    # --------------------------------------------------------------
    # Voice, Music Songs & LED Helpers
    # --------------------------------------------------------------
    def say(self, text):
        """Speaks clearly and enthusiastically using Pepper's voice."""
        try:
            self.tts.say(str(text))
        except Exception:
            pass

    def say_animated(self, text):
        """Speaks with expressive body gestures."""
        try:
            self.speech.say(str(text))
        except Exception:
            self.say(text)

    def start_song(self, song_path):
        """Starts playing a song or sound file in the background and returns the task ID."""
        if not self.audio:
            return None
        for p in [song_path, "/tmp/kids_party_song.wav"]:
            if p and os.path.exists(p):
                try:
                    return self.audio.post.playFile(p)
                except Exception:
                    continue
        return None

    def stop_all_songs(self):
        if self.audio:
            try:
                self.audio.stopAll()
            except Exception:
                pass

    def disco_leds(self, duration=4.5):
        def _run():
            try:
                self.leds.rasta(duration)
                self.leds.reset("AllLeds")
            except Exception:
                pass
        t = threading.Thread(target=_run)
        t.daemon = True
        t.start()

    def set_eye_color(self, color_hex):
        try:
            self.leds.fadeRGB("FaceLeds", color_hex, 0.25)
        except Exception:
            pass

    def reset_leds(self):
        try:
            self.leds.reset("AllLeds")
        except Exception:
            pass

    def run_anim(self, path):
        try:
            self.anim.run(path)
            return True
        except Exception:
            return False

    # --------------------------------------------------------------
    # Safe Small-Distance Stage Walking / Rolling Helpers (ALMotion)
    # --------------------------------------------------------------
    def stage_move(self, x=0.0, y=0.0, theta=0.0, async_move=False):
        """
        Rolls Pepper a small, safe distance around its current stage spot.
        If the rear charging hatch is open (ILS sensor == 1.0) or an obstacle blocks the wheels,
        it warns the operator and performs a full-body hip/knee/torso lean & twist movement so
        Pepper still moves dynamically on stage!
        """
        try:
            hatch_open = False
            if self.memory:
                try:
                    ils = self.memory.getData("Device/SubDeviceList/Platform/ILS/Sensor/Value")
                    if ils and float(ils) > 0.5:
                        hatch_open = True
                        print("[Stage Move] NOTE: Pepper's rear charging flap/hatch is OPEN (or charger plugged in) -> Wheels are locked by Pepper hardware! Close the back flap to roll wheels.")
                except Exception:
                    pass

            safe_x = max(-0.30, min(0.30, float(x)))
            safe_y = max(-0.25, min(0.25, float(y)))
            safe_t = float(theta)

            moved = False
            if not hatch_open:
                if async_move:
                    self.motion.post.moveTo(safe_x, safe_y, safe_t)
                    moved = True
                else:
                    moved = bool(self.motion.moveTo(safe_x, safe_y, safe_t))

            if not moved:
                # Full-body stage lean, hip-sway & torso twist when wheels are locked
                pitch = -0.25 if safe_x > 0 else (0.15 if safe_x < 0 else -0.12)
                roll  =  0.18 if safe_y > 0 else (-0.18 if safe_y < 0 else (0.16 if safe_t > 0 else -0.16))
                yaw   =  0.55 if safe_t > 0 else (-0.55 if safe_t < 0 else 0.0)
                names = ["HipPitch", "KneePitch", "HipRoll", "HeadYaw"]
                if async_move:
                    self.motion.post.angleInterpolationWithSpeed(names, [pitch, -pitch*0.45, roll, yaw], 0.35)
                else:
                    self.motion.angleInterpolationWithSpeed(names, [pitch, -pitch*0.45, roll, yaw], 0.35)
                    self.motion.angleInterpolationWithSpeed(names, [-0.03, 0.0, 0.0, 0.0], 0.35)
        except Exception as e:
            print("[Kids Fun] Stage move note: {}".format(e))

    def stage_pulse_move(self):
        """
        Guaranteed stage movement that runs on EVERY action so Pepper always moves
        around its stage (rolls wheels slightly forward/turn & back when unlocked,
        AND sways hips/torso/arms so the whole robot is visibly moving!).
        """
        try:
            self.stage_move(0.18, 0.0, 0.28, async_move=True)
        except Exception:
            pass

    def stage_return_move(self):
        """Returns Pepper smoothly back to its stage spot after an action."""
        try:
            self.stage_move(-0.18, 0.0, -0.28, async_move=True)
        except Exception:
            pass

    # --------------------------------------------------------------
    # Choreographed Physical Dance Routines (ALMotion)
    # --------------------------------------------------------------
    def dance_wave_boogie(self, cycles=3, with_stage_roll=False):
        """Energetic arm + hip + head wave dance (+ optional small stage glide left/right & back)."""
        try:
            names = [
                "LShoulderPitch", "RShoulderPitch",
                "LShoulderRoll",  "RShoulderRoll",
                "LElbowRoll",     "RElbowRoll",
                "HipRoll",        "HeadYaw", "HeadPitch"
            ]
            pose_left = [
                -0.4,  1.1,
                 0.45, -0.1,
                -1.1,   0.4,
                 0.16,  0.45, -0.15
            ]
            pose_right = [
                 1.1, -0.4,
                 0.1, -0.45,
                -0.4,  1.1,
                -0.16, -0.45, -0.15
            ]
            for i in range(cycles):
                if with_stage_roll and i == 0:
                    self.stage_move(0.18, 0.0, 0.35, async_move=True)
                elif with_stage_roll and i == 1:
                    self.stage_move(0.0, 0.0, -0.70, async_move=True)
                elif with_stage_roll and i == 2:
                    self.stage_move(-0.18, 0.0, 0.35, async_move=True)
                self.motion.angleInterpolationWithSpeed(names, pose_left, 0.55)
                self.motion.angleInterpolationWithSpeed(names, pose_right, 0.55)
            self.motion.angleInterpolationWithSpeed(
                names, [1.4, 1.4, 0.15, -0.15, -0.5, 0.5, 0.0, 0.0, -0.1], 0.4
            )
        except Exception:
            pass

    def dance_robot_pop(self):
        """Mechanical robot pop-and-lock dance moves."""
        try:
            names = ["LShoulderPitch", "RShoulderPitch", "LElbowYaw", "RElbowYaw", "LElbowRoll", "RElbowRoll", "HeadYaw", "HipPitch"]
            steps = [
                [0.0,  1.4, -1.5,  1.5, -1.5,  0.2,  0.5, -0.08],
                [1.4,  0.0, -1.5,  1.5, -0.2,  1.5, -0.5, -0.08],
                [0.0,  0.0,  0.0,  0.0, -1.5,  1.5,  0.0, -0.18],
                [0.5,  0.5, -1.2,  1.2, -0.4,  0.4,  0.0,  0.0],
            ]
            for pose in steps:
                self.motion.angleInterpolationWithSpeed(names, pose, 0.6)
            self.motion.angleInterpolationWithSpeed(names, [1.4, 1.4, -1.2, 1.2, -0.5, 0.5, 0.0, 0.0], 0.4)
        except Exception:
            pass

    # --------------------------------------------------------------
    # Short, Fast Dances & Actions (Voice ONLY on key ones, short lines!)
    # --------------------------------------------------------------
    def cmd_0_home(self, force_open=False):
        self.set_tablet_command(0, force_open=force_open)

    def cmd_1_welcome_peekaboo(self):
        """1: Short Welcome ('Hello friends! Welcome!') + Wave & Peek-a-Boo."""
        self.set_tablet_command(1)
        self.disco_leds(4.5)
        self.say_animated("^start(animations/Stand/Gestures/Hey_1) Hello friends! Welcome!")
        self.run_anim("animations/Stand/Waiting/HideEyes_1")
        self.run_anim("animations/Stand/Emotions/Positive/Happy_4")
        self.reset_leds()

    def cmd_2_disco_dance(self):
        """2: Short 'Let's dance!' + Immediate High-Energy EDM/Funk Song & Dance Party (+ Small Stage Roll)!"""
        self.set_tablet_command(2)
        self.disco_leds(12.0)
        self.say("Let's dance!")
        song = random.choice(ENERGETIC_DANCE_SONGS)
        self.start_song(song)
        self.run_anim("animations/Stand/Waiting/FunnyDancer_1")
        self.dance_wave_boogie(cycles=3, with_stage_roll=True)
        self.dance_robot_pop()
        self.stop_all_songs()
        self.start_song(SFX_APPLAUSE_OGG)
        self.run_anim("animations/Stand/Emotions/Positive/Winner_1")
        self.reset_leds()

    # --------------------------------------------------------------
    # Football Superstar Celebrations (Ronaldo "SIUUUU!" & Lionel Messi Sky Point!)
    # --------------------------------------------------------------
    def cmd_cr_ronaldo_siuuu(self):
        """cr: Cristiano Ronaldo 'SIUUUUU!' Jump, Spin & Wide-Arm Power Landing Celebration!"""
        self.set_tablet_command("soccer")
        self.set_eye_color(0xFDE047)
        names = [
            "HipPitch", "KneePitch", "HeadPitch", "HeadYaw",
            "LShoulderPitch", "RShoulderPitch",
            "LShoulderRoll",  "RShoulderRoll",
            "LElbowRoll",     "RElbowRoll",
            "LElbowYaw",      "RElbowYaw",
            "LHand",          "RHand"
        ]
        # 1. Run-up & cross arms high over chest ("Jump")
        cross_arms_pose = [
            -0.25,  0.12, -0.10, 0.0,
            -0.25, -0.25,
             0.05, -0.05,
            -1.48,  1.48,
            -0.40,  0.40,
             0.15,  0.15
        ]
        # 2. Iconic "SIUUUU!" landing: chest proud, head up, both arms thrown straight down & out wide to the sides!
        siuuu_land_pose = [
             0.08, -0.04, -0.25, 0.0,
             0.75,  0.75,
             0.58, -0.58,
            -0.08,  0.08,
            -1.40,  1.40,
             0.95,  0.95
        ]
        neutral_pose = [
            -0.03,  0.0,  -0.10, 0.0,
             1.45,  1.45,
             0.15, -0.15,
            -0.50,  0.50,
            -1.20,  1.20,
             0.50,  0.50
        ]
        try:
            self.motion.setStiffnesses(names, 1.0)
            # Step forward & cross arms across chest
            self.stage_move(0.22, 0.0, 0.35, async_move=True)
            self.motion.angleInterpolationWithSpeed(names, cross_arms_pose, 0.60)

            # Spin/land into wide SIUUUU power pose + roar "SIUUUUUU!"
            self.disco_leds(4.5)
            self.start_song("/tmp/kids_siuuu.wav")
            self.start_song(SFX_APPLAUSE_OGG)
            self.tts.post.say("\\rspd=80\\ \\vct=85\\ Siuuuuuuuuuu!")
            self.stage_move(0.0, 0.0, -0.35, async_move=True)
            self.motion.angleInterpolationWithSpeed(names, siuuu_land_pose, 0.75)
            time.sleep(1.8)

            # Return smoothly
            self.stage_move(-0.22, 0.0, 0.0, async_move=True)
            self.motion.angleInterpolationWithSpeed(names, neutral_pose, 0.40)
        except Exception:
            pass
        self.stop_all_songs()
        self.reset_leds()

    def cmd_lm_messi_pose(self):
        """lm: Lionel Messi Signature Goal Celebration — Both Hands Pointing Straight Up & Looking Up at the Sky!"""
        self.set_tablet_command("soccer")
        # Argentina Sky Blue eyes
        self.set_eye_color(0x38BDF8)
        names = [
            "HipPitch", "KneePitch", "HeadPitch", "HeadYaw",
            "LShoulderPitch", "RShoulderPitch",
            "LShoulderRoll",  "RShoulderRoll",
            "LElbowRoll",     "RElbowRoll",
            "LElbowYaw",      "RElbowYaw",
            "LWristYaw",      "RWristYaw",
            "LHand",          "RHand"
        ]
        # Both arms raised straight up to the sky (-1.48 rad) + head tilted up looking at the sky (-0.52 rad)!
        messi_sky_pose = [
             0.05,  0.0,  -0.52,  0.0,
            -1.48, -1.48,
             0.14, -0.14,
            -0.12,  0.12,
            -0.20,  0.20,
             0.0,   0.0,
             0.65,  0.65
        ]
        neutral_pose = [
            -0.03,  0.0,  -0.10,  0.0,
             1.45,  1.45,
             0.15, -0.15,
            -0.50,  0.50,
            -1.20,  1.20,
             0.0,   0.0,
             0.50,  0.50
        ]
        try:
            self.motion.setStiffnesses(names, 1.0)
            self.stage_move(0.20, 0.0, 0.0, async_move=True)
            self.start_song(SFX_APPLAUSE_OGG)
            self.start_song(SFX_MAGIC_OGG)
            # Raise both hands high up to the sky & look straight up!
            self.motion.angleInterpolationWithSpeed(names, messi_sky_pose, 0.45)
            # Gentle celebratory sway while holding both hands up and looking at the sky
            self.motion.angleInterpolationWithSpeed(["HeadYaw", "HipRoll"], [ 0.18,  0.10], 0.25)
            self.motion.angleInterpolationWithSpeed(["HeadYaw", "HipRoll"], [-0.18, -0.10], 0.25)
            self.motion.angleInterpolationWithSpeed(["HeadYaw", "HipRoll"], [ 0.0,   0.0 ], 0.25)
            time.sleep(1.2)
            self.stage_move(-0.20, 0.0, 0.0, async_move=True)
            self.motion.angleInterpolationWithSpeed(names, neutral_pose, 0.40)
        except Exception:
            pass
        self.stop_all_songs()
        self.reset_leds()

    def cmd_3_air_guitar_rock(self):
        """3: No speech — immediate Electric Air Guitar Song & Rock Dance."""
        self.set_tablet_command(3)
        self.set_eye_color(0xFF0055)
        self.run_anim("animations/Stand/Waiting/AirGuitar_1")
        self.disco_leds(4.0)
        self.start_song(SONG_GUITAR_OGG)
        self.dance_wave_boogie(cycles=2)
        self.stop_all_songs()
        self.reset_leds()

    def cmd_4_kungfu_knight(self):
        """4: No speech — immediate Kung Fu & Sword Dance with energetic hyper beat."""
        self.set_tablet_command(4)
        self.set_eye_color(0xFF8800)
        self.start_song(SONG_HYPER_WAV)
        self.run_anim("animations/Stand/Waiting/KungFu_1")
        self.set_eye_color(0xFFD700)
        self.run_anim("animations/Stand/Waiting/Knight_1")
        self.stop_all_songs()
        self.reset_leds()

    def cmd_5_monster_elephant(self):
        """5: No speech — immediate Elephant sound + Monster & Zombie action."""
        self.set_tablet_command(5)
        self.set_eye_color(0x00FF00)
        self.start_song(SFX_ELEPHANT_OGG)
        self.dance_wave_boogie(cycles=1)
        self.stop_all_songs()
        self.run_anim("animations/Stand/Waiting/Monster_1")
        self.run_anim("animations/Stand/Waiting/Zombie_1")
        self.reset_leds()

    def cmd_6_helicopter_spaceship(self):
        """6: No speech — immediate Helicopter Spin & Rocket Blast-Off."""
        self.set_tablet_command(6)
        self.set_eye_color(0x00E5FF)
        self.run_anim("animations/Stand/Waiting/Helicopter_1")
        self.disco_leds(4.5)
        self.run_anim("animations/Stand/Waiting/SpaceShuttle_1")
        self.reset_leds()

    def cmd_7_penguin_workout_dance(self):
        """7: No speech — immediate Electro-Funk Song + Penguin Waddle (+ Stage Step) & Robot Dance."""
        self.set_tablet_command(7)
        self.disco_leds(9.0)
        self.start_song(SONG_FUNK_WAV)
        self.stage_move(0.18, 0.0, 0.0, async_move=True)
        self.run_anim("animations/Stand/Waiting/Waddle_1")
        self.stage_move(-0.18, 0.0, 0.0, async_move=True)
        self.dance_robot_pop()
        self.stop_all_songs()
        self.run_anim("animations/Stand/Waiting/ShowMuscles_1")
        self.reset_leds()

    def cmd_8_magic_light_show(self):
        """8: No speech — immediate Rainbow Eye Colors + Star Wars R2-D2 & Magic Power."""
        self.set_tablet_command(8)
        for hex_val in [0xFF0000, 0x0066FF, 0x00FF44, 0xFFFF00, 0xAA00FF]:
            self.set_eye_color(hex_val)
            time.sleep(0.2)
        self.disco_leds(5.0)
        self.start_song(SFX_R2D2_OGG)
        self.run_anim("animations/Stand/Waiting/MysticalPower_1")
        self.stop_all_songs()
        self.reset_leds()

    def cmd_p_photo(self):
        """p: Keeps Pepper's face straight at the front, says 'Let's take a picture! Three, two, one, cheese!', snaps & shows."""
        import shutil
        awareness = None
        speak_move = None
        try:
            awareness = ALProxy("ALBasicAwareness", PEPPER_IP, PEPPER_PORT)
            awareness.pauseAwareness()
        except Exception:
            pass
        try:
            speak_move = ALProxy("ALSpeakingMovement", PEPPER_IP, PEPPER_PORT)
            speak_move.setEnabled(False)
        except Exception:
            pass

        def _look_straight_front():
            try:
                self.motion.setStiffnesses(["HeadYaw", "HeadPitch", "HipRoll", "HipPitch"], 1.0)
                self.motion.angleInterpolationWithSpeed(
                    ["HeadYaw", "HeadPitch", "HipRoll", "HipPitch"],
                    [0.0, 0.0, 0.0, 0.0],
                    0.35
                )
            except Exception:
                pass

        rad = math.pi / 180.0
        arm_names = [
            "LShoulderPitch", "RShoulderPitch",
            "LShoulderRoll",  "RShoulderRoll",
            "LElbowRoll",     "RElbowRoll",
            "LElbowYaw",      "RElbowYaw",
            "LWristYaw",      "RWristYaw",
            "LHand",          "RHand"
        ]
        # Raise both hands up in front to hold an imaginary camera (while head stays locked at front!)
        camera_hold_pose = [
            -29.3*rad, -29.3*rad,
             27.4*rad, -27.4*rad,
            -88.5*rad,  88.5*rad,
            -46.5*rad,  46.5*rad,
             13.6*rad, -13.6*rad,
             1.0,       1.0
        ]
        camera_neutral_pose = [
             86.3*rad,  86.2*rad,
              6.7*rad,  -7.3*rad,
            -25.5*rad,  24.0*rad,
            -66.9*rad,  66.1*rad,
              7.5*rad,  10.2*rad,
              0.3,       0.3
        ]

        # 1. Center Pepper's face straight at the front & raise both hands into camera pose
        _look_straight_front()
        self.set_tablet_command("c")
        self.set_eye_color(0x00E5FF)
        try:
            self.motion.post.angleInterpolationWithSpeed(arm_names, camera_hold_pose, 0.35)
        except Exception:
            pass

        self.say("Let's take a picture! Three, two, one, cheese!")

        # 2. Keep face locked straight at the front & click fingers on shutter button!
        _look_straight_front()
        try:
            self.motion.setAngles(["LHand", "RHand"], [0.12, 0.12], 0.8)
            time.sleep(0.18)
            self.motion.setAngles(["LHand", "RHand"], [1.0, 1.0], 0.8)
        except Exception:
            pass

        self.set_eye_color(0xFFFFFF)
        self.start_song(SFX_CAMERA_OGG)

        app_dir  = "/home/nao/.local/share/PackageManager/apps/laurimate-1e47c7"
        html_dir = "/home/nao/.local/share/PackageManager/apps/laurimate-1e47c7/html"
        main_jpg = os.path.join(app_dir, "kids_photo.jpg")
        html_jpg = os.path.join(html_dir, "kids_photo.jpg")

        try:
            if not self.photo:
                self.photo = ALProxy("ALPhotoCapture", PEPPER_IP, PEPPER_PORT)
                self.photo.setCameraID(0)
                self.photo.setResolution(2)
                self.photo.setPictureFormat("jpg")
            self.photo.takePicture(app_dir, "kids_photo")
            if os.path.exists(main_jpg) and os.path.exists(html_dir):
                shutil.copyfile(main_jpg, html_jpg)
            print("[Kids Fun] Captured photo: {}".format(main_jpg))
        except Exception as e:
            print("[Kids Fun] Photo capture error: {}".format(e))

        self.set_tablet_command("p")
        self.disco_leds(3.5)
        self.start_song(SFX_APPLAUSE_OGG)
        # Lower hands back down while keeping face straight at the front
        try:
            self.motion.post.angleInterpolationWithSpeed(arm_names, camera_neutral_pose, 0.35)
        except Exception:
            pass
        _look_straight_front()
        time.sleep(1.5)
        self.reset_leds()

        if speak_move:
            try:
                speak_move.setEnabled(True)
            except Exception:
                pass
        if awareness:
            try:
                awareness.resumeAwareness()
            except Exception:
                pass

    def cmd_g_freeze_dance_game(self):
        """g: Fast Freeze Dance ('Dance!' -> Energetic EDM & Dance -> 'Freeze!')."""
        self.set_tablet_command(2)
        self.disco_leds(8.0)
        self.say("Let's dance!")
        self.start_song(SONG_EDM_WAV)
        self.dance_wave_boogie(cycles=2)
        self.stop_all_songs()

        self.set_eye_color(0xFF0000)
        self.say("Freeze!")
        time.sleep(2.2)

        self.disco_leds(5.0)
        self.start_song(SONG_HYPER_WAV)
        self.dance_robot_pop()
        self.stop_all_songs()

        self.set_eye_color(0xFF0000)
        self.say("Freeze!")
        time.sleep(1.8)
        self.start_song(SFX_APPLAUSE_OGG)
        self.run_anim("animations/Stand/Emotions/Positive/Winner_1")
        self.reset_leds()

    def cmd_l_hug_and_song(self):
        """l: Short 'Big robot hug!' + Hug & Celebration."""
        self.set_tablet_command("l")
        self.set_eye_color(0xFF4B72)
        self.say("Big robot hug!")
        self.run_anim("animations/Stand/Waiting/LoveYou_1")
        self.reset_leds()

    def cmd_b_birthday_dance(self):
        """b: Happy Birthday Song & Celebration Dance."""
        self.set_tablet_command("bday")
        self.disco_leds(7.0)
        self.run_anim("animations/Stand/Waiting/HappyBirthday_1")
        self.run_anim("animations/Stand/Emotions/Positive/Ecstatic_1")
        self.reset_leds()

    def cmd_c_race_car(self):
        """c: Race Car Driver (Engine start, driving & crash sound FX)."""
        self.set_tablet_command("car")
        self.set_eye_color(0xFF3300)
        self.run_anim("animations/Stand/Waiting/DriveCar_1")
        self.reset_leds()

    def cmd_e_elephant_dance(self):
        """e: Authentic Full-Body Elephant Choreography (from Laurea Event) + Elephant Trumpet!"""
        self.set_tablet_command("ele")
        self.set_eye_color(0x22C55E)
        self.start_song(SFX_ELEPHANT_OGG)
        try:
            rad = math.pi / 180.0
            names = ["HipPitch", "KneePitch", "HeadPitch", "HeadYaw", "LShoulderPitch", "LElbowRoll", "RShoulderPitch", "RElbowRoll", "RWristYaw"]
            # Bow forward + left hand on nose + swing right arm like an elephant trunk 3 times
            down_pose = [-45.0*rad, 18.0*rad, 28.0*rad, -21.0*rad, -23.0*rad, -89.0*rad,  30.0*rad, 30.0*rad, -73.0*rad]
            up_pose   = [-10.0*rad,  2.0*rad,  8.0*rad, -21.0*rad, -37.0*rad, -88.0*rad, -30.0*rad,  2.0*rad, -73.0*rad]
            for _ in range(2):
                self.motion.angleInterpolationWithSpeed(names, down_pose, 0.35)
                self.motion.angleInterpolationWithSpeed(names, up_pose,   0.35)
            # Return neutral
            self.motion.angleInterpolationWithSpeed(names, [-2.0*rad, 0.0, -10.0*rad, 0.0, 88.0*rad, -29.0*rad, 88.0*rad, 29.0*rad, 0.0], 0.35)
        except Exception:
            pass
        self.stop_all_songs()
        self.reset_leds()

    def cmd_o_gorilla(self):
        """o: Chest-Beating Gorilla Full-Body Choreography + Gorilla Roar & Chest-Thump Sound FX!"""
        self.set_tablet_command(5)
        self.set_eye_color(0xFF8800)
        self.start_song(SFX_MONSTER_OGG)
        self.start_song("/tmp/kids_gorilla_thump.wav")
        try:
            rad = math.pi / 180.0
            names = ["HipPitch", "HipRoll", "HeadYaw", "LShoulderPitch", "LShoulderRoll", "LElbowRoll", "RShoulderPitch", "RShoulderRoll", "RElbowRoll", "LHand", "RHand"]
            beat_left  = [7.5*rad,  5.0*rad,  5.0*rad, -9.0*rad, 11.0*rad, -87.0*rad,  8.2*rad, -23.0*rad,  1.0*rad, 0.02, 0.02]
            beat_right = [7.5*rad, -5.0*rad, -5.0*rad,  8.2*rad, 23.0*rad,  -1.0*rad, -9.0*rad, -11.0*rad, 87.0*rad, 0.02, 0.02]
            for i in range(4):
                if i == 2:
                    self.start_song(SFX_GORILLA_OGG)
                self.motion.angleInterpolationWithSpeed(names, beat_left,  0.55)
                self.motion.angleInterpolationWithSpeed(names, beat_right, 0.55)
            self.motion.angleInterpolationWithSpeed(names, [-2.0*rad, 0.0, 0.0, 88.0*rad, 8.0*rad, -29.0*rad, 88.0*rad, -8.0*rad, 29.0*rad, 0.6, 0.6], 0.4)
        except Exception:
            pass
        self.stop_all_songs()
        self.reset_leds()

    def cmd_i_mouse(self):
        """i: Tiny Nibbling Mouse Full-Body Choreography + Mouse Squeak & Sniffing Sound FX!"""
        self.set_tablet_command("shy")
        self.set_eye_color(0xFDE047)
        self.start_song("/tmp/kids_mouse_squeak.wav")
        self.start_song(SFX_SNIFF_OGG)
        try:
            rad = math.pi / 180.0
            names = ["HipPitch", "KneePitch", "HeadPitch", "LShoulderPitch", "LElbowRoll", "LElbowYaw", "LWristYaw", "RShoulderPitch", "RElbowRoll", "RElbowYaw", "RWristYaw"]
            crouch = [-38.0*rad, 20.0*rad, -5.0*rad, 1.5*rad, -82.0*rad, -56.0*rad, -52.0*rad, 1.0*rad, 82.0*rad, 54.0*rad, 52.0*rad]
            self.motion.angleInterpolationWithSpeed(names, crouch, 0.35)
            self.start_song("/tmp/kids_mouse_squeak.wav")
            # Rapid little mouse paw nibbles & head twitches
            for _ in range(4):
                self.motion.setAngles(["LHand", "RHand", "HeadPitch"], [0.12, 0.12, -12.0*rad], 0.8)
                time.sleep(0.18)
                self.motion.setAngles(["LHand", "RHand", "HeadPitch"], [0.35, 0.35, -2.0*rad], 0.8)
                time.sleep(0.18)
            self.motion.angleInterpolationWithSpeed(names, [-2.0*rad, 0.0, -10.0*rad, 88.0*rad, -29.0*rad, -70.0*rad, 0.0, 88.0*rad, 29.0*rad, 70.0*rad, 0.0], 0.35)
        except Exception:
            pass
        self.stop_all_songs()
        self.reset_leds()

    def cmd_a_animal_safari(self):
        """a: Mega Zoo Animal Safari Show (Elephant -> Mouse -> Gorilla -> Lion -> Dog -> Cat -> Dinosaur!)."""
        self.say("Watch my mega animal show!")
        self.cmd_e_elephant_dance()
        self.cmd_i_mouse()
        self.cmd_o_gorilla()
        self.cmd_li_lion()
        self.cmd_do_dog()
        self.cmd_ca_cat()
        self.cmd_di_dinosaur()
        self.start_song(SFX_APPLAUSE_OGG)
        self.run_anim("animations/Stand/Emotions/Positive/Winner_1")

    def cmd_li_lion(self):
        """li: King Lion / Tiger Roar, Claw Pounce & Stage Lunge!"""
        self.set_tablet_command("lion")
        self.set_eye_color(0xFF8800)
        self.start_song(SFX_MONSTER_OGG)
        self.stage_move(0.22, 0.0, 0.0, async_move=True)
        try:
            rad = math.pi / 180.0
            names = ["HipPitch", "HeadPitch", "HeadYaw", "LShoulderPitch", "LShoulderRoll", "LElbowRoll", "RShoulderPitch", "RShoulderRoll", "RElbowRoll", "LHand", "RHand"]
            pounce1 = [-22.0*rad, -12.0*rad,  18.0*rad, -35.0*rad, 25.0*rad, -75.0*rad, -35.0*rad, -25.0*rad, 75.0*rad, 0.95, 0.95]
            pounce2 = [ -5.0*rad,   8.0*rad, -18.0*rad,  15.0*rad, 10.0*rad, -40.0*rad,  15.0*rad, -10.0*rad, 40.0*rad, 0.20, 0.20]
            for i in range(2):
                if i == 1:
                    self.start_song(SFX_GORILLA_OGG)
                self.motion.angleInterpolationWithSpeed(names, pounce1, 0.5)
                self.motion.angleInterpolationWithSpeed(names, pounce2, 0.5)
            self.motion.angleInterpolationWithSpeed(names, [-2.0*rad, -10.0*rad, 0.0, 88.0*rad, 8.0*rad, -29.0*rad, 88.0*rad, -8.0*rad, 29.0*rad, 0.6, 0.6], 0.4)
        except Exception:
            pass
        self.stage_move(-0.22, 0.0, 0.0, async_move=True)
        self.stop_all_songs()
        self.reset_leds()

    def cmd_di_dinosaur(self):
        """di: Giant T-Rex Dinosaur Heavy Stomp, Tiny Arms & Fierce Roar!"""
        self.set_tablet_command("dino")
        self.set_eye_color(0x22C55E)
        self.start_song("/tmp/kids_dino_stomp.wav")
        self.start_song(SFX_MONSTER_OGG)
        try:
            rad = math.pi / 180.0
            names = ["HipPitch", "KneePitch", "HipRoll", "HeadPitch", "HeadYaw", "LShoulderPitch", "LElbowRoll", "RShoulderPitch", "RElbowRoll", "LHand", "RHand"]
            stomp_l = [-32.0*rad, 15.0*rad,  14.0*rad, -15.0*rad,  25.0*rad, 25.0*rad, -88.0*rad, 25.0*rad, 88.0*rad, 0.2, 0.2]
            stomp_r = [-32.0*rad, 15.0*rad, -14.0*rad,   5.0*rad, -25.0*rad, 25.0*rad, -88.0*rad, 25.0*rad, 88.0*rad, 0.2, 0.2]
            self.stage_move(0.20, 0.0, 0.25, async_move=True)
            for _ in range(2):
                self.motion.angleInterpolationWithSpeed(names, stomp_l, 0.45)
                self.motion.angleInterpolationWithSpeed(names, stomp_r, 0.45)
            self.stage_move(-0.20, 0.0, -0.25, async_move=True)
            self.motion.angleInterpolationWithSpeed(names, [-2.0*rad, 0.0, 0.0, -10.0*rad, 0.0, 88.0*rad, -29.0*rad, 88.0*rad, 29.0*rad, 0.6, 0.6], 0.4)
        except Exception:
            pass
        self.stop_all_songs()
        self.reset_leds()

    def cmd_do_dog(self):
        """do: Playful Puppy Dog Barking, Sniffing & Happy Tail-Wag Stage Bounce!"""
        self.set_tablet_command("dog")
        self.set_eye_color(0xFBBF24)
        self.start_song("/tmp/kids_dog_bark.wav")
        self.stage_move(0.20, 0.0, 0.0, async_move=True)
        try:
            rad = math.pi / 180.0
            names = ["HipPitch", "HipRoll", "HeadPitch", "HeadYaw", "LShoulderPitch", "LElbowRoll", "RShoulderPitch", "RElbowRoll"]
            wag_l = [-18.0*rad,  15.0*rad, -14.0*rad,  20.0*rad, 35.0*rad, -85.0*rad, 35.0*rad, 85.0*rad]
            wag_r = [-18.0*rad, -15.0*rad, -14.0*rad, -20.0*rad, 35.0*rad, -85.0*rad, 35.0*rad, 85.0*rad]
            for i in range(3):
                if i == 1:
                    self.start_song(SFX_SNIFF_OGG)
                elif i == 2:
                    self.start_song("/tmp/kids_dog_bark.wav")
                self.motion.angleInterpolationWithSpeed(names, wag_l, 0.55)
                self.motion.angleInterpolationWithSpeed(names, wag_r, 0.55)
            self.motion.angleInterpolationWithSpeed(names, [-2.0*rad, 0.0, -10.0*rad, 0.0, 88.0*rad, -29.0*rad, 88.0*rad, 29.0*rad], 0.4)
        except Exception:
            pass
        self.stage_move(-0.20, 0.0, 0.0, async_move=True)
        self.stop_all_songs()
        self.reset_leds()

    def cmd_ca_cat(self):
        """ca: Cute Kitty Cat Meow, Paw Face-Wash & Graceful Stage Turn!"""
        self.set_tablet_command("cat")
        self.set_eye_color(0xF472B6)
        self.start_song("/tmp/kids_cat_meow.wav")
        self.stage_move(0.15, 0.12, 0.25, async_move=True)
        try:
            rad = math.pi / 180.0
            names = ["HeadPitch", "HeadYaw", "HipRoll", "RShoulderPitch", "RShoulderRoll", "RElbowRoll", "RElbowYaw", "RHand"]
            wash1 = [ 5.0*rad, -12.0*rad,  10.0*rad, -25.0*rad, -5.0*rad, 88.0*rad, 40.0*rad, 0.2]
            wash2 = [-8.0*rad, -12.0*rad, -10.0*rad,   5.0*rad, -5.0*rad, 70.0*rad, 40.0*rad, 0.5]
            for i in range(3):
                if i == 2:
                    self.start_song("/tmp/kids_cat_meow.wav")
                self.motion.angleInterpolationWithSpeed(names, wash1, 0.45)
                self.motion.angleInterpolationWithSpeed(names, wash2, 0.45)
            self.motion.angleInterpolationWithSpeed(names, [-10.0*rad, 0.0, 0.0, 88.0*rad, -8.0*rad, 29.0*rad, 70.0*rad, 0.6], 0.4)
        except Exception:
            pass
        self.stage_move(-0.15, -0.12, -0.25, async_move=True)
        self.stop_all_songs()
        self.reset_leds()

    def cmd_bi_bird(self):
        """bi: Soaring Eagle / Songbird Chirps, Flapping Wings & Stage Glide!"""
        self.set_tablet_command("bird")
        self.set_eye_color(0x38BDF8)
        self.start_song("/tmp/kids_bird_chirp.wav")
        self.stage_move(0.20, 0.0, 0.35, async_move=True)
        self.run_anim("animations/Stand/Gestures/Wings_1")
        self.start_song("/tmp/kids_bird_chirp.wav")
        self.stage_move(-0.20, 0.0, -0.35, async_move=True)
        self.run_anim("animations/Stand/Gestures/Wings_2")
        self.stop_all_songs()
        self.reset_leds()

    def cmd_fr_frog(self):
        """fr: Jumping Green Frog 'Ribbit! Ribbit!' Crouch & Stage Hop!"""
        self.set_tablet_command("frog")
        self.set_eye_color(0x4ADE80)
        self.start_song("/tmp/kids_frog_ribbit.wav")
        try:
            rad = math.pi / 180.0
            names = ["HipPitch", "KneePitch", "HeadPitch", "LShoulderPitch", "RShoulderPitch", "LElbowRoll", "RElbowRoll"]
            crouch_pose = [-45.0*rad, 22.0*rad,  15.0*rad,  45.0*rad,  45.0*rad, -75.0*rad, 75.0*rad]
            jump_pose   = [  2.0*rad, -2.0*rad, -20.0*rad, -45.0*rad, -45.0*rad, -15.0*rad, 15.0*rad]
            for i in range(2):
                if i == 1:
                    self.start_song("/tmp/kids_frog_ribbit.wav")
                self.motion.angleInterpolationWithSpeed(names, crouch_pose, 0.45)
                self.stage_move(0.18 if i == 0 else -0.18, 0.0, 0.0, async_move=True)
                self.motion.angleInterpolationWithSpeed(names, jump_pose, 0.65)
            self.motion.angleInterpolationWithSpeed(names, [-2.0*rad, 0.0, -10.0*rad, 88.0*rad, 88.0*rad, -29.0*rad, 29.0*rad], 0.4)
        except Exception:
            pass
        self.stop_all_songs()
        self.reset_leds()

    # --------------------------------------------------------------
    # Domestic & Farm Animals Shows (Cow, Sheep, Horse, Duck, Chicken, Pig & Farm Show!)
    # --------------------------------------------------------------
    def cmd_cw_cow(self):
        """cw: Dairy Farm Cow — Deep 'Moooooo!' Sound + Cow Horns Gesture & Grazing Sway!"""
        self.set_tablet_command("cow")
        self.set_eye_color(0xFFFFFF)
        self.start_song("/tmp/kids_cow_moo.wav")
        self.tts.post.say("\\rspd=75\\ \\vct=75\\ Moooooooo!")
        try:
            rad = math.pi / 180.0
            names = ["HipPitch", "HipRoll", "HeadPitch", "HeadYaw", "LShoulderPitch", "LShoulderRoll", "LElbowRoll", "RShoulderPitch", "RShoulderRoll", "RElbowRoll"]
            # Raise both hands beside head like cow horns while swaying and grazing
            moo_left  = [-22.0*rad,  14.0*rad,  12.0*rad,  18.0*rad, -30.0*rad, 25.0*rad, -85.0*rad, -30.0*rad, -25.0*rad, 85.0*rad]
            moo_right = [-22.0*rad, -14.0*rad, -10.0*rad, -18.0*rad, -30.0*rad, 25.0*rad, -85.0*rad, -30.0*rad, -25.0*rad, 85.0*rad]
            for _ in range(2):
                self.motion.angleInterpolationWithSpeed(names, moo_left,  0.45)
                self.motion.angleInterpolationWithSpeed(names, moo_right, 0.45)
            self.motion.angleInterpolationWithSpeed(names, [-2.0*rad, 0.0, -10.0*rad, 0.0, 88.0*rad, 8.0*rad, -29.0*rad, 88.0*rad, -8.0*rad, 29.0*rad], 0.4)
        except Exception:
            pass
        self.stop_all_songs()
        self.reset_leds()

    def cmd_sh_sheep(self):
        """sh: Fluffy Farm Sheep — 'Baaaaa! Baaaaa!' Bleat & Happy Woolly Hop!"""
        self.set_tablet_command("sheep")
        self.set_eye_color(0xE0F2FE)
        self.start_song("/tmp/kids_sheep_baa.wav")
        self.tts.post.say("\\rspd=85\\ \\vct=115\\ Baaaaaa! Baaaaaa!")
        try:
            rad = math.pi / 180.0
            names = ["HipPitch", "KneePitch", "HeadPitch", "HeadYaw", "LShoulderPitch", "RShoulderPitch", "LElbowRoll", "RElbowRoll"]
            baa1 = [-25.0*rad, 12.0*rad, -14.0*rad,  16.0*rad, 35.0*rad, 35.0*rad, -82.0*rad, 82.0*rad]
            baa2 = [ -4.0*rad,  0.0,       8.0*rad, -16.0*rad, 55.0*rad, 55.0*rad, -60.0*rad, 60.0*rad]
            for _ in range(2):
                self.motion.angleInterpolationWithSpeed(names, baa1, 0.50)
                self.motion.angleInterpolationWithSpeed(names, baa2, 0.50)
            self.motion.angleInterpolationWithSpeed(names, [-2.0*rad, 0.0, -10.0*rad, 0.0, 88.0*rad, 88.0*rad, -29.0*rad, 29.0*rad], 0.4)
        except Exception:
            pass
        self.stop_all_songs()
        self.reset_leds()

    def cmd_ho_horse(self):
        """ho: Galloping Farm Horse — 'Neeeigh!' Whinny + Hoof Clops + Riding Reins Gallop!"""
        self.set_tablet_command("horse")
        self.set_eye_color(0xF59E0B)
        self.start_song("/tmp/kids_horse_neigh.wav")
        try:
            rad = math.pi / 180.0
            names = ["HipPitch", "KneePitch", "HeadPitch", "LShoulderPitch", "RShoulderPitch", "LElbowRoll", "RElbowRoll", "LHand", "RHand"]
            # Hold horse reins with both hands in front and gallop up & down!
            gallop_up   = [ -4.0*rad,  0.0,     -16.0*rad, 15.0*rad, 15.0*rad, -75.0*rad, 75.0*rad, 0.1, 0.1]
            gallop_down = [-30.0*rad, 15.0*rad,  10.0*rad, 35.0*rad, 35.0*rad, -55.0*rad, 55.0*rad, 0.1, 0.1]
            for _ in range(3):
                self.motion.angleInterpolationWithSpeed(names, gallop_up,   0.55)
                self.motion.angleInterpolationWithSpeed(names, gallop_down, 0.55)
            self.motion.angleInterpolationWithSpeed(names, [-2.0*rad, 0.0, -10.0*rad, 88.0*rad, 88.0*rad, -29.0*rad, 29.0*rad, 0.6, 0.6], 0.4)
        except Exception:
            pass
        self.stop_all_songs()
        self.reset_leds()

    def cmd_du_duck(self):
        """du: Waddling Farm Duck — 'Quack! Quack! Quack!' + Wing Flap & Waddle!"""
        self.set_tablet_command("duck")
        self.set_eye_color(0xFDE047)
        self.start_song("/tmp/kids_duck_quack.wav")
        self.tts.post.say("Quack, quack, quack!")
        self.run_anim("animations/Stand/Waiting/Waddle_1")
        self.stop_all_songs()
        self.reset_leds()

    def cmd_ch_chicken(self):
        """ch: Farm Chicken / Rooster — 'Cluck, cluck, Cock-a-doodle-doo!' + Chicken Wing Flap & Peck!"""
        self.set_tablet_command("chicken")
        self.set_eye_color(0xEF4444)
        self.start_song("/tmp/kids_chicken_cluck.wav")
        try:
            rad = math.pi / 180.0
            names = ["HipPitch", "HeadPitch", "LShoulderPitch", "RShoulderPitch", "LShoulderRoll", "RShoulderRoll", "LElbowRoll", "RElbowRoll"]
            flap_out = [-15.0*rad,  18.0*rad, 40.0*rad, 40.0*rad, 48.0*rad, -48.0*rad, -89.0*rad, 89.0*rad]
            flap_in  = [ -3.0*rad, -15.0*rad, 40.0*rad, 40.0*rad,  8.0*rad,  -8.0*rad, -89.0*rad, 89.0*rad]
            for _ in range(3):
                self.motion.angleInterpolationWithSpeed(names, flap_out, 0.60)
                self.motion.angleInterpolationWithSpeed(names, flap_in,  0.60)
            self.motion.angleInterpolationWithSpeed(names, [-2.0*rad, -10.0*rad, 88.0*rad, 88.0*rad, 8.0*rad, -8.0*rad, -29.0*rad, 29.0*rad], 0.4)
        except Exception:
            pass
        self.stop_all_songs()
        self.reset_leds()

    def cmd_pg_pig(self):
        """pg: Happy Farm Piggy — 'Oink! Oink! Snort!' + Piggy Snout Wiggle Dance!"""
        self.set_tablet_command("pig")
        self.set_eye_color(0xF472B6)
        self.start_song("/tmp/kids_pig_oink.wav")
        self.start_song(SFX_SNIFF_OGG)
        self.tts.post.say("Oink, oink, oink!")
        self.dance_wave_boogie(cycles=2)
        self.stop_all_songs()
        self.reset_leds()

    def cmd_fa_farm_show(self):
        """fa: Old MacDonald Domestic & Farm Animals Show (Cow -> Sheep -> Horse -> Duck -> Chicken -> Pig -> Dog -> Cat)!"""
        self.say("Welcome to the farm! Listen to the farm animals!")
        self.cmd_cw_cow()
        self.cmd_sh_sheep()
        self.cmd_ho_horse()
        self.cmd_du_duck()
        self.cmd_ch_chicken()
        self.cmd_pg_pig()
        self.cmd_do_dog()
        self.cmd_ca_cat()
        self.start_song(SFX_APPLAUSE_OGG)
        self.run_anim("animations/Stand/Emotions/Positive/Winner_1")

    def cmd_t_taichi_dance(self):
        """t: Traditional Tai Chi Chuan Chinese Martial Arts Dance with Music!"""
        self.set_tablet_command(4)
        self.disco_leds(14.0)
        self.start_song(SONG_TAICHI_MP3)
        try:
            rad = math.pi / 180.0
            names = ["HipPitch", "KneePitch", "HeadYaw", "HeadPitch", "LShoulderPitch", "LShoulderRoll", "LElbowRoll", "RShoulderPitch", "RShoulderRoll", "RElbowRoll"]
            poses = [
                [-17.0*rad,  5.7*rad,   0.0,       0.0,      110.0*rad, 20.0*rad, -60.0*rad, 110.0*rad, -20.0*rad, 60.0*rad],
                [-25.0*rad, 10.2*rad,  18.0*rad,  19.0*rad,   21.0*rad, 40.0*rad, -95.0*rad,  10.0*rad,  -4.0*rad, 71.0*rad],
                [ -3.0*rad,  0.0,     -68.0*rad,   0.0,       11.0*rad,  5.0*rad, -85.0*rad,  60.0*rad, -87.0*rad,  4.0*rad],
                [ -3.0*rad,  0.0,      90.0*rad,  -5.0*rad,  -17.0*rad, 66.0*rad,   0.0,      -4.0*rad,   0.0,     72.0*rad],
                [-25.0*rad, 10.2*rad,   0.0,      28.0*rad,   27.0*rad, 10.0*rad, -51.0*rad,  27.0*rad, -10.0*rad, 51.0*rad],
                [ -3.0*rad,  0.0,     -90.0*rad,  -5.0*rad,   -4.0*rad,  0.0,     -72.0*rad, -17.0*rad, -66.0*rad,  2.0*rad],
                [ -2.0*rad,  0.0,       0.0,     -10.0*rad,   87.0*rad,  6.0*rad, -22.0*rad,  86.0*rad,  -6.0*rad, 22.0*rad]
            ]
            for p in poses:
                self.motion.angleInterpolationWithSpeed(names, p, 0.28)
        except Exception:
            pass
        self.stop_all_songs()
        self.run_anim("animations/Stand/Gestures/BowShort_1")
        self.reset_leds()

    def cmd_x_vacuum_cleaner(self):
        """x: Funny Vacuum Cleaner Robot (Loud vacuum sound + sweeping floor!)."""
        self.set_tablet_command(7)
        self.set_eye_color(0x00E5FF)
        self.start_song(SFX_VACUUM_OGG)
        self.run_anim("animations/Stand/Gestures/ShowFloor_1")
        self.run_anim("animations/Stand/Gestures/ShowFloor_3")
        self.run_anim("animations/Stand/Gestures/ShowFloor_4")
        self.stop_all_songs()
        self.reset_leds()

    def cmd_n_golf_swing(self):
        """n: Pro Golf Swing + Ball Hit Sound + Watching Ball Fly Far Away!"""
        self.set_tablet_command("win")
        self.set_eye_color(0x4ADE80)
        self.start_song(SFX_GOLF_OGG)
        self.run_anim("animations/Stand/Gestures/ShowFloor_2")
        self.run_anim("animations/Stand/Gestures/Far_1")
        self.stop_all_songs()
        self.start_song(SFX_APPLAUSE_OGG)
        self.run_anim("animations/Stand/Emotions/Positive/Winner_2")
        self.reset_leds()

    def cmd_j_mime_and_bird(self):
        """j: Invisible Glass Wall Mime + Eagle Bird Flying Wings!"""
        self.set_tablet_command(6)
        self.disco_leds(7.0)
        self.run_anim("animations/Stand/Gestures/Mime_1")
        self.run_anim("animations/Stand/Gestures/Wings_1")
        self.run_anim("animations/Stand/Gestures/Wings_2")
        self.reset_leds()

    def cmd_r_shake_and_dazzle(self):
        """r: Full-Body Wet Puppy Shake & Dazzled by Bright Lights!"""
        self.set_tablet_command("surp")
        self.disco_leds(6.0)
        self.run_anim("animations/Stand/Reactions/ShakeBody_1")
        self.run_anim("animations/Stand/Reactions/LightShine_1")
        self.reset_leds()

    # --------------------------------------------------------------
    # Dedicated Small-Distance Stage Walking / Rolling Actions
    # --------------------------------------------------------------
    def cmd_wf_walk_forward_back(self):
        """wf: Rolls 25cm forward toward the kids, waves hello, and rolls 25cm back to stage center!"""
        self.set_tablet_command(1)
        self.disco_leds(6.0)
        self.stage_move(0.24, 0.0, 0.0)
        self.run_anim("animations/Stand/Gestures/Hey_1")
        self.stage_move(-0.24, 0.0, 0.0)
        self.reset_leds()

    def cmd_ws_walk_side_dance(self):
        """ws: Glides side-to-side across the stage (left, right, back to center) with music & boogie!"""
        self.set_tablet_command(2)
        self.disco_leds(8.0)
        self.start_song("/tmp/kids_party_song.wav")
        self.stage_move(0.0, 0.20, 0.30)
        self.dance_wave_boogie(cycles=1)
        self.stage_move(0.0, -0.40, -0.60)
        self.dance_wave_boogie(cycles=1)
        self.stage_move(0.0, 0.20, 0.30)
        self.stop_all_songs()
        self.reset_leds()

    def cmd_wr_spin_360(self):
        """wr: Spins a full 360-degree turn right in place on stage with rainbow disco lights!"""
        self.set_tablet_command(2)
        self.disco_leds(6.0)
        self.start_song("/tmp/kids_party_song.wav")
        self.stage_move(0.0, 0.0, 3.14)
        self.stage_move(0.0, 0.0, 3.14)
        self.stop_all_songs()
        self.run_anim("animations/Stand/Emotions/Positive/Happy_4")
        self.reset_leds()

    def cmd_wp_stage_patrol(self):
        """wp: Walks a small 22cm patrol loop around its current stage spot and returns to exact center!"""
        self.set_tablet_command(1)
        self.disco_leds(9.0)
        self.start_song(SONG_DANCE_MP3)
        # Step forward-left, wave, step right, wave, return to center
        self.stage_move(0.20, 0.15, 0.35)
        self.run_anim("animations/Stand/Gestures/Hey_3")
        self.stage_move(0.0, -0.30, -0.70)
        self.run_anim("animations/Stand/Gestures/Hey_1")
        self.stage_move(-0.20, 0.15, 0.35)
        self.stop_all_songs()
        self.reset_leds()

    def cmd_tl_turn_left(self):
        """tl: Turns Pepper ~45 degrees to the LEFT (rotates base wheels if unlocked, and turns head/torso left)."""
        self.disco_leds(2.0)
        try:
            awareness = ALProxy("ALBasicAwareness", PEPPER_IP, PEPPER_PORT)
            awareness.pauseAwareness()
        except Exception:
            pass
        moved = False
        try:
            ils = self.memory.getData("Device/SubDeviceList/Platform/ILS/Sensor/Value") if self.memory else 0.0
            if not (ils and float(ils) > 0.5):
                moved = bool(self.motion.moveTo(0.0, 0.0, 0.785))
        except Exception:
            moved = False
        if not moved:
            # If wheels are locked by charging flap, turn and hold head & upper torso to the LEFT
            try:
                self.motion.setStiffnesses(["HeadYaw", "HeadPitch", "HipRoll"], 1.0)
                self.motion.angleInterpolationWithSpeed(["HeadYaw", "HeadPitch", "HipRoll"], [0.78, -0.08, 0.15], 0.35)
            except Exception:
                pass

    def cmd_tr_turn_right(self):
        """tr: Turns Pepper ~45 degrees to the RIGHT (rotates base wheels if unlocked, and turns head/torso right)."""
        self.disco_leds(2.0)
        try:
            awareness = ALProxy("ALBasicAwareness", PEPPER_IP, PEPPER_PORT)
            awareness.pauseAwareness()
        except Exception:
            pass
        moved = False
        try:
            ils = self.memory.getData("Device/SubDeviceList/Platform/ILS/Sensor/Value") if self.memory else 0.0
            if not (ils and float(ils) > 0.5):
                moved = bool(self.motion.moveTo(0.0, 0.0, -0.785))
        except Exception:
            moved = False
        if not moved:
            # If wheels are locked by charging flap, turn and hold head & upper torso to the RIGHT
            try:
                self.motion.setStiffnesses(["HeadYaw", "HeadPitch", "HipRoll"], 1.0)
                self.motion.angleInterpolationWithSpeed(["HeadYaw", "HeadPitch", "HipRoll"], [-0.78, -0.08, -0.15], 0.35)
            except Exception:
                pass

    def cmd_tc_turn_center(self):
        """tc: Centers Pepper's head and torso straight to the FRONT."""
        self.disco_leds(1.5)
        try:
            self.motion.setStiffnesses(["HeadYaw", "HeadPitch", "HipRoll", "HipPitch"], 1.0)
            self.motion.angleInterpolationWithSpeed(["HeadYaw", "HeadPitch", "HipRoll", "HipPitch"], [0.0, -0.08, 0.0, 0.0], 0.35)
        except Exception:
            pass

    def cmd_wb_walk_back(self):
        """wb: Rolls/steps 24cm BACKWARD on stage."""
        self.disco_leds(2.5)
        self.stage_move(-0.24, 0.0, 0.0)

    # --------------------------------------------------------------
    # Creative Direct-With-Kids Interactions (Handshake, High-Five, Fist Bump, Rock-Paper-Scissors, Head-Shoulders)
    # --------------------------------------------------------------
    def cmd_hs_handshake(self):
        """hs: Interactive Robot Handshake with a Kid! Extends right hand, shakes up & down, and cheers."""
        self.set_tablet_command(1)
        self.disco_leds(6.0)
        self.stage_move(0.15, 0.0, 0.0, async_move=True)
        names = ["RShoulderPitch", "RShoulderRoll", "RElbowYaw", "RElbowRoll", "RWristYaw", "RHand", "HeadPitch", "HeadYaw"]
        # Extend open right hand forward at kid height
        extend_pose = [0.45, -0.10, 1.20, 0.55, 0.0, 0.90, 0.12, -0.10]
        try:
            self.motion.setStiffnesses(names, 1.0)
            self.motion.angleInterpolationWithSpeed(names, extend_pose, 0.40)
        except Exception:
            pass

        self.say("Nice to meet you! Shake my hand!")

        # Wait briefly (or detect hand touch sensor if kid touches back of hand)
        t0 = time.time()
        while (time.time() - t0) < 1.3:
            try:
                if self.memory and float(self.memory.getData("Device/SubDeviceList/RHand/Touch/Back/Sensor/Value") or 0.0) > 0.5:
                    break
            except Exception:
                pass
            time.sleep(0.1)

        # Gently close hand around kid's hand and pump up & down 3 times!
        try:
            self.motion.setAngles("RHand", 0.40, 0.5)
            for _ in range(3):
                self.motion.angleInterpolationWithSpeed(["RShoulderPitch", "RElbowRoll"], [0.30, 0.85], 0.55)
                self.motion.angleInterpolationWithSpeed(["RShoulderPitch", "RElbowRoll"], [0.60, 0.35], 0.55)
            # Release hand & return arm smoothly
            self.motion.setAngles("RHand", 0.90, 0.6)
            time.sleep(0.25)
            self.motion.angleInterpolationWithSpeed(names, [1.45, -0.15, 1.20, 0.50, 0.0, 0.5, -0.10, 0.0], 0.40)
        except Exception:
            pass
        self.stage_move(-0.15, 0.0, 0.0, async_move=True)
        self.reset_leds()

    def cmd_hf_highfive(self):
        """hf: Interactive High-Five with a Kid! Raises open palm, dings & celebrates!"""
        self.set_tablet_command("win")
        self.set_eye_color(0xFDE047)
        self.stage_move(0.15, 0.0, 0.0, async_move=True)
        names = ["RShoulderPitch", "RShoulderRoll", "RElbowYaw", "RElbowRoll", "RWristYaw", "RHand", "HeadPitch"]
        highfive_pose = [-0.25, -0.15, 0.15, 1.15, -1.35, 1.0, -0.12]
        try:
            self.motion.setStiffnesses(names, 1.0)
            self.motion.angleInterpolationWithSpeed(names, highfive_pose, 0.45)
        except Exception:
            pass

        self.say("High five!")

        # Wait up to 1.6s or until hand touch sensor is triggered
        t0 = time.time()
        while (time.time() - t0) < 1.6:
            try:
                if self.memory and float(self.memory.getData("Device/SubDeviceList/RHand/Touch/Back/Sensor/Value") or 0.0) > 0.5:
                    break
            except Exception:
                pass
            time.sleep(0.1)

        self.disco_leds(3.5)
        self.start_song("/home/nao/.local/share/PackageManager/apps/boot-config/sounds/ding.ogg")
        try:
            # High-five bounce back & lower arm
            self.motion.angleInterpolationWithSpeed(["RShoulderPitch", "RElbowRoll"], [-0.45, 1.40], 0.65)
            self.motion.angleInterpolationWithSpeed(names, [1.45, -0.15, 1.20, 0.50, 0.0, 0.5, -0.10], 0.40)
        except Exception:
            pass
        self.stage_move(-0.15, 0.0, 0.0, async_move=True)
        self.reset_leds()

    def cmd_fb_fistbump(self):
        """fb: Cool Robot Fist Bump + 'Boom!' Fireworks Hand Explosion!"""
        self.set_tablet_command(6)
        self.set_eye_color(0x00E5FF)
        self.stage_move(0.15, 0.0, 0.0, async_move=True)
        names = ["RShoulderPitch", "RShoulderRoll", "RElbowYaw", "RElbowRoll", "RWristYaw", "RHand"]
        # Extend closed fist forward
        fist_pose = [0.35, -0.08, 1.20, 0.25, 0.0, 0.0]
        try:
            self.motion.setStiffnesses(names, 1.0)
            self.motion.angleInterpolationWithSpeed(names, fist_pose, 0.45)
        except Exception:
            pass

        self.say("Fist bump!")
        time.sleep(1.2)

        # Bump forward & explode fingers open with rocket sound ("Ba-boom!")
        self.disco_leds(3.5)
        self.start_song(SFX_ROCKET_OGG)
        try:
            self.motion.angleInterpolationWithSpeed(["RShoulderPitch", "RElbowRoll", "RHand"], [0.20, 0.10, 0.0], 0.65)
            self.motion.angleInterpolationWithSpeed(["RShoulderPitch", "RShoulderRoll", "RElbowRoll", "RHand"], [-0.20, -0.45, 0.90, 1.0], 0.65)
            self.motion.angleInterpolationWithSpeed(names, [1.45, -0.15, 1.20, 0.50, 0.0, 0.5], 0.40)
        except Exception:
            pass
        self.stage_move(-0.15, 0.0, 0.0, async_move=True)
        self.stop_all_songs()
        self.reset_leds()

    def cmd_rps_rock_paper_scissors(self):
        """rps: Plays a real physical game of Rock, Paper, Scissors against the kids!"""
        self.set_tablet_command("win")
        self.disco_leds(6.0)
        self.stage_move(0.15, 0.0, 0.0, async_move=True)
        names = ["RShoulderPitch", "RShoulderRoll", "RElbowYaw", "RElbowRoll", "RWristYaw", "RHand"]
        choice_name, hand_val, wrist_val = random.choice([
            ("Rock!",     0.0,  0.0),
            ("Paper!",    1.0, -1.2),
            ("Scissors!", 0.55, 0.0)
        ])
        try:
            self.motion.setStiffnesses(names, 1.0)
            self.motion.angleInterpolationWithSpeed(names, [0.40, -0.10, 1.20, 0.70, 0.0, 0.0], 0.45)
            self.tts.post.say("Rock, paper, scissors, shoot!")
            # Pump fist 3 times
            for _ in range(3):
                self.motion.angleInterpolationWithSpeed(["RShoulderPitch", "RElbowRoll"], [0.25, 0.95], 0.65)
                self.motion.angleInterpolationWithSpeed(["RShoulderPitch", "RElbowRoll"], [0.55, 0.40], 0.65)
            # Throw Rock, Paper, or Scissors!
            self.motion.angleInterpolationWithSpeed(["RShoulderPitch", "RElbowRoll", "RWristYaw", "RHand"], [0.30, 0.35, wrist_val, hand_val], 0.75)
        except Exception:
            pass
        self.say(choice_name)
        self.start_song(SFX_APPLAUSE_OGG)
        time.sleep(1.2)
        try:
            self.motion.angleInterpolationWithSpeed(names, [1.45, -0.15, 1.20, 0.50, 0.0, 0.5], 0.40)
        except Exception:
            pass
        self.stage_move(-0.15, 0.0, 0.0, async_move=True)
        self.reset_leds()

    def cmd_hsk_head_shoulders_knees(self):
        """hsk: 'Head, Shoulders, Knees & Clap!' Interactive Copy-Me Dance with Kids!"""
        self.set_tablet_command(2)
        self.disco_leds(9.0)
        self.say("Touch your head, shoulders, knees, and clap with me!")
        self.start_song("/tmp/kids_party_song.wav")
        try:
            rad = math.pi / 180.0
            names = ["HipPitch", "KneePitch", "LShoulderPitch", "RShoulderPitch", "LShoulderRoll", "RShoulderRoll", "LElbowRoll", "RElbowRoll"]
            # 1. Head
            self.motion.angleInterpolationWithSpeed(names, [0.0, 0.0, -45.0*rad, -45.0*rad, 20.0*rad, -20.0*rad, -88.0*rad, 88.0*rad], 0.55)
            # 2. Shoulders
            self.motion.angleInterpolationWithSpeed(names, [0.0, 0.0,  10.0*rad,  10.0*rad, 15.0*rad, -15.0*rad, -89.0*rad, 89.0*rad], 0.55)
            # 3. Knees (deep bend forward reaching down)
            self.motion.angleInterpolationWithSpeed(names, [-42.0*rad, 20.0*rad, 45.0*rad, 45.0*rad, 10.0*rad, -10.0*rad, -20.0*rad, 20.0*rad], 0.55)
            # 4. Clap / Hands up!
            self.motion.angleInterpolationWithSpeed(names, [0.0, 0.0, -35.0*rad, -35.0*rad,  2.0*rad,  -2.0*rad, -45.0*rad, 45.0*rad], 0.60)
            self.motion.angleInterpolationWithSpeed(names, [-2.0*rad, 0.0, 88.0*rad, 88.0*rad, 8.0*rad, -8.0*rad, -29.0*rad, 29.0*rad], 0.40)
        except Exception:
            pass
        self.stop_all_songs()
        self.start_song(SFX_APPLAUSE_OGG)
        self.run_anim("animations/Stand/Emotions/Positive/Winner_1")
        self.reset_leds()

    # --------------------------------------------------------------
    # Football Superstar Celebrations (Ronaldo "SIUUUU!" & Lionel Messi Sky Point!)
    # --------------------------------------------------------------
    def cmd_cr_ronaldo_siuuu(self):
        """cr: Cristiano Ronaldo 'SIUUUUU!' Jump, Spin & Wide-Arm Power Landing Celebration!"""
        self.set_tablet_command("soccer")
        self.set_eye_color(0xFDE047)
        names = [
            "HipPitch", "KneePitch", "HeadPitch", "HeadYaw",
            "LShoulderPitch", "RShoulderPitch",
            "LShoulderRoll",  "RShoulderRoll",
            "LElbowRoll",     "RElbowRoll",
            "LElbowYaw",      "RElbowYaw",
            "LHand",          "RHand"
        ]
        # 1. Run-up & cross arms high over chest ("Jump")
        cross_arms_pose = [
            -0.25,  0.12, -0.10, 0.0,
            -0.25, -0.25,
             0.05, -0.05,
            -1.48,  1.48,
            -0.40,  0.40,
             0.15,  0.15
        ]
        # 2. Iconic "SIUUUU!" landing: chest proud, head up, both arms thrown straight down & out wide to the sides!
        siuuu_land_pose = [
             0.08, -0.04, -0.25, 0.0,
             0.75,  0.75,
             0.58, -0.58,
            -0.08,  0.08,
            -1.40,  1.40,
             0.95,  0.95
        ]
        neutral_pose = [
            -0.03,  0.0,  -0.10, 0.0,
             1.45,  1.45,
             0.15, -0.15,
            -0.50,  0.50,
            -1.20,  1.20,
             0.50,  0.50
        ]
        try:
            self.motion.setStiffnesses(names, 1.0)
            # Step forward & cross arms across chest
            self.stage_move(0.22, 0.0, 0.35, async_move=True)
            self.motion.angleInterpolationWithSpeed(names, cross_arms_pose, 0.60)

            # Spin/land into wide SIUUUU power pose + roar "SIUUUUUU!"
            self.disco_leds(4.5)
            self.start_song("/tmp/kids_siuuu.wav")
            self.start_song(SFX_APPLAUSE_OGG)
            self.tts.post.say("\\rspd=80\\ \\vct=85\\ Siuuuuuuuuuu!")
            self.stage_move(0.0, 0.0, -0.35, async_move=True)
            self.motion.angleInterpolationWithSpeed(names, siuuu_land_pose, 0.75)
            time.sleep(1.8)

            # Return smoothly
            self.stage_move(-0.22, 0.0, 0.0, async_move=True)
            self.motion.angleInterpolationWithSpeed(names, neutral_pose, 0.40)
        except Exception:
            pass
        self.stop_all_songs()
        self.reset_leds()

    def cmd_lm_messi_pose(self):
        """lm: Lionel Messi Signature Goal Celebration — Both Hands Pointing Straight Up & Looking Up at the Sky!"""
        self.set_tablet_command("soccer")
        # Argentina Sky Blue eyes
        self.set_eye_color(0x38BDF8)
        names = [
            "HipPitch", "KneePitch", "HeadPitch", "HeadYaw",
            "LShoulderPitch", "RShoulderPitch",
            "LShoulderRoll",  "RShoulderRoll",
            "LElbowRoll",     "RElbowRoll",
            "LElbowYaw",      "RElbowYaw",
            "LWristYaw",      "RWristYaw",
            "LHand",          "RHand"
        ]
        # Both arms raised straight up to the sky (-1.48 rad) + head tilted up looking at the sky (-0.52 rad)!
        messi_sky_pose = [
             0.05,  0.0,  -0.52,  0.0,
            -1.48, -1.48,
             0.14, -0.14,
            -0.12,  0.12,
            -0.20,  0.20,
             0.0,   0.0,
             0.65,  0.65
        ]
        neutral_pose = [
            -0.03,  0.0,  -0.10,  0.0,
             1.45,  1.45,
             0.15, -0.15,
            -0.50,  0.50,
            -1.20,  1.20,
             0.0,   0.0,
             0.50,  0.50
        ]
        try:
            self.motion.setStiffnesses(names, 1.0)
            self.stage_move(0.20, 0.0, 0.0, async_move=True)
            self.start_song(SFX_APPLAUSE_OGG)
            self.start_song(SFX_MAGIC_OGG)
            # Raise both hands high up to the sky & look straight up!
            self.motion.angleInterpolationWithSpeed(names, messi_sky_pose, 0.45)
            # Gentle celebratory sway while holding both hands up and looking at the sky
            self.motion.angleInterpolationWithSpeed(["HeadYaw", "HipRoll"], [ 0.18,  0.10], 0.25)
            self.motion.angleInterpolationWithSpeed(["HeadYaw", "HipRoll"], [-0.18, -0.10], 0.25)
            self.motion.angleInterpolationWithSpeed(["HeadYaw", "HipRoll"], [ 0.0,   0.0 ], 0.25)
            time.sleep(1.2)
            self.stage_move(-0.20, 0.0, 0.0, async_move=True)
            self.motion.angleInterpolationWithSpeed(names, neutral_pose, 0.40)
        except Exception:
            pass
        self.stop_all_songs()
        self.reset_leds()

    def cmd_z_sneeze(self):
        """z: Funny Robot Sneeze ('Achoo!')."""
        self.set_tablet_command("surp")
        self.set_eye_color(0xFFFF00)
        self.run_anim("animations/Stand/Emotions/Neutral/Sneeze")
        self.reset_leds()

    def cmd_w_wakeup_stretch(self):
        """w: Wake Up, Big Yawn & Morning Stretch."""
        self.set_tablet_command(1)
        self.set_eye_color(0x38BDF8)
        self.run_anim("animations/Stand/Waiting/WakeUp_1")
        self.run_anim("animations/Stand/Waiting/Stretch_1")
        self.reset_leds()

    def cmd_f_fitness_workout(self):
        """f: Gym Fitness Workout & Super Muscles with energetic music."""
        self.set_tablet_command(7)
        self.disco_leds(7.0)
        self.start_song(SONG_HYPER_WAV)
        self.run_anim("animations/Stand/Waiting/Fitness_1")
        self.run_anim("animations/Stand/Waiting/Fitness_2")
        self.stop_all_songs()
        self.run_anim("animations/Stand/Waiting/ShowMuscles_1")
        self.reset_leds()

    def cmd_k_conductor_whistle(self):
        """k: Whistle & Orchestra Bandmaster Conductor."""
        self.set_tablet_command(2)
        self.disco_leds(6.0)
        self.run_anim("animations/Stand/Waiting/CallSomeone_1")
        self.run_anim("animations/Stand/Waiting/Bandmaster_1")
        self.reset_leds()

    def cmd_y_shy_robot(self):
        """y: Cute Shy / Bashful Robot."""
        self.set_tablet_command("shy")
        self.set_eye_color(0xFF66B2)
        self.run_anim("animations/Stand/Emotions/Positive/Shy_1")
        self.reset_leds()

    def cmd_u_surprised_robot(self):
        """u: Surprised / Shocked Robot Reaction."""
        self.set_tablet_command("surp")
        self.set_eye_color(0x00FFFF)
        self.run_anim("animations/Stand/Emotions/Negative/Surprise_1")
        self.run_anim("animations/Stand/Emotions/Negative/Fear_1")
        self.reset_leds()

    def cmd_h_hungry_robot(self):
        """h: Hungry Sniffing Robot + Drink Action."""
        self.set_tablet_command(9)
        self.set_eye_color(0xFFA500)
        self.run_anim("animations/Stand/Emotions/Positive/Hungry_1")
        self.run_anim("animations/Stand/Waiting/Drink_1")
        self.reset_leds()

    def cmd_v_victory_applause(self):
        """v: Victory Pose & Crowd Applause."""
        self.set_tablet_command("win")
        self.disco_leds(5.0)
        self.start_song(SFX_APPLAUSE_OGG)
        self.run_anim("animations/Stand/Emotions/Positive/Winner_1")
        self.run_anim("animations/Stand/Emotions/Positive/Winner_2")
        self.reset_leds()

    def cmd_d_robot_r2d2(self):
        """d: Mechanical R2-D2 Robot Walk & Pop Dance."""
        self.set_tablet_command(8)
        self.set_eye_color(0x00E5FF)
        self.run_anim("animations/Stand/Waiting/Robot_1")
        self.dance_robot_pop()
        self.reset_leds()

    def cmd_s_full_show(self):
        """s: Full Interactive Kids Show (Welcome + Magic Eyes + Disco Song Dance + Freeze Game + Photo)!"""
        self.cmd_1_welcome_peekaboo()
        time.sleep(0.5)
        self.cmd_8_magic_light_show()
        time.sleep(0.5)
        self.cmd_2_disco_dance()
        time.sleep(0.5)
        self.cmd_p_photo()

    def say_custom(self, text):
        self.set_tablet_command(0)
        self.disco_leds(2.5)
        self.say_animated("^start(animations/Stand/Gestures/Hey_1) " + text)
        self.reset_leds()

    # --------------------------------------------------------------
    # Physical Tactile Sensor Interactive Loop (Head & Hands Touch!)
    # --------------------------------------------------------------
    def start_touch_listener(self):
        """When kids touch Pepper's head or hands, Pepper reacts and dances!"""
        if not self.memory:
            return

        def _watch():
            sensors = [
                ("Device/SubDeviceList/Head/Touch/Front/Sensor/Value",  "head"),
                ("Device/SubDeviceList/Head/Touch/Middle/Sensor/Value", "head"),
                ("Device/SubDeviceList/Head/Touch/Rear/Sensor/Value",   "head"),
                ("Device/SubDeviceList/RHand/Touch/Back/Sensor/Value",  "rhand"),
                ("Device/SubDeviceList/LHand/Touch/Back/Sensor/Value",  "lhand")
            ]
            while True:
                time.sleep(0.25)
                if self.busy:
                    continue
                try:
                    for key, kind in sensors:
                        val = self.memory.getData(key)
                        if val and float(val) > 0.5:
                            self.busy = True
                            print("\n[Interactive Touch] Kid touched Pepper's {}!".format(kind))
                            self.disco_leds(3.0)
                            if kind == "head":
                                self.run_anim("animations/Stand/Emotions/Positive/Happy_4")
                            elif kind == "rhand":
                                self.start_song("/tmp/kids_party_song.wav")
                                self.dance_wave_boogie(cycles=1)
                                self.stop_all_songs()
                            else:
                                self.run_anim("animations/Stand/Emotions/Positive/Happy_4")
                            self.busy = False
                            time.sleep(0.8)
                            break
                except Exception:
                    self.busy = False

        t = threading.Thread(target=_watch)
        t.daemon = True
        t.start()

    # --------------------------------------------------------------
    # Tablet Touch Screen HTTP Server (Port 8765 on 198.18.0.1)
    # Allows students to touch buttons on Pepper's tablet directly!
    # --------------------------------------------------------------
    def start_tablet_http_server(self, port=8765):
        import BaseHTTPServer
        import urlparse
        entertainer = self

        class TouchHandler(BaseHTTPServer.BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                try:
                    parsed = urlparse.urlparse(self.path)
                    qs = urlparse.parse_qs(parsed.query)
                    cmd = qs.get("c", [""])[0].strip().lower()
                except Exception:
                    cmd = ""

                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write("OK")

                if cmd and not entertainer.busy:
                    def _run_touch():
                        print("\n[Tablet Touch] Student tapped '{}' on tablet screen!".format(cmd))
                        entertainer.run_command(cmd)
                    th = threading.Thread(target=_run_touch)
                    th.daemon = True
                    th.start()

        def _serve():
            try:
                httpd = BaseHTTPServer.HTTPServer(("0.0.0.0", port), TouchHandler)
                print("[Kids Fun] Tablet touch server active on port {}.".format(port))
                httpd.serve_forever()
            except Exception:
                pass

        st = threading.Thread(target=_serve)
        st.daemon = True
        st.start()

    def run_command(self, key):
        k = str(key).lower().strip()
        self.busy = True
        # Move the robot on stage during EVERY action (except home/init/main or p which has its own camera pose)
        do_auto_move = k not in ("0", "home", "p", "photo", "pic", "picture", "m", "main", "init", "check", "--check", "diag", "tl", "left", "tr", "right", "tc", "center", "front", "wf", "walk", "forward", "wb", "back", "backward", "ws", "glide", "side", "wr", "spin", "turn", "wp", "patrol", "roam")
        try:
            if do_auto_move:
                self.stage_pulse_move()
            if k in ("0", "home"):      self.cmd_0_home(force_open=False)
            elif k == "1":              self.cmd_1_welcome_peekaboo()
            elif k == "2":              self.cmd_2_disco_dance()
            elif k == "3":              self.cmd_3_air_guitar_rock()
            elif k == "4":              self.cmd_4_kungfu_knight()
            elif k == "5":              self.cmd_5_monster_elephant()
            elif k == "6":              self.cmd_6_helicopter_spaceship()
            elif k == "7":              self.cmd_7_penguin_workout_dance()
            elif k == "8":              self.cmd_8_magic_light_show()
            elif k in ("p", "photo", "pic", "picture"): self.cmd_p_photo()
            elif k in ("g", "freeze", "game"):          self.cmd_g_freeze_dance_game()
            elif k in ("l", "hug", "love"):             self.cmd_l_hug_and_song()
            elif k in ("b", "birthday", "bday"):        self.cmd_b_birthday_dance()
            elif k in ("c", "car", "drive"):            self.cmd_c_race_car()
            elif k in ("e", "elephant"):                self.cmd_e_elephant_dance()
            elif k in ("o", "gorilla"):                 self.cmd_o_gorilla()
            elif k in ("i", "mouse"):                   self.cmd_i_mouse()
            elif k in ("li", "lion", "tiger"):          self.cmd_li_lion()
            elif k in ("di", "dino", "dinosaur", "trex"): self.cmd_di_dinosaur()
            elif k in ("do", "dog", "puppy"):           self.cmd_do_dog()
            elif k in ("ca", "cat", "kitty"):           self.cmd_ca_cat()
            elif k in ("bi", "bird", "eagle"):          self.cmd_bi_bird()
            elif k in ("fr", "frog"):                   self.cmd_fr_frog()
            elif k in ("cw", "cow", "moo"):             self.cmd_cw_cow()
            elif k in ("sh", "sheep", "goat", "lamb"):  self.cmd_sh_sheep()
            elif k in ("ho", "horse"):                  self.cmd_ho_horse()
            elif k in ("du", "duck"):                   self.cmd_du_duck()
            elif k in ("ch", "chicken", "rooster", "hen"): self.cmd_ch_chicken()
            elif k in ("pg", "pig", "piggy"):           self.cmd_pg_pig()
            elif k in ("fa", "farm"):                   self.cmd_fa_farm_show()
            elif k in ("a", "animals", "safari"):       self.cmd_a_animal_safari()
            elif k in ("t", "taichi"):                  self.cmd_t_taichi_dance()
            elif k in ("x", "vacuum", "clean"):         self.cmd_x_vacuum_cleaner()
            elif k in ("n", "golf"):                    self.cmd_n_golf_swing()
            elif k in ("j", "mime", "wings"):           self.cmd_j_mime_and_bird()
            elif k in ("r", "shake"):                   self.cmd_r_shake_and_dazzle()
            elif k in ("z", "sneeze"):                  self.cmd_z_sneeze()
            elif k in ("w", "wakeup", "stretch"):       self.cmd_w_wakeup_stretch()
            elif k in ("f", "fitness", "workout"):      self.cmd_f_fitness_workout()
            elif k in ("k", "conductor", "whistle"):    self.cmd_k_conductor_whistle()
            elif k in ("y", "shy"):                     self.cmd_y_shy_robot()
            elif k in ("u", "surprise", "shock"):       self.cmd_u_surprised_robot()
            elif k in ("h", "hungry", "drink"):         self.cmd_h_hungry_robot()
            elif k in ("v", "victory", "win"):          self.cmd_v_victory_applause()
            elif k in ("d", "r2d2", "robot"):           self.cmd_d_robot_r2d2()
            elif k in ("wf", "walk", "forward"):        self.cmd_wf_walk_forward_back()
            elif k in ("wb", "back", "backward"):       self.cmd_wb_walk_back()
            elif k in ("tl", "left"):                   self.cmd_tl_turn_left()
            elif k in ("tr", "right"):                  self.cmd_tr_turn_right()
            elif k in ("tc", "center", "front"):        self.cmd_tc_turn_center()
            elif k in ("ws", "glide", "side"):          self.cmd_ws_walk_side_dance()
            elif k in ("wr", "spin", "turn"):           self.cmd_wr_spin_360()
            elif k in ("wp", "patrol", "roam"):         self.cmd_wp_stage_patrol()
            elif k in ("hs", "shake", "handshake"):     self.cmd_hs_handshake()
            elif k in ("hf", "highfive"):               self.cmd_hf_highfive()
            elif k in ("fb", "fistbump", "bump"):       self.cmd_fb_fistbump()
            elif k in ("rps", "rock"):                  self.cmd_rps_rock_paper_scissors()
            elif k in ("hsk", "shoulders"):             self.cmd_hsk_head_shoulders_knees()
            elif k in ("cr", "siu", "siuuu", "ronaldo"): self.cmd_cr_ronaldo_siuuu()
            elif k in ("lm", "messi"):                  self.cmd_lm_messi_pose()
            elif k in ("s", "show"):                    self.cmd_s_full_show()
            elif k in ("m", "main"):                    self.restore_main_tablet()
            elif k in ("init", "check", "--check"):
                self.cmd_0_home(force_open=True)
                self.disco_leds(1.2)
                # Ensure background tablet-touch daemon is running on port 8765
                try:
                    import socket
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(0.3)
                    in_use = (s.connect_ex(("127.0.0.1", 8765)) == 0)
                    s.close()
                    if not in_use:
                        os.system("setsid python2.7 /home/nao/Laurimate/kids_fun.py --daemon </dev/null >/dev/null 2>&1 &")
                        time.sleep(1.2)
                except Exception:
                    pass
                print("PEPPER_KIDS_FUN_READY (Camera={})".format(self.photo is not None))
            elif k == "diag":
                try:
                    self.motion.setExternalCollisionProtectionEnabled("Move", False)
                except Exception as e:
                    print("Disable Move collision note:", e)
                try:
                    print("Hatch sensor:", self.memory.getData("Device/SubDeviceList/Platform/ILS/Sensor/Value"))
                except Exception as e:
                    print("Hatch err:", e)
                try:
                    p0 = self.motion.getRobotPosition(False)
                    res = self.motion.moveTo(0.12, 0.0, 0.0)
                    if res:
                        self.motion.moveTo(-0.12, 0.0, 0.0)
                    p1 = self.motion.getRobotPosition(False)
                    print("moveTo result:", res, "pos0:", p0, "pos1:", p1)
                except Exception as e:
                    print("moveTo err:", e)
            else:
                return False
            return True
        finally:
            if do_auto_move:
                self.stage_return_move()
            self.busy = False


def print_menu():
    print("\n======================================================================================")
    print("             LAURIMATE LIVE KIDS CONTROLLER (ALL CONTROLS — BEST ON TOP)              ")
    print("======================================================================================")
    print("  *** #1 FEATURED SHOWSTOPPER: KIDS PHOTO BOOTH (WITH RETAKE ON TABLET) ***")
    print("  >>> [p]  TAKE KIDS PICTURE & SHOW ON TABLET (WITH RETAKE PHOTO BUTTON!) <<<")
    print("--------------------------------------------------------------------------------------")
    print("  *** TOP SHOWSTOPPERS & KIDS FAVORITES ***")
    print("  [cr] Ronaldo 'SIUUUUU!' Celebration   | [lm] Lionel Messi Two Hands Up & Look Sky")
    print("  [2]  Energetic Disco Dance Party      | [g]  Musical Freeze Dance Game!")
    print("  [hs] Robot Handshake with a Kid       | [hf] Interactive High-Five (+ Ding FX)")
    print("  [wf] Walk Forward (+24cm), Wave & Hi  | [l]  Big Robot Hug & Flying Hearts")
    print("  [hsk] Head, Shoulders, Knees & Clap   | [wr] 360-Degree Disco Spin in Place")
    print("  [3]  Electric Air Guitar Rock Song    | [d]  Classic R2-D2 Robot Walk & Pop Dance")
    print("  [7]  Penguin Waddle & Workout Dance   | [8]  Magic Rainbow Eyes & R2-D2 Sounds")
    print("  [6]  Helicopter & Space Rocket Launch | [b]  Happy Birthday Song & Dance")
    print("  [c]  Race Car Driver (Engine & Crash) | [di] Giant T-Rex Dinosaur (Stomp/Roar)")
    print("  [fa] OLD MACDONALD FARM ANIMALS SHOW! | [a]  MEGA WILD ZOO SAFARI ANIMALS SHOW!")
    print("  [1]  Welcome Wave & Peek-a-Boo        | [s]  RUN FULL AUTO MINI-SHOW!")
    print("--------------------------------------------------------------------------------------")
    print("  *** TURN LEFT/RIGHT & STAGE WALKING ***")
    print("  [tl] Turn LEFT (~45 deg)              | [tr] Turn RIGHT (~45 deg)")
    print("  [tc] Face Straight CENTER / Front     | [wb] Step/Roll Backward (-24cm)")
    print("  [ws] Side-to-Side Stage Glide Dance   | [wp] Mini Stage Patrol & Wave Loop")
    print("--------------------------------------------------------------------------------------")
    print("  *** DOMESTIC, FARM & WILD ANIMALS (WITH SOUNDS & MOVES) ***")
    print("  [cw] Dairy Cow ('Moooooo!' + Horns)   | [do] Puppy Dog ('Woof! Woof!' + Tail Wag)")
    print("  [ca] Kitty Cat ('Meow!' + Paw Wash)   | [sh] Fluffy Sheep ('Baaaaa!' + Hop)")
    print("  [ho] Galloping Horse (Neigh + Hooves) | [du] Farm Duck ('Quack, quack!' + Waddle)")
    print("  [ch] Chicken/Rooster (Cluck + Wings)  | [pg] Farm Piggy ('Oink! Oink!' + Wiggle)")
    print("  [e]  Giant Elephant (Trunk + Trumpet) | [o]  Chest-Beating Gorilla (+ Roar/Thump)")
    print("  [i]  Tiny Nibbling Mouse (+ Squeaks)  | [li] King Lion / Tiger (Roar + Claw Pounce)")
    print("  [bi] Soaring Eagle Bird (Chirps+Wings)| [fr] Jumping Green Frog ('Ribbit!')")
    print("  [5]  Friendly Monster & Zombie Walk   | [t]  Traditional Tai Chi Dance + Song")
    print("--------------------------------------------------------------------------------------")
    print("  *** MORE COMEDY, SPORTS & ROBOT ACTIONS ***")
    print("  [fb] Fist Bump + Fireworks Boom!      | [4]  Kung Fu Master & Sword Knight Dance")
    print("  [x]  Vacuum Cleaner Robot (+ Sound)   | [n]  Pro Golf Swing & Hole-in-One")
    print("  [j]  Invisible Wall Mime & Bird Wings | [r]  Wet Puppy Body Shake & Dazzle")
    print("  [f]  Gym Fitness Workout & Muscles    | [k]  Whistle & Orchestra Conductor")
    print("  [z]  Funny Robot Sneeze ('Achoo!')    | [w]  Wake Up, Big Yawn & Stretch")
    print("  [y]  Cute Shy / Bashful Robot         | [u]  Surprised / Shocked Robot")
    print("  [h]  Hungry Sniffing & Drink Soda     | [v]  Victory Trophy & Crowd Applause")
    print("  [0]  Kids Visual Home Screen          | [m]  Restore Main Campus Tablet UI")
    print("  [q]  Quit (or type ANY text to speak live!)")
    print("======================================================================================")


def _run_via_ssh_from_pc():
    import paramiko
    print("[Kids Fun] Connecting to Pepper ({})...".format(REMOTE_SSH_IP))
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(REMOTE_SSH_IP, username=REMOTE_USER, password=REMOTE_PASS, timeout=10)
    print("[Kids Fun] Connected!")

    def remote_trigger(arg_str):
        cmd = "python2.7 /home/nao/Laurimate/kids_fun.py {}".format(arg_str)
        stdin, stdout, stderr = ssh.exec_command(cmd)
        out = stdout.read().decode("utf-8", "ignore").strip()
        err = stderr.read().decode("utf-8", "ignore").strip()
        if out:
            print(out)
        if err:
            for line in err.splitlines():
                if "qimessaging" not in line and "sdklayout" not in line:
                    print(line)

    if len(sys.argv) > 1:
        args = " ".join(['"{}"'.format(a.replace('"', '\\"')) for a in sys.argv[1:]])
        remote_trigger(args)
        ssh.close()
        return

    remote_trigger("init")

    valid_cmds = (
        "0", "1", "2", "3", "4", "5", "6", "7", "8",
        "p", "photo", "pic", "picture", "g", "freeze", "game",
        "l", "hug", "love", "b", "birthday", "bday",
        "c", "car", "drive", "e", "elephant", "o", "gorilla",
        "i", "mouse", "li", "lion", "tiger", "di", "dino", "dinosaur", "trex",
        "do", "dog", "puppy", "ca", "cat", "kitty", "bi", "bird", "eagle",
        "fr", "frog", "cw", "cow", "moo", "sh", "sheep", "goat", "lamb",
        "ho", "horse", "du", "duck", "ch", "chicken", "rooster", "hen",
        "pg", "pig", "piggy", "fa", "farm",
        "a", "animals", "safari", "t", "taichi",
        "x", "vacuum", "clean", "n", "golf", "j", "mime", "bird", "wings",
        "r", "shake", "z", "sneeze",
        "w", "wakeup", "stretch", "f", "fitness", "workout",
        "k", "conductor", "whistle", "y", "shy",
        "u", "surprise", "shock", "h", "hungry", "drink",
        "v", "victory", "win", "d", "r2d2", "robot",
        "tl", "left", "tr", "right", "tc", "center", "front",
        "wf", "walk", "forward", "wb", "back", "backward",
        "ws", "glide", "side",
        "wr", "spin", "turn", "wp", "patrol", "roam",
        "hs", "shake", "handshake", "hf", "highfive",
        "fb", "fistbump", "bump", "rps", "rock", "hsk", "shoulders",
        "cr", "siu", "siuuu", "ronaldo", "lm", "messi",
        "s", "show", "m", "main", "home"
    )
    try:
        while True:
            print_menu()
            try:
                choice = raw_input("CMD [cr/lm/p/2/hs/hf/fb/rps/fa/a/cw/do/ca/tl/tr/wf or text] > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting.")
                break
            c = choice.lower()
            if c == "q":
                print("Goodbye!")
                break
            elif c in valid_cmds:
                remote_trigger(c)
            elif choice:
                remote_trigger('say "{}"'.format(choice.replace('"', '\\"')))
    finally:
        ssh.close()


def main():
    if not HAS_NAOQI:
        _run_via_ssh_from_pc()
        return

    ent = KidsEntertainer()

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "--daemon":
            ent.start_tablet_http_server(8765)
            ent.start_touch_listener()
            while True:
                time.sleep(10.0)
            return
        if cmd == "say" and len(sys.argv) > 2:
            ent.say_custom(" ".join(sys.argv[2:]))
        elif not ent.run_command(cmd):
            ent.say_custom(" ".join(sys.argv[1:]))
        return

    ent.run_command("init")
    ent.start_tablet_http_server(8765)
    ent.start_touch_listener()

    while True:
        print_menu()
        try:
            choice = raw_input("CMD [cr/lm/p/2/hs/hf/fb/rps/fa/a/cw/do/ca/tl/tr/wf or text] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break
        c = choice.lower()
        if c == "q":
            print("Goodbye!")
            break
        elif not ent.run_command(c):
            if choice:
                ent.say_custom(choice)


if __name__ == "__main__":
    main()
