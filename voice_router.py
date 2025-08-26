# voice_router.py
import re
import time
# 핸들러
from weatherapi_en import handle_weather_query, speak_en
from fxapi_en import handle_fx_query  # 환율

# -----------------------------
# 설정/상태
# -----------------------------
WAKE_WORDS = ["hey there", "hello there", "the hey there", "the hello there"]
SLEEP_WORDS = ["shut up", "good bye", "never mind", "cancel"]

_LEADING_SEP_RE = re.compile(r'^[\s\W_]+', flags=re.UNICODE)
_WAKE_WINDOW_SEC = 30
_awake_until = 0.0
KEEP_AWAKE_ON_ACTIVITY_SEC = 15
POST_TTS_GRACE_SEC = 6

_last_text = ""
_last_ts = 0.0
_DEBOUNCE_SEC = 1.0

# -----------------------------
# 패턴 (날씨)
# -----------------------------
WEATHER_KEY = re.compile(
    r"\b(?:the\s+)?(weather|temperature|temp|forecast|rain|precip|sunny|cloudy|snow|humidity)\b",
    re.I,
)

# "<city> weather/forecast" 는 문장 맨 앞에서만 허용(^), in/for/at CITY 는 어디서나 허용
CITY_PAT = re.compile(
    r"""
    (?:^([A-Za-z][A-Za-z\s\-']+?)\s+(?:weather|forecast)\b)  # CASE A: ^CITY weather
    |
    (?:\b(?:in|for|at)\s+([A-Za-z][A-Za-z\s\-']+)\b)         # CASE B: in/for/at CITY
    """,
    re.I | re.X,
)

WHEN_PAT = re.compile(
    r"\b(now|today|tomorrow|day after tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.I,
)

STOPWORDS_START = {
    "what", "what's", "whats", "how", "is", "the", "please", "tell", "tell me", "can", "could"
}

# -----------------------------
# 패턴 (환율)
# -----------------------------
FX_KEY = re.compile(
    r"\b(exchange rate|currency|fx|kor|krw|won|korea|jp|jpy|yen|japan|usd|cad|dollar|canadian|canada)\b",
    re.I,
)

# 키워드가 없어도 FX처럼 보이게 하는 간단한 휴리스틱 (나라/도시/통화 별칭)
FX_ALIASES_MINI = {
    # KRW
    "kor":"KRW","krw":"KRW","won":"KRW","korea":"KRW","korean":"KRW",
    "seoul":"KRW","busan":"KRW","pusan":"KRW",
    # JPY
    "jp":"JPY","jpy":"JPY","yen":"JPY","japan":"JPY","japanese":"JPY",
    "tokyo":"JPY","osaka":"JPY","miyazaki":"JPY",
    # USD
    "usd":"USD","dollar":"USD","us":"USD","usa":"USD","america":"USD","american":"USD",
    # CAD
    "cad":"CAD","canadian":"CAD","canada":"CAD"
}

# ASR 흔한 오인식 교정
FX_PREFIX_FIX = {
    "seol": "seoul",     # seol → seoul
    "soul": "seoul",
    "miya": "miyazaki",  # miya → miyazaki
    "pusan": "busan",
}

recognizer_reset_cb = None  # 외부에서 Vosk rec.Reset 등을 연결

# -----------------------------
# 유틸
# -----------------------------
def _now():
    return time.time()

def _is_awake() -> bool:
    return _now() < _awake_until

def _wake():
    global _awake_until
    _awake_until = _now() + _WAKE_WINDOW_SEC

def keep_awake(sec: float):
    global _awake_until
    _awake_until = max(_awake_until, _now() + sec)

def _sleep():
    global _awake_until
    _awake_until = 0.0

def normalize(s: str) -> str:
    s = s.strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s

def _match_wake_prefix(t: str, w: str) -> int:
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
    t = text_norm
    for w in sorted(WAKE_WORDS, key=len, reverse=True):
        cut = _match_wake_prefix(t.lower(), w)
        if cut != -1:
            rest = t[cut:]
            rest = _LEADING_SEP_RE.sub("", rest)
            return rest
    return t

