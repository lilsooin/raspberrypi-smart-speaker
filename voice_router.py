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
KEEP_AWAKE_ON_ACTIVITY_SEC = 15
POST_TTS_GRACE_SEC = 6


# 디바운스(중복 억제)용 캐시
_last_text = ""
_last_ts = 0.0
_DEBOUNCE_SEC = 1.0

# 패턴: 날씨/온도 위주 + now/today/weekday 지원
# "the weather" 같은 관사 포함도 허용
WEATHER_KEY = re.compile(r"\b(?:the\s+)?(weather|temperature|temp|forecast|rain|precip|sunny|cloudy|snow|humidity)\b", re.I)

# 도시 패턴 보강:
# - in/for/at <city>
# "<city> weather/forecast" 는 문장 맨 앞에서만 허용( ^ ),
# preposition(in/for/at) 뒤 <city> 는 어디서든 허용
CITY_PAT = re.compile(
    r"""
    (?:^([A-Za-z][A-Za-z\s\-']+?)\s+(?:weather|forecast)\b)  # CASE A: ^CITY weather
    |
    (?:\b(?:in|for|at)\s+([A-Za-z][A-Za-z\s\-']+)\b)         # CASE B: in/for/at CITY
    """,
    re.I | re.X
)

WHEN_PAT = re.compile(
    r"\b(now|today|tomorrow|day after tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.I
)

STOPWORDS_START = {
    "what", "what's", "whats", "how", "is", "the", "please", "tell", "tell me", "can", "could"
}


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

def keep_awake(sec):
    global _awake_until
    _awake_until = max(_awake_until, _now() + sec)

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
    city = (m.group(1) or m.group(2) or "").strip()
    if not city:
        return None
    # 질문사/불용어로 시작하면 무효 (예: "what miya zaki" → drop)
    first_token = city.lower().split()[0]
    if first_token in STOPWORDS_START:
        return None
    return city

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
    if _is_awake() or is_wake_like or WEATHER_KEY.search(q):
        _wake()
        
        # 웨이크워드 제거 후 남은 질의가 있으면 즉시 처리
        rest = _strip_leading_wake(q)
        if rest:
            q = rest  # 같은 호출에서 계속 진행
        else:
            print("[Router] Wake!")
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
    domain = route_domain(q)

    if domain == "weather":
        keep_awake(KEEP_AWAKE_ON_ACTIVITY_SEC)  # 처리 시작 전: 최소 유지
        try:
            # 도메인만 확정되면 무조건 호출 → 핸들러가 자체적으로 부족한 슬롯(도시/날짜 등)을 보완/질문
            handle_weather_query(q)
        finally:
            keep_awake(POST_TTS_GRACE_SEC)  # TTS 직후 여유
    elif domain == "fx":  # 예: 환율
        keep_awake(KEEP_AWAKE_ON_ACTIVITY_SEC)
        try:
            handle_fx_query(q)
        finally:
            keep_awake(POST_TTS_GRACE_SEC)
    else:
        # unknown: 필요하면 간단 피드백/무시
        pass