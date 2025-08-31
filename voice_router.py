# === voice_router.py ===
import re
import time
from weatherapi_en import handle_weather_query, speak_en
from fxapi_en import handle_fx_query

# ------------------------
# 상태 변수들
# ------------------------
_last_text = ""
_last_ts = 0.0
_DEBOUNCE_SEC = 2.5   # 연속 인식 디바운스 시간

# 웨이크워드/의도 키워드
SLEEP_WORDS = ["sleep", "stop listening", "go to sleep"]
KEEP_AWAKE_ON_ACTIVITY_SEC = 6
POST_TTS_GRACE_SEC = 6

# intent regex
FX_INTENT = re.compile(r"\b(exchange(?:\s+rate)?|currency|fx|rate|rates)\b", re.I)
WEATHER_INTENT = re.compile(r"\b(weather|temperature|forecast)\b", re.I)

# ------------------------
# TTS 에코 억제/하드리셋
# ------------------------
_TTS_SUPPRESS_UNTIL = 0.0
POST_TTS_SUPPRESS_SEC = 1.25   # TTS 끝나고 이만큼은 무시

recognizer_reset_cb = None  # 외부에서 rec.Reset() 연결

def _now() -> float:
    return time.time()

def suppress_asr_for(sec: float):
    """TTS 에코 억제"""
    global _TTS_SUPPRESS_UNTIL
    _TTS_SUPPRESS_UNTIL = max(_TTS_SUPPRESS_UNTIL, _now() + sec)

def _hard_reset_after_tts():
    """ASR 내부 상태/디바운스 리셋"""
    global _last_text, _last_ts
    _last_text = ""
    _last_ts = 0.0
    if recognizer_reset_cb:
        try:
            recognizer_reset_cb()  # Vosk recognizer Reset()
        except Exception:
            pass

def set_recognizer_reset(cb):
    global recognizer_reset_cb
    recognizer_reset_cb = cb

# ------------------------
# 도메인 판정 / 슬라이스
# ------------------------
def _is_wake_phrase(q: str) -> bool:
    return q.startswith("hello there") or q.startswith("hey there")

def _is_awake() -> bool:
    # TODO: 상태 관리 로직 (예시에서는 항상 True 가정)
    return True

def _wake():
    # TODO: 상태 awake = True
    pass

def _sleep():
    # TODO: 상태 awake = False
    pass

def keep_awake(sec: float):
    # TODO: 타이머 리셋
    pass

def normalize(s: str) -> str:
    return s.strip().lower()

def _strip_leading_wake(q: str) -> str:
    if q.startswith("hello there"):
        return q[len("hello there"):].strip()
    if q.startswith("hey there"):
        return q[len("hey there"):].strip()
    return q

def slice_from_first_keyword(q: str) -> str:
    m = FX_INTENT.search(q)
    if m:
        return q[m.start():]
    m2 = WEATHER_INTENT.search(q)
    if m2:
        return q[m2.start():]
    return q

def looks_like_fx(q: str) -> bool:
    # 통화 단어가 들어가면 FX 취급
    return any(w in q for w in ["usd", "dollar", "won", "korea", "japan", "yen", "canada", "cad"])

def route_domain(text: str) -> str:
    t = text.lower()
    if FX_INTENT.search(t) or looks_like_fx(t):
        return "fx"
    if WEATHER_INTENT.search(t):
        return "weather"
    return "unknown"

def extract_city(q: str):
    # TODO: 도시 파싱
    return None

WHEN_PAT = re.compile(r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)

# ------------------------
# on_asr_final 본체
# ------------------------
def on_asr_final(recognized_text: str, confidence: float | None = None):
    global _last_text, _last_ts

    # 0) TTS 에코 억제 게이트
    if _now() < _TTS_SUPPRESS_UNTIL:
        print(f"[Router] Suppressed during TTS: {recognized_text.strip()}")
        return

    # 1) 정리
    q_raw = recognized_text
    q = normalize(q_raw)

    # 활동 감지로 깨어있기 연장
    keep_awake(KEEP_AWAKE_ON_ACTIVITY_SEC)

    # 웨이크워드 여부
    is_wake_like = _is_wake_phrase(q)

    # 2) 짧은 문장 필터
    if not (is_wake_like or WEATHER_INTENT.search(q) or FX_INTENT.search(q) or looks_like_fx(q)):
        if len(q) < 3 or len(q.split()) < 2:
            print(f"[Router] Ignored short: {q}")
            return

    # 3) 디바운스
    now = time.time()
    if q == _last_text and (now - _last_ts) < _DEBOUNCE_SEC:
        print(f"[Router] Debounced: {q}")
        return
    _last_text, _last_ts = q, now

    # 4) 수면 명령
    if any(q.startswith(s) or q == s for s in SLEEP_WORDS):
        _sleep()
        print("[Router] Sleep.")
        return

    # 5) 웨이크/의도 기반 각성
    if _is_awake() or is_wake_like or WEATHER_INTENT.search(q) or FX_INTENT.search(q) or looks_like_fx(q):
        _wake()
        # 웨이크 직후 인식기 버퍼 리셋
        if recognizer_reset_cb:
            recognizer_reset_cb()

        rest = _strip_leading_wake(q)
        if rest:
            q = rest
        else:
            print("[Router] Wake!")
            return

    # 6) 아직 수면이면 무시
    if not _is_awake():
        print(f"[Router] Ignored while sleeping: {q}")
        return

    # 7) 웨이크워드 제거 + 키워드 기준 슬라이스
    q = _strip_leading_wake(q)
    q = slice_from_first_keyword(q)

    # 8) 도메인 판정
    domain = route_domain(q)

    # 9) 날씨는 도시/시점 파싱
    if domain == "weather":
        _ = extract_city(q)
        _ = WHEN_PAT.search(q) is not None

    # 10) 핸들러 호출
    if domain == "fx":
        keep_awake(KEEP_AWAKE_ON_ACTIVITY_SEC)
        try:
            handle_fx_query(q)
        finally:
            # ★ TTS 직후 억제/하드리셋/여유
            suppress_asr_for(POST_TTS_SUPPRESS_SEC)
            _hard_reset_after_tts()
            keep_awake(POST_TTS_GRACE_SEC)

    elif domain == "weather":
        keep_awake(KEEP_AWAKE_ON_ACTIVITY_SEC)
        try:
            handle_weather_query(q)
        finally:
            suppress_asr_for(POST_TTS_SUPPRESS_SEC)
            _hard_reset_after_tts()
            keep_awake(POST_TTS_GRACE_SEC)

    else:
        print(f"[Router] Unknown domain: {q}")
