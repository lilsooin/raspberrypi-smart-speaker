# asr_vosk_live.py
import json, queue, sys, time
import sounddevice as sd
from vosk import Model, KaldiRecognizer

# 라우터: on_asr_final + recognizer reset 콜백 연결
from voice_router import on_asr_final, set_recognizer_reset

MODEL_PATH = "models/vosk-model-en-us-0.22-lgraph"
SAMPLE_RATE = 16000
BLOCKSIZE = 4096  # ~0.256s @16k mono. 필요 시 3072/2048로 더 줄여도 OK.

# NOTE:
# - 가능하면 전부 소문자. (대문자 토큰은 vocab 경고가 뜨기 쉬움)
# - 'what's the weather like in', 'how is the weather in' 사이에 반드시 콤마!
PHRASES = [
    # Wake words (boost)
    "hey there", "hello there", "the hey there", "the hello there",

    # Sentence patterns (questions)
    "what is the weather in", "what's the weather in", "what's the weather like in", "how is the weather in",

    # Date tokens (query helpers)
    "what is the temperature in", "temperature in", "weather in",
    "weather now in", "temperature now in", "now in", "right now in",
    "now", "today", "tomorrow", "day after tomorrow",

    # Weekdays
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",

    # City names (formal + common typos/variants)
    "miyazaki", "miyasaki", "miya zaki",
    "toronto", "tokyo", "busan", "pusan", "seoul", "seol", "soul", "new york",

    # Currency intent words / connectors
    "currency", "exchange", "rate", "rates", "fx",
    "to", "from", "in", "into",

    # Currency / country names (소문자)
    # 한국 원 / 대한민국
    "kor", "krw", "won", "korean", "korea", "seoul", "busan", "pusan",
    # 일본 엔 / 일본
    "jp", "jpy", "yen", "japanese", "japan", "tokyo", "osaka",
    # 미국 달러 / 미국
    "usd", "dollar", "us", "u s", "america", "american",
    # 캐나다 달러 / 캐나다
    "cad", "canadian", "canada",
]

def _is_wake_like(text: str) -> bool:
    t = text.strip().lower()
    return t in ("hey there", "hello there")

def main():
    model = Model(MODEL_PATH)
    rec = KaldiRecognizer(model, SAMPLE_RATE, json.dumps(PHRASES))
    rec.SetWords(True)

    # 라우터가 TTS 직후 인식기 버퍼를 리셋할 수 있도록 콜백 연결
    def reset_recognizer():
        try:
            rec.Reset()
        except Exception:
            pass
    set_recognizer_reset(reset_recognizer)

    # Limit the number of audio chunks queued to prevent overflow
    q = queue.Queue(maxsize=8)

    def audio_cb(indata, frames, time_info, status):
        if status:
            print(status, file=sys.stderr)
        try:
            q.put_nowait(bytes(indata))
        except queue.Full:
            # If the queue is full, discard the oldest chunk to avoid delay
            _ = q.get_nowait()
            q.put_nowait(bytes(indata))

    with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BLOCKSIZE,
                           dtype="int16", channels=1, callback=audio_cb):
        print("[Vosk] Listening... (Ctrl+C to stop)")
        partial_last = ""
        last_final_text = ""
        last_final_ts = 0.0

        try:
            while True:
                data = q.get()
                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    text = result.get("text", "").strip()
                    if text:
                        # 1) Filter out too short or meaningless results
                        tokens = text.split()

                        # 짧은 결과 필터 — 단, 웨이크워드는 통과
                        if (len(text) < 3 or len(tokens) < 2) and not _is_wake_like(text):
                            rec.Reset()
                            partial_last = ""
                            continue

                        # 같은 결과 빠르게 반복될 때 억제
                        now = time.time()
                        if text == last_final_text and (now - last_final_ts) < 1.0:
                            rec.Reset()
                            partial_last = ""
                            continue

                        print(">>", text)
                        on_asr_final(text, confidence=None)

                        # Update state and reset (중요!)
                        last_final_text = text
                        last_final_ts = now
                        rec.Reset()
                        partial_last = ""
                else:
                    part = json.loads(rec.PartialResult()).get("partial", "")
                    if part and part != partial_last:
                        partial_last = part

        except KeyboardInterrupt:
            print("\n[Vosk] Stopped.")

if __name__ == "__main__":
    main()
