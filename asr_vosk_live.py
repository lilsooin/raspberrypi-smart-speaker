# asr_vosk_live.py
import json, queue, sys
import sounddevice as sd
from vosk import Model, KaldiRecognizer
from voice_router import on_asr_final

MODEL_PATH = "models/vosk-model-small-en-us-0.15"
SAMPLE_RATE = 16000
BLOCKSIZE = 8000  # 0.5s

def main():
    model = Model(MODEL_PATH)
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    rec.SetWords(True)

    q = queue.Queue()

    def audio_cb(indata, frames, time, status):
        if status:
            print(status, file=sys.stderr)
        q.put(bytes(indata))

    with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BLOCKSIZE,
                           dtype="int16", channels=1, callback=audio_cb):
        print("[Vosk] Listening... (Ctrl+C to stop)")
        partial_last = ""
        try:
            while True:
                data = q.get()
                if rec.AcceptWaveform(data):
                    # 문장 하나가 완성됐을 때
                    result = json.loads(rec.Result())
                    text = result.get("text", "").strip()
                    if text:
                        print(">>", text)
                        on_asr_final(text, confidence=None)
                else:
                    # 필요시 partial로 화면 디버그
                    part = json.loads(rec.PartialResult()).get("partial","")
                    if part and part != partial_last:
                        partial_last = part
        except KeyboardInterrupt:
            print("\n[Vosk] Stopped.")

if __name__ == "__main__":
    main()