# === voice_router.py ===
import re
import time
from weatherapi_en import handle_weather_query, speak_en
from fxapi_en import handle_fx_query

# ------------------------
# State variables
# ------------------------
_last_text = ""
_last_ts = 0.0
_DEBOUNCE_SEC = 2.5   # Debounce window for consecutive recognitions

# Wake word / intent keywords
SLEEP_WORDS = ["sleep", "stop listening", "go to sleep"]
KEEP_AWAKE_ON_ACTIVITY_SEC = 6
POST_TTS_GRACE_SEC = 6

# intent regex
FX_INTENT = re.compile(r"\b(exchange(?:\s+rate)?|currency|fx|rate|rates)\b", re.I)
WEATHER_INTENT = re.compile(r"\b(weather|temperature|forecast)\b", re.I)

# ------------------------
# Suppress TTS echo / hard reset
# ------------------------
_TTS_SUPPRESS_UNTIL = 0.0
POST_TTS_SUPPRESS_SEC = 1.25   # Ignore ASR for this long after TTS finishes

recognizer_reset_cb = None  # Hook to connect external rec.Reset()

def _now() -> float:
    return time.time()

def suppress_asr_for(sec: float):
    """Suppress ASR to avoid capturing TTS echo."""
    global _TTS_SUPPRESS_UNTIL
    _TTS_SUPPRESS_UNTIL = max(_TTS_SUPPRESS_UNTIL, _now() + sec)

def _hard_reset_after_tts():
    """Reset ASR internal state / debounce variables."""
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
# Domain detection / slicing
# ------------------------
def _is_wake_phrase(q: str) -> bool:
    return q.startswith("hello there") or q.startswith("hey there")

def _is_awake() -> bool:
    # TODO: State management logic (assume always True in this example)
    return True

def _wake():
    # TODO: state awake = True
    pass

def _sleep():
    # TODO: state awake = False
    pass

def keep_awake(sec: float):
    # TODO: reset keep-awake timer
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
    # Treat as FX if currency-related words appear
    return any(w in q for w in ["usd", "dollar", "won", "korea", "japan", "yen", "canada", "cad"])

def route_domain(text: str) -> str:
    t = text.lower()
    if FX_INTENT.search(t) or looks_like_fx(t):
        return "fx"
    if WEATHER_INTENT.search(t):
        return "weather"
    return "unknown"

def extract_city(q: str):
    # TODO: parse city name
    return None

WHEN_PAT = re.compile(r"\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)

# ------------------------
# on_asr_final main routine
# ------------------------
def on_asr_final(recognized_text: str, confidence: float | None = None):
    global _last_text, _last_ts

    # 0) Gate for suppressing TTS echo
    if _now() < _TTS_SUPPRESS_UNTIL:
        print(f"[Router] Suppressed during TTS: {recognized_text.strip()}")
        return

    # 1) Normalize
    q_raw = recognized_text
    q = normalize(q_raw)

    # Extend awake state due to detected activity
    keep_awake(KEEP_AWAKE_ON_ACTIVITY_SEC)

    # Check wake phrase
    is_wake_like = _is_wake_phrase(q)

    # 2) Filter very short utterances
    if not (is_wake_like or WEATHER_INTENT.search(q) or FX_INTENT.search(q) or looks_like_fx(q)):
        if len(q) < 3 or len(q.split()) < 2:
            print(f"[Router] Ignored short: {q}")
            return

    # 3) Debounce
    now = time.time()
    if q == _last_text and (now - _last_ts) < _DEBOUNCE_SEC:
        print(f"[Router] Debounced: {q}")
        return
    _last_text, _last_ts = q, now

    # 4) Sleep commands
    if any(q.startswith(s) or q == s for s in SLEEP_WORDS):
        _sleep()
        print("[Router] Sleep.")
        return

    # 5) Wake / intent-driven activation
    if _is_awake() or is_wake_like or WEATHER_INTENT.search(q) or FX_INTENT.search(q) or looks_like_fx(q):
        _wake()
        # Reset recognizer buffer right after wake
        if recognizer_reset_cb:
            recognizer_reset_cb()

        rest = _strip_leading_wake(q)
        if rest:
            q = rest
        else:
            print("[Router] Wake!")
            return

    # 6) If still sleeping, ignore
    if not _is_awake():
        print(f"[Router] Ignored while sleeping: {q}")
        return

    # 7) Remove wake phrase + slice from first keyword
    q = _strip_leading_wake(q)
    q = slice_from_first_keyword(q)

    # 8) Domain routing
    domain = route_domain(q)

    # 9) For weather, parse city/time
    if domain == "weather":
        _ = extract_city(q)
        _ = WHEN_PAT.search(q) is not None

    # 10) Invoke handlers
    if domain == "fx":
        keep_awake(KEEP_AWAKE_ON_ACTIVITY_SEC)
        try:
            handle_fx_query(q)
        finally:
            # ★ After TTS: suppress/ hard reset / grace period
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
