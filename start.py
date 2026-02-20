import queue
import sounddevice as sd
import vosk
import ollama
import subprocess
import threading
import json
import sys
import time
import os

# ─── Settings ───────────────────────────────────────────
MODEL_NAME = "hindi-smart:latest"
VOSK_MODEL_PATH = "model"
SAMPLE_RATE = 16000
SPEAK_AFTER_WORDS = 3
MIN_WORDS = 2  # ignore inputs with less than this many words
# ────────────────────────────────────────────────────────

# Suppress Vosk logs
os.environ["VOSK_LOG_LEVEL"] = "-1"

audio_queue = queue.Queue()
is_speaking = False

def audio_callback(indata, frames, time_info, status):
    if is_speaking:
        return
    if status:
        print(status, file=sys.stderr)
    audio_queue.put(bytes(indata))

# ─── Now Speak beep ─────────────────────────────────────
def play_beep():
    global is_speaking
    is_speaking = True  # block mic during beep
    subprocess.run(["espeak-ng", "-v", "hi", "-s", "150", "बोलिए"])
    time.sleep(0.3)     # small buffer after beep
    is_speaking = False # only unblock AFTER beep finishes

# ─── Streaming TTS ──────────────────────────────────────
class StreamingTTS:
    def __init__(self):
        self.token_queue = queue.Queue()
        self.buffer = ""
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()
        print("✅ TTS ready")

    def _worker(self):
        global is_speaking
        while True:
            token = self.token_queue.get()
            if token is None:
                break
            self.buffer += token
            words = self.buffer.split()
            if (len(words) >= SPEAK_AFTER_WORDS or
                any(self.buffer.endswith(p) for p in ["।", ".", "?", "!", ",", "\n"])):
                text = self.buffer.strip()
                if text:
                    try:
                        is_speaking = True
                        subprocess.run(
                            ["espeak-ng", "-v", "hi", "-s", "150", text],
                            timeout=10
                        )
                    except Exception as e:
                        print(f"TTS error: {e}")
                self.buffer = ""

    def speak_token(self, token):
        self.token_queue.put(token)

    def flush(self):
        global is_speaking
        if self.buffer.strip():
            try:
                is_speaking = True
                subprocess.run(
                    ["espeak-ng", "-v", "hi", "-s", "150", self.buffer.strip()],
                    timeout=10
                )
            except Exception as e:
                print(f"TTS flush error: {e}")
            self.buffer = ""
        # flush stale audio captured while speaking
        while not audio_queue.empty():
            try:
                audio_queue.get_nowait()
            except:
                break
        play_beep()  # handles is_speaking = False after beep

    def close(self):
        self.token_queue.put(None)

# ─── LLM Streaming Response ─────────────────────────────
def get_response_streaming(query, tts):
    global is_speaking
    first_token = True
    t0 = time.time()
    print("AI: ", end='', flush=True)

    try:
        stream = ollama.generate(model=MODEL_NAME, prompt=query, stream=True)
        for chunk in stream:
            token = chunk['response']
            if first_token:
                print(f"\n⏱ First token: {time.time()-t0:.2f}s")
                first_token = False
            print(token, end='', flush=True)
            tts.speak_token(token)

        tts.flush()
        print(f"\n⏱ Total LLM: {time.time()-t0:.2f}s\n")

    except Exception as e:
        print(f"\nLLM error: {e}")
        is_speaking = False

# ─── Main ────────────────────────────────────────────────
def main():
    # Load Vosk STT silently
    try:
        stt_model = vosk.Model(VOSK_MODEL_PATH)
        rec = vosk.KaldiRecognizer(stt_model, SAMPLE_RATE)
        print("✅ STT ready")
    except Exception as e:
        print(f"STT Error: {e}")
        sys.exit(1)

    # Init TTS
    tts = StreamingTTS()

    # Startup sound
    subprocess.run(["espeak-ng", "-v", "hi", "-s", "150", "सिस्टम तैयार है"])
    play_beep()  # first "बोलिए" at startup

    print("--- System Live ---\n")

    try:
        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=4000,
            dtype='int16',
            channels=1,
            device=5,
            callback=audio_callback
        ):
            while True:
                data = audio_queue.get()
                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    query = result.get("text", "").strip()
                    if query:
                        word_count = len(query.split())
                        if word_count < MIN_WORDS:
                            print(f"(ignored: '{query}')")
                            continue
                        print(f"\nYou: {query}")
                        get_response_streaming(query, tts)

    except KeyboardInterrupt:
        print("\n--- Shutting down ---")
        tts.close()
        sys.exit(0)

if __name__ == "__main__":
    main()
