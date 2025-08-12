# asr_vosk_live.py
import json, queue, sys, time
import sounddevice as sd
from vosk import Model, KaldiRecognizer
from voice_router import on_asr_final

MODEL_PATH = "models/vosk-model-en-us-0.22-lgraph"
SAMPLE_RATE = 16000
BLOCKSIZE = 4096  # ↓ 0.5s → ~0.26s (체감 반응속도 개선)
PHRASES = [
  # 문장 패턴(질문)
  "what is the weather in", "what's the weather in", "how is the weather in",

  # 날짜 토큰 (질의 보조)
  "what is the temperature in", "temperature in", "weather in",
  "weather now in", "temperature now in", "now in", "right now in",
  "now", "today", "tomorrow", "day after tomorrow",

  # 도시명(정식 + 흔한 오타/변형)
  "monday","tuesday","wednesday","thursday","friday","saturday","sunday",
  "miyazaki","miyasaki","miya zaki",
  "toronto","tokyo","busan","pusan","seoul","seol","soul","new york"
]


def main():
    model = Model(MODEL_PATH)
    rec = KaldiRecognizer(model, SAMPLE_RATE, json.dumps(PHRASES))
    rec.SetWords(True)

    # 너무 많은 오디오가 한꺼번에 밀려들어오는 걸 방지
    q = queue.Queue(maxsize=8)

    def audio_cb(indata, frames, time_info, status):
        if status:
            print(status, file=sys.stderr)
        try:
            q.put_nowait(bytes(indata))
        except queue.Full:
            # 가끔 밀리면 가장 오래된 버퍼를 버림
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
                        # 1) 너무 짧은/무의미 결과 필터
                        if len(text) < 3 or len(text.split()) < 2:
                            # 리셋하고 다음 입력 대기
                            rec.Reset()
                            partial_last = ""
                            continue

                        # 2) 직전 결과와 동일하면(1.0초 내) 무시
                        now = time.time()
                        if text == last_final_text and (now - last_final_ts) < 1.0:
                            rec.Reset()
                            partial_last = ""
                            continue

                        print(">>", text)
                        on_asr_final(text, confidence=None)

                        # 상태 갱신 + 리셋(중요!)
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