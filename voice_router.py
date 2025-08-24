# voice_router.py
import re
import time
# 기존: weather 처리 핸들러
from weatherapi_en import handle_weather_query, speak_en  # ← TTS 사용 위해 speak_en 추가 임포트

# -----------------------------
# 설정/상태
# -----------------------------
WAKE_WORDS = ["hey there", "hello there", "the hey there", "the hello there"]
SLEEP_WORDS = ["shut up", "good bye", "never mind", "cancel"]

# 웨이크워드 뒤에 붙은 구두점/공백을 걷어내기 위한 정규식
_LEADING_SEP_RE = re.compile(r'^[\s\W_]+', flags=re.UNICODE)
_WAKE_WINDOW_SEC = 30  # 깨어있는 유지 시간
_awake_until = 0.0     # 타임스탬프

# 디바운스(중복 억제)용 캐시
_last_text = ""
_last_ts = 0.0
_DEBOUNCE_SEC = 1.0

# 패턴: 날씨/온도 위주 + now/today/weekday 지원
# "the weather" 같은 관사 포함도 허용
WEATHER_KEY = re.compile(r"\b(?:the\s+)?(weather|temperature|temp|forecast|rain|precip|sunny|cloudy|snow|humidity)\b", re.I)

# 도시 패턴 보강:
# - in/for/at <city>
# - <city> weather/forecast
CITY_PAT = re.compile(
    r"""
    (?:\b(?:in|for|at)\s+([a-zA-Z][a-zA-Z\s\-']+)\b)         # in/for/at CITY
    |
    (?:\b([a-zA-Z][a-zA-Z\s\-']+)\s+(?:weather|forecast)\b)  # CITY weather/forecast
    """,
    re.I | re.X
)

WHEN_PAT = re.compile(
    r"\b(now|today|tomorrow|day after tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.I
)

# -----------------------------
# 유틸 함수
# -----------------------------
def _now():
    return time.time()

def _is_awake() -> bool:
    return _now() < _awake_until

def _wake():
    global _awake_until
    _awake_until = _now() + _WAKE_WINDOW_SEC
    # 필요 시 짧은 피드백
    # speak_en("Yes?")

def _sleep():
    """수면 상태로 전환."""
    global _awake_until
    _awake_until = 0.0

def normalize(s: str) -> str:
    """공백/구두점 정리, 다중 공백 축약."""
    s = s.strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s

def _match_wake_prefix(t: str, w: str) -> int:
    """
    t가 웨이크워드 w로 시작하면 w의 끝 인덱스(잘라낼 위치)를 반환.
    - 정확히 같거나
    - w 바로 다음 문자가 '단어 경계'(영숫자 아님)일 때만 매칭으로 인정.
    매치 없으면 -1
    """
    if t == w:
        return len(w)
    if t.startswith(w):
        if len(t) == len(w):
            return len(w)
        nxt = t[len(w)]
        if not nxt.isalnum():
            return len(w)
    return -1

def _is_wake_phrase(text_norm: str) -> bool:
    t = text_norm.lower()
    for w in sorted(WAKE_WORDS, key=len, reverse=True):
        if _match_wake_prefix(t, w) != -1:
            return True
    return False

def _strip_leading_wake(text_norm: str) -> str:
    """
    맨 앞 웨이크워드를 한 번 제거.
    웨이크워드 뒤에 붙은 공백/구두점도 함께 제거.
    """
    t = text_norm
    for w in sorted(WAKE_WORDS, key=len, reverse=True):
        cut = _match_wake_prefix(t.lower(), w)
        if cut != -1:
            rest = t[cut:]
            rest = _LEADING_SEP_RE.sub("", rest)
            return rest
    return t

def route_domain(text: str) -> str:
    t = text.lower()
    if WEATHER_KEY.search(t):
        return "weather"
    return "unknown"

def extract_city(q: str) -> str | None:
    """도시명 후보 추출 (패턴 2가지 케이스 지원)."""
    m = CITY_PAT.search(q)
    if not m:
        return None
    # 두 캡쳐 그룹 중 하나만 매칭될 수 있으므로 둘 중 있는 쪽 사용
    city = (m.group(1) or m.group(2)) if (m.group(1) or m.group(2)) else None
    return city.strip() if city else None

# -----------------------------
# 콜백: ASR 최종 결과 수신
# -----------------------------
def on_asr_final(recognized_text: str, confidence: float | None = None):
    global _last_text, _last_ts

    # 1) 정리
    q_raw = recognized_text
    q = normalize(q_raw)

    # 웨이크워드 여부 선계산
    is_wake_like = _is_wake_phrase(q)

    # 2) 너무 짧은 텍스트 필터
    #   - 웨이크워드는 예외
    #   - 날씨 키워드가 있으면 예외 (ASR가 "the weather" 등으로 짧게 끊어도 통과)
    if not is_wake_like and not WEATHER_KEY.search(q):
        if len(q) < 3 or len(q.split()) < 2:
            print(f"[Router] Ignored short: {q}")
            return

    # 3) 디바운스(같은 문장 반복 억제)
    now = time.time()
    if q == _last_text and (now - _last_ts) < _DEBOUNCE_SEC:
        print(f"[Router] Debounced: {q}")
        return
    _last_text, _last_ts = q, now

    # 4) 수면 명령
    if any(q.startswith(s) or q == s for s in SLEEP_WORDS):
        _sleep()
        print("[Router] Sleep.")
        # speak_en("Okay, going to sleep.")
        return

    # 5) 웨이크워드 처리
    if is_wake_like:
        _wake()
        # 웨이크워드 제거 후 남은 질의가 있으면 즉시 처리
        rest = _strip_leading_wake(q)
        if rest:
            q = rest  # 같은 호출에서 계속 진행
        else:
            print("[Router] Wake!")
            # speak_en("Yes?")
            return

    # 6) 깨어있지 않으면 무시 (단, 5)에서 바로 깬 경우는 통과됨)
    if not _is_awake():
        print(f"[Router] Ignored while sleeping: {q}")
        return

    # 7) 웨이크워드 프리픽스 제거(다시 한 번 안전 조치)
    q = _strip_leading_wake(q)

    # 8) 도메인 라우팅 (현재는 weather만)
    if route_domain(q) != "weather":
        print(f"[Router] Unknown domain: {q}")
        return

    # 9) 도시/시점 판정
    city = extract_city(q)
    has_when = WHEN_PAT.search(q) is not None

    # 10) 핸들러 호출
    # - 도시가 있거나, when 키워드가 있거나, 날씨 키워드가 있으면 바로 통과
    if city or has_when or WEATHER_KEY.search(q):
        handle_weather_query(q)
    else:
        # 안전망: 키워드가 모호해도 핸들러에서 퍼지 보정 가능
        handle_weather_query(q)