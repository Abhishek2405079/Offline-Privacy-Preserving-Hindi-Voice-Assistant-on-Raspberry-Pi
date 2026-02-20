# Offline Privacy-Preserving Hindi Voice Assistant — Raspberry Pi 4

This repository contains my submission for the Bharat AI-SoC Student Challenge 2026 — a fully offline Hindi voice assistant built on a Raspberry Pi 4. It listens to spoken Hindi commands via Bluetooth earbuds, processes them locally using a small LLM, and speaks responses through a Bluetooth speaker, with no internet connection required.

## 🔧 Hardware

| Component | Device |
|-----------|--------|
| Main Board | Raspberry Pi 4 Model B (4GB RAM) |
| Storage | 64GB USB 3.0 Pendrive |
| Mic Input | realme Buds T310 (Bluetooth, HFP profile) |
| Audio Output | NuR SONICPOP50 (Bluetooth, A2DP profile) |

## 🧠 Software & AI Stack

| Layer | Tool |
|-------|------|
| OS | Raspberry Pi OS Lite (Headless, 64-bit) |
| Language | Python 3.13 |
| Speech-to-Text | Vosk (`vosk-model-small-hi-0.22`) |
| Language Model | Ollama (`llama3.2:latest` — custom Modelfile, renamed `hindi-smart:latest`) |
| Text-to-Speech | eSpeak-NG (Hindi voice) |
| Audio Manager | PulseAudio 17.0 |

## 🏗️ Architecture
```
Microphone (HFP) → Vosk STT → Ollama LLM (streamed) → eSpeak TTS → Speaker (A2DP)
```

The assistant runs entirely on the Raspberry Pi 4 using a streaming pipeline designed to minimize perceived latency. Instead of waiting for the full LLM response, `ollama.generate()` is called with `stream=True`. Each token is immediately fed to a background TTS worker thread via a queue. The worker buffers tokens until 2-3 words are ready, then passes them to eSpeak-NG — so audio playback overlaps with LLM generation. While the speaker is saying the first chunk, the LLM is already generating the next one.

### 📁 File Structure
```
/home/abhishek/
├── asr/                          # Main project directory
│   ├── start.py                  # Main voice assistant script
│   └── model/                    # Vosk Hindi STT model
│       └── vosk-model-small-hi-0.22/
├── voice_env/                    # Python virtual environment
│   └── bin/
│       └── python3               # Python 3.13 interpreter

/usr/bin/
└── espeak-ng                     # eSpeak-NG TTS (system package, apt installed)

/usr/share/espeak-ng-data/
└── hi/                           # Hindi voice data files for eSpeak-NG

~/.ollama/models/
└── hindi-smart/                  # Custom Ollama model (llama3.2 + Hindi Modelfile)
```

### 🔄 How It Works Step by Step

1. `sounddevice` captures live audio from the earbuds mic (HFP, 16kHz mono) in chunks of 4000 frames
2. Each chunk is passed to `vosk.KaldiRecognizer` which detects when a full Hindi sentence has been spoken
3. The recognized text is sent to `ollama.generate()` running `hindi-smart:latest` locally on the RPi CPU
4. Tokens stream back one by one and are queued into the `StreamingTTS` worker thread
5. The worker speaks every 2-3 words via `espeak-ng -v hi` through PulseAudio to the Bluetooth speaker (A2DP)

---

## 🧪 Methodology

### Tool Selection Rationale

Every component in this stack was chosen under two hard constraints: it had to run **fully offline** and fit within the **4GB RAM** of the Raspberry Pi 4.

**Vosk (STT):** The project guidelines offered 2-3 STT options. Vosk was selected as the best tradeoff between Hindi recognition accuracy and latency on edge hardware. It runs inference in ~0.01s and loads a compact model (`vosk-model-small-hi-0.22`) that occupies minimal RAM, making it ideal for a resource-constrained environment.

**llama3.2 (LLM):** With ~200–300MB consumed by the headless OS and additional memory reserved for the STT model, TTS engine, and LLM context window, the usable RAM for the language model was approximately 2.5–3GB. `llama3.2:latest` has a quantized footprint of ~2GB, fitting cleanly within this budget while delivering strong Hindi language comprehension. A larger model would have caused out-of-memory failures or excessive swap usage, making llama3.2 the only practical choice at this memory tier.

**eSpeak-NG (TTS):** Among the available TTS options in the project guidelines, eSpeak-NG offered the best latency per chunk (~0.2s) with native Hindi (`-v hi`) support. Neural TTS alternatives produce more natural speech but require significantly more compute and memory — not viable on a CPU-only RPi 4.

**Streaming Pipeline Design:** Rather than a sequential STT → LLM → TTS pipeline (which would add all three latencies before the user hears anything), a producer-consumer architecture was implemented. The LLM streams tokens into a queue consumed by a background TTS thread, so speech begins within ~3–4 seconds of the user finishing their query regardless of total response length.

---

## 🖥️ Hardware Utilization

### Raspberry Pi 4 — Resource Budget

