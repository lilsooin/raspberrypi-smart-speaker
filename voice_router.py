# voice_router.py
import re
import time
# 기존: weather 처리 핸들러
from weatherapi_en import handle_weather_query, speak_en  # ← TTS 사용 위해 speak_en 추가 임포트

WAKE_WORDS = ["computer", "hey assistant", "hey buddy"]

# 디바운스(중복 억제)용 캐시
_last_text = ""
_last_ts = 0.0
_DEBOUNCE_SEC = 1.0

# 패턴: 날씨/온도 위주 + now/today/weekday 지원
WEATHER_KEY = re.compile(r"\b(weather|temperature|temp|forecast|rain|precip|sunny|cloudy|snow|humidity)\b", re.I)
CITY_PAT = re.compile(r"\bin\s+([a-zA-Z ]+)\b", re.I)
WHEN_PAT = re.compile(r"\b(now|today|tomorrow|day after tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)

def normalize(s: str) -> str:
    s = s.strip()
    # 공백/구두점 정리
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s

def strip_wakeword(text: str) -> str:
    t = text.lstrip()
    low = t.lower()
    for w in WAKE_WORDS:
        if low.startswith(w):
            return t[len(w):].lstrip(" ,.:!?")
    return t

def route_domain(text: str) -> str:
    t = text.lower()
    if WEATHER_KEY.search(t):
        return "weather"
    return "unknown"

def on_asr_final(recognized_text: str, confidence: float | None = None):
    global _last_text, _last_ts

    # 1) 정리
    q = strip_wakeword(recognized_text)
    q = normalize(q)

    # 2) 너무 짧은/무의미 텍스트 제거
    if len(q) < 3 or len(q.split()) < 2:
        print(f"[Router] Ignored short: {q}")
        return

    # 3) 디바운스(같은 문장 반복 억제)
    now = time.time()
    if q == _last_text and (now - _last_ts) < _DEBOUNCE_SEC:
        print(f"[Router] Debounced: {q}")
        return
    _last_text, _last_ts = q, now

    # 4) 날씨 도메인만 통과
    if route_domain(q) != "weather":
        print(f"[Router] Unknown domain: {q}")
        return

    # 5) "in <city>" 있으면 바로 통과, 없더라도 now/today/weekday 포함이면 통과
    has_city = CITY_PAT.search(q) is not None
    has_when = WHEN_PAT.search(q) is not None

    if has_city or has_when:
        handle_weather_query(q)
    else:
        # 도시 추출 실패 시에도 weather 키워드가 있으면 통과(나중에 퍼지매칭으로 보정)
        handle_weather_query(q)