def _fx_norm_token(tok: str) -> str:
    t = tok.lower()
    if t in FX_PREFIX_FIX:
        t = FX_PREFIX_FIX[t]
    return t

def looks_like_fx(q: str) -> bool:
    """
    키워드가 없어도 문장 내에 통화/나라/도시 별칭이 2개 이상이면 FX로 간주.
    'to|in|into|->|→' 같은 연결어가 있으면 1개만 잡혀도 FX로 간주.
    """
    tokens = re.findall(r"[a-zA-Z]+", q.lower())
    tokens = [_fx_norm_token(t) for t in tokens]
    has_connector = any(t in ("to", "in", "into") for t in tokens)
    codes = [FX_ALIASES_MINI[t] for t in tokens if t in FX_ALIASES_MINI]
    return len(codes) >= 2 or (has_connector and len(codes) >= 1)

def slice_from_first_keyword(q: str) -> str:
    """currency/weather 키워드가 있으면 그 지점부터 잘라 잔상/잡음 앞부분 제거"""
    m = FX_KEY.search(q)
    if m:
        return q[m.start():]
    m2 = WEATHER_KEY.search(q)
    if m2:
        return q[m2.start():]
    return q

def route_domain(text: str) -> str:
    t = text.lower()
    # FX 우선 (키워드 OR 휴리스틱)
    if FX_KEY.search(t) or looks_like_fx(t):
        return "fx"
    if WEATHER_KEY.search(t):
        return "weather"
    return "unknown"

def extract_city(q: str) -> str | None:
    m = CITY_PAT.search(q)
    if not m:
        return None
    city = (m.group(1) or m.group(2) or "").strip()
    if not city:
        return None
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

    # ASR 최종 수신 → 상호작용 진행 중이므로 유지
    keep_awake(KEEP_AWAKE_ON_ACTIVITY_SEC)

    # 웨이크워드 여부
    is_wake_like = _is_wake_phrase(q)

    # 2) 짧은 문장 필터 (웨이크/날씨/환율/휴리스틱은 예외)
    if not is_wake_like and not (WEATHER_KEY.search(q) or FX_KEY.search(q) or looks_like_fx(q)):
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
    if _is_awake() or is_wake_like or WEATHER_KEY.search(q) or FX_KEY.search(q) or looks_like_fx(q):
        _wake()
        # 웨이크 직후 인식기 버퍼 리셋 (외부에서 set_recognizer_reset로 연결)
        if recognizer_reset_cb:
            recognizer_reset_cb()

        rest = _strip_leading_wake(q)
        if rest:
            q = rest
        else:
            print("[Router] Wake!")
            return

    # 6) 아직 수면이면 중단
    if not _is_awake():
        print(f"[Router] Ignored while sleeping: {q}")
        return

    # 7) 웨이크워드 제거 + 키워드 시작점으로 슬라이스
    q = _strip_leading_wake(q)
    q = slice_from_first_keyword(q)

    # 8) 도메인 판정
    domain = route_domain(q)

    # 9) (weather 참고 파싱: 핸들러 내부 보정 전)
    if domain == "weather":
        _ = extract_city(q)
        _ = WHEN_PAT.search(q) is not None

    # 10) 핸들러 호출
    if domain == "fx":
        keep_awake(KEEP_AWAKE_ON_ACTIVITY_SEC)
        try:
            handle_fx_query(q)
        finally:
            keep_awake(POST_TTS_GRACE_SEC)

    elif domain == "weather":
        keep_awake(KEEP_AWAKE_ON_ACTIVITY_SEC)
        try:
            handle_weather_query(q)
        finally:
            keep_awake(POST_TTS_GRACE_SEC)

    else:
        print(f"[Router] Unknown domain: {q}")

def set_recognizer_reset(cb):
    """외부(Vosk 등)에서 recognizer_reset_cb(lambda: rec.Reset()) 연결"""
    global recognizer_reset_cb
    recognizer_reset_cb = cb