The RPi 4 (4GB RAM variant) was chosen specifically because the 2GB variant cannot fit a capable LLM alongside the OS and supporting processes. The 8GB variant would work but adds unnecessary cost for this use case.

| Resource | Estimated Usage |
|----------|----------------|
| OS (Headless Lite) | ~200–300 MB RAM |
| Vosk STT model | ~50–80 MB RAM |
| eSpeak-NG TTS | ~10–20 MB RAM |
| llama3.2 model (quantized) | ~2000 MB RAM |
| Python runtime + context window | ~200–400 MB RAM |
| **Total (approximate)** | **~2.5–3.0 GB RAM** |

The RPi 4's quad-core ARM Cortex-A72 handles all inference on CPU — there is no GPU. The LLM is the dominant compute load, running entirely on the ARM cores during token generation.

### USB 3.0 Boot vs SD Card

The OS is booted from a **64GB USB 3.0 pendrive** plugged into one of the RPi 4's blue USB 3.0 ports rather than a microSD card. USB 3.0 offers significantly higher sequential read/write throughput compared to typical microSD cards, which meaningfully reduces model load times when Ollama reads the llama3.2 weights from disk at startup.

### Bluetooth Profile Constraints (HFP vs A2DP)

Bluetooth audio operates on two fundamentally different profiles with an inherent tradeoff:

| Profile | Quality | Supports Mic | Used For |
|---------|---------|--------------|----------|
| A2DP | High (stereo) | ❌ No | Speaker output |
| HFP (Hands-Free) | Low (mono, 8–16kHz) | ✅ Yes | Earbuds mic input |

A Bluetooth device cannot simultaneously operate in A2DP and HFP on the same endpoint. This is why the earbuds are explicitly switched to `handsfree_head_unit` profile via `pactl` — it sacrifices audio quality on the earbuds to unlock the microphone. The speaker remains on A2DP for high-quality audio output. This profile must be re-applied every time the earbuds reconnect.

---

## ⚡ Optimization Techniques

Several targeted optimizations were applied to make the system responsive within the RPi 4's hardware constraints:

**1. Quantized Small LLM:** `llama3.2:latest` uses quantized (Q4) weights, reducing the model size to ~2GB while preserving strong language understanding. This was a deliberate memory-aware decision — the full-precision model would exceed available RAM.

**2. Streaming TTS Overlap:** Instead of waiting for the complete LLM response, tokens are streamed directly into a background TTS worker thread. The worker buffers 2-3 words and begins speaking immediately, so audio output overlaps with ongoing LLM inference. This reduces time-to-first-speech from ~15–20s (full response wait) to ~3–4s.

**3. Tuned Audio Chunk Size:** The `sounddevice` input chunk size is set to 4000 frames at 16kHz (0.25s per chunk). This is deliberately sized to give Vosk enough audio context for accurate Hindi recognition while keeping input latency low.

**4. USB 3.0 Boot:** Booting from a USB 3.0 pendrive instead of a microSD card reduces model loading time at startup due to higher read throughput, particularly noticeable when Ollama loads the 2GB LLM weights into memory.

**5. PulseAudio Explicit Routing:** Default PulseAudio sink/source assignments are set explicitly via `pactl` commands after every Bluetooth reconnect. This prevents audio from accidentally routing to the wrong device (e.g., HDMI or the earbuds in A2DP mode) and ensures the HFP mic is always the active input source.

---

## 📊 Performance

| Stage | Latency |
|-------|---------|
| STT (Vosk) | ~0.01s |
| LLM first token | ~2.5–3s |
| LLM full response | ~15–20s |
| TTS per chunk (eSpeak) | ~0.2s |
| **Time to first spoken words** | **~3–4s** |

> ⚠️ The LLM is the main bottleneck — it runs entirely on the RPi 4 ARM CPU with no GPU acceleration. Total response time depends on response length.

---

## 💾 OS Installation & Setup

### Step 1: Download Raspberry Pi Imager
Download and install the official Raspberry Pi Imager from `raspberrypi.com/software`.

### Step 2: Choose Device & OS
1. Open Raspberry Pi Imager → select **Raspberry Pi 4**
2. Click **Raspberry Pi OS (other)** → **Raspberry Pi OS Lite (64-bit)**
   > A minimal Debian-based OS with no desktop environment — ideal for headless use

### Step 3: Select Storage
1. Plug in your **64GB USB 3.0 pendrive**
2. Select your USB drive
   > ⚠️ Double check the drive — this will erase everything on it

### Step 4: Configure Headless Settings
Click **EDIT SETTINGS** before writing and configure:

**General Tab:**
- Enter Hostname
  Example: `abcd`
- Enter Username
  Example: `efgh`
- Enter Password
  Example: `qwertyuiop`
- Configure Wireless LAN: enter your Wi-Fi SSID and password
- Set your timezone and keyboard layout

**Services Tab:**
- Enable SSH: `ON`
- Authentication: `Password`

### Step 5: Flash & Boot
1. Click **NEXT** → **WRITE** → confirm the warning
2. Wait for writing and verification to complete
3. Safely eject the USB drive
4. Plug it into one of the **blue USB 3.0 ports** on the Raspberry Pi 4 and power on

## 🔌 Connecting via SSH

### Option 1: Wi-Fi Hotspot
1. Turn on the same Wi-Fi hotspot you entered during OS installation
2. Connect your laptop to that same hotspot
3. Wait — you should see a second device connect to the hotspot with the hostname you set
4. Open your hotspot's **Managed Devices** on your phone to find the RPi's IP address
5. Open terminal and run:
```bash
ssh username@<ip-address>
# Example:
ssh efgh@192.168.43.105
```
6. Type `yes` when prompted, then enter your password

### Option 2: Ethernet Cable
1. Connect your laptop directly to the RPi 4 via ethernet cable
2. Find connected devices on your laptop:
```bash
# On Linux/Mac:
arp -a

# On Windows (PowerShell):
arp -a
```
3. Find the RPi's MAC address from the list, then connect:
```bash
ssh username@<mac-address>
# Example:
ssh efgh@b8:27:eb:xx:xx:xx
```
4. Enter your password when prompted
   ```bash
   # Example
   qwertyuiop
   ```

---

## 🤖 Installing Ollama & Setting Up the LLM

### 1. Install Ollama
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. Pull the base model
```bash
ollama pull llama3.2:latest
```
> This may take a while depending on your internet speed (~2GB download)

### 3. Create the custom Hindi model
The Modelfile is included in this repository. Use it directly:
```bash
ollama create hindi-smart -f Modelfile
```

### 4. Verify it works
```bash
ollama run hindi-smart
# Type a Hindi question to test, then Ctrl+D to exit
```

## 🎤 Installing Vosk Hindi STT

### 1. Install Python environment and Vosk
```bash
sudo apt install python3-venv python3-pip -y
python3 -m venv ~/voice_env
source ~/voice_env/bin/activate
pip install vosk sounddevice ollama
```

### 2. Download and set up Vosk Hindi model
```bash
cd ~/asr
wget https://alphacephei.com/vosk/models/vosk-model-small-hi-0.22.zip
unzip vosk-model-small-hi-0.22.zip
mv vosk-model-small-hi-0.22 model
rm vosk-model-small-hi-0.22.zip
```

---

## 🔊 Installing eSpeak-NG
```bash
sudo apt install espeak-ng -y

# Test it works
espeak-ng -v hi "नमस्ते"
```

---

## 📡 Connecting Bluetooth Devices

### 1. Enable and start Bluetooth
```bash
sudo systemctl enable bluetooth
sudo systemctl start bluetooth
```

### 2. Pair both devices
```bash
bluetoothctl
```
Inside bluetoothctl:
```bash
power on
agent on
scan on
# Wait until you see your devices appear, then:
pair 58:91:7F:3E:2F:C9        # NuR SONICPOP50 (Speaker)
pair 98:47:44:B2:4A:07        # realme Buds T310 (Earbuds)
trust 58:91:7F:3E:2F:C9
trust 98:47:44:B2:4A:07
connect 58:91:7F:3E:2F:C9
connect 98:47:44:B2:4A:07
scan off
exit
```

---

## 🎛️ Setting Audio Input & Output Profiles

By default earbuds connect in A2DP mode which has no microphone. Switch to HFP to enable the mic:

### 1. Switch earbuds to HFP (enables microphone)
```bash
pactl set-card-profile bluez_card.98_47_44_B2_4A_07 handsfree_head_unit
```

### 2. Set speaker as default output (A2DP — high quality)
```bash
pactl set-default-sink bluez_sink.58_91_7F_3E_2F_C9.a2dp_sink
```

### 3. Set earbuds as default mic input
```bash
pactl set-default-source bluez_source.98_47_44_B2_4A_07.handsfree_head_unit
```

### 4. Verify correct routing
```bash
pactl info | grep -E "Default Sink|Default Source"
```

### 5. Find correct input device number for Python
```bash
python3 -c "import sounddevice as sd; print(sd.query_devices())"
# Note the number next to pulse or bluez_source — update device= in start.py if needed
```

## 📄 Setting Up start.py

The main script is included in this repository as `start.py`. Copy it into your asr folder:
```bash
cp start.py ~/asr/start.py
```

Before running, open the file and update these values to match your setup:
```bash
nano ~/asr/start.py
```

Change the following:
- **Wi-Fi SSID & password** — match what you entered during OS installation
- **Bluetooth MAC addresses** — replace with your speaker and earbuds MAC addresses (find them with `bluetoothctl devices`)
- **IP address** — your RPi's IP on your network (find with `hostname -I`)
- **Hostname** — replace `abhishek` with whatever hostname you set

### Run the assistant
```bash
source ~/voice_env/bin/activate
cd ~/asr
python3 start.py
```

You should hear **"सिस्टम तैयार है"** — the assistant is ready to take Hindi commands.

> ⚠️ These audio profile commands must be re-run every time the earbuds reconnect. Device numbers can also change after profile switching — always verify with the last command above.
