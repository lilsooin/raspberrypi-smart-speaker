# fxapi_en.py
import re
import requests
import time
import json
from weatherapi_en import speak_en  # 기존 TTS 재사용

# ------------------- 설정 -------------------
DEBUG = True  # 콘솔에 [FX] 디버그 로그 출력

def fx_debug(*args):
    if DEBUG:
        print("[FX]", *args)

# Frankfurter 기본 (우선 시도)
FRANKFURTER_DOMAINS = ["api.frankfurter.dev", "api.frankfurter.app"]

# 사용자 축약/별칭 → ISO 코드
ALIASES = {
    # 한국 원
    "kor": "KRW", "krw": "KRW", "won": "KRW", "korean": "KRW", "korea": "KRW",
    # 일본 엔
    "jp": "JPY", "jpy": "JPY", "yen": "JPY", "japanese": "JPY", "japan": "JPY",
    # 미국 달러
    "usd": "USD", "dollar": "USD", "us": "USD", "america": "USD", "american": "USD",
    # 캐나다 달러
    "cad": "CAD", "canadian": "CAD", "canada": "CAD",
}

# 허용 페어(순서 중요: from → to)
ALLOWED_PAIRS = {
    ("KRW", "USD"),
    ("KRW", "CAD"),
    ("KRW", "JPY"),
    ("JPY", "CAD"),
    ("JPY", "USD"),
    ("JPY", "KRW"),
    ("USD", "CAD"),
}

# 1) 금액 + from/to 패턴 (from 생략 허용)
RE_AMOUNT_FROM_TO = re.compile(
    r"""
    (?<![A-Za-z0-9])
    (?:(?P<amount>\d+(?:\.\d+)?)\s+)?         # optional amount
    (?:from\s+)?(?P<from>[A-Za-z]{2,12})\s*   # from token (with optional 'from')
    (?:to|in|into|->|→)\s*                    # connector
    (?P<to>[A-Za-z]{2,12})(?![A-Za-z])
    """,
    re.I | re.X
)

# 자유형 파서용
FILLERS = {"currency", "exchange", "rate", "rates", "hello", "there", "the"}
CONNECTORS = {"to", "in", "into"}

def _norm_ccy(tok: str) -> str | None:
    t = tok.strip().lower()
    return ALIASES.get(t) or (t.upper() if t.upper() in {"KRW","JPY","USD","CAD"} else None)

def _tokenize(s: str):
    return re.findall(r"[A-Za-z]+|\d+(?:\.\d+)?", s.lower())

def infer_pair_freeform(s: str):
    """
    연결어가 없거나 'to'가 누락돼도 문장 내 통화 토큰만 모아
    - 연결어가 있으면 직전/직후 통화를 (from→to)
    - 없으면 문장 내 마지막 2개 통화를 (from→to)
    """
    tokens = _tokenize(s)
    cur_idxs = []
    for i, t in enumerate(tokens):
        if t in FILLERS:
            continue
        code = _norm_ccy(t)
        if code:
            cur_idxs.append((i, code))
    if not cur_idxs:
        return (None, None)

    conn_idx = next((i for i, t in enumerate(tokens) if t in CONNECTORS), None)
    if conn_idx is not None:
        left = None
        for i, code in reversed(cur_idxs):
            if i < conn_idx:
                left = code
                break
        right = None
        for i, code in cur_idxs:
            if i > conn_idx:
                right = code
                break
        if left and right:
            return (left, right)

    if len(cur_idxs) >= 2:
        _, a = cur_idxs[-2]
        _, b = cur_idxs[-1]
        return (a, b)

    return (None, None)

# ------------------- 환율 호출 -------------------
def _fetch_rate_once_frankfurter(domain: str, base: str, target: str, amount: float | None, timeout_sec: float):
    params = []
    if amount is not None:
        params.append(f"amount={amount}")
    params += [f"from={base}", f"to={target}"]
    url = f"https://{domain}/latest?" + "&".join(params)
    fx_debug("GET", url)
    r = requests.get(url, timeout=timeout_sec)
    status = r.status_code
    try:
        data = r.json()
    except Exception:
        data = {"_raw": r.text}
    fx_debug(f"{domain} -> HTTP {status}")
    if status != 200:
        raise RuntimeError(f"Frankfurter {domain} HTTP {status} data={data}")
    if "rates" not in data or target not in data["rates"]:
        raise RuntimeError(f"Frankfurter {domain} missing rate for {target}: {data}")
    return float(data["rates"][target])

def _fetch_rate_once_exhost(base: str, target: str, amount: float | None, timeout_sec: float):
    amt = amount if amount is not None else 1
    url = f"https://api.exchangerate.host/convert?from={base}&to={target}&amount={amt}"
    fx_debug("GET", url)
    r = requests.get(url, timeout=timeout_sec)
    status = r.status_code
    try:
        data = r.json()
    except Exception:
        data = {"_raw": r.text}
    fx_debug(f"exchangerate.host -> HTTP {status}")
    if status != 200 or data.get("success") is False:
        raise RuntimeError(f"exchangerate.host HTTP {status} data={data}")
    return float(data.get("result"))

def _fetch_rate(base: str, target: str, amount: float | None, timeout_sec=4.0, retries=1):
    last_exc = None
    for _ in range(retries + 1):
        # Frankfurter .dev → .app
        for dom in FRANKFURTER_DOMAINS:
            try:
                return _fetch_rate_once_frankfurter(dom, base, target, amount, timeout_sec)
            except Exception as e:
                fx_debug("Frankfurter fail:", repr(e))
                last_exc = e
        # exchangerate.host 폴백
        try:
            return _fetch_rate_once_exhost(base, target, amount, timeout_sec)
        except Exception as e3:
            fx_debug("exchangerate.host fail:", repr(e3))
            last_exc = e3
        time.sleep(0.15)
    fx_debug("fetch failed:", repr(last_exc))
    raise last_exc

# ------------------- 응답 포맷 -------------------
def _format_response(base: str, target: str, amount: float | None, rate: float) -> str:
    """
    - amount가 있으면 그대로 변환 결과
    - amount가 없고 KRW<->JPY면 100 단위로 읽기 좋게
    - 그 외는 1 단위
    """
    if amount is not None:
        converted = rate  # Frankfurter/exhost는 amount 포함 시 변환값을 반환 or 비율? → 여기선 rate를 'to 금액'으로 취급
        # 위 fetch 구현은 Frankfurter는 rates[target], amount None이면 1단위 비율,
        # exchangerate.host는 result가 amount 적용 값. 혼선을 피하려고 아래로 통일:
        # amount가 주어진 경우엔 다시 직접 계산:
        unit_rate = _fetch_rate(base, target, None)  # 1단위 비율
        converted = unit_rate * amount
        return f"{amount:.2f} {base} is {converted:.2f} {target}."
    else:
        display_amt = 100.0 if {base, target} == {"KRW", "JPY"} else 1.0
        unit_rate = _fetch_rate(base, target, None)  # 1단위 비율
        converted = unit_rate * display_amt
        if display_amt == 100.0:
            return f"{int(display_amt)} {base} is {converted:.2f} {target}."
        else:
            return f"One {base} is {converted:.4f} {target}."

# ------------------- 엔트리 -------------------
def handle_fx_query(q: str):
    s = q.strip()
    fx_debug("input:", s)

    # 1) 금액+from/to 우선
    m = RE_AMOUNT_FROM_TO.search(s)
    fx_debug("RE match:", m)
    if m:
        amount = float(m.group("amount")) if m.group("amount") else None
        base = _norm_ccy(m.group("from"))
        target = _norm_ccy(m.group("to"))
        fx_debug("parsed:", {"amount": amount, "from": base, "to": target})

        if not base or not target:
            fx_debug("parse fail: base/target missing")
            speak_en("I couldn't recognize the currencies. Try saying from Korea to Japan.")
            return
        if (base, target) not in ALLOWED_PAIRS:
            fx_debug("pair not allowed:", (base, target))
            speak_en("That pair is not supported.")
            return
        try:
            # 1단위 비율을 기준으로 포맷 (내부에서 100단위/amount 처리)
            txt = _format_response(base, target, amount, rate=None)
            fx_debug("ok:", txt)
            speak_en(txt)
            return
        except Exception as e:
            fx_debug("primary fetch failed on RE path:", repr(e), "— trying freeform fallback")
            # 자유형으로 재시도
            fb_base, fb_target = infer_pair_freeform(s)
            fx_debug("fallback freeform:", (fb_base, fb_target))
            if fb_base and fb_target:
                try_pairs = []
                if (fb_base, fb_target) in ALLOWED_PAIRS:
                    try_pairs.append((fb_base, fb_target))
                if (fb_target, fb_base) in ALLOWED_PAIRS:
                    try_pairs.append((fb_target, fb_base))
                for b, t in try_pairs:
                    try:
                        txt = _format_response(b, t, None, rate=None)
                        fx_debug("fallback ok:", txt)
                        speak_en(txt)
                        return
                    except Exception as e2:
                        fx_debug("fallback fetch failed:", repr(e2))
            speak_en("I couldn't fetch the exchange rate right now.")
            return

    # 2) 자유형 파싱: 연결어 없어도 마지막 두 통화로 추정
    base, target = infer_pair_freeform(s)
    fx_debug("freeform:", (base, target))
    if base and target:
        try_pairs = []
        if (base, target) in ALLOWED_PAIRS:
            try_pairs.append((base, target))
        if (target, base) in ALLOWED_PAIRS:
            try_pairs.append((target, base))
        if try_pairs:
            for b, t in try_pairs:
                try:
                    txt = _format_response(b, t, None, rate=None)
                    fx_debug("ok:", txt)
                    speak_en(txt)
                    return
                except Exception as e:
                    fx_debug("fetch failed:", repr(e))
        fx_debug("pair not allowed (freeform):", (base, target))
        speak_en("That pair is not supported.")
        return

    # 3) 실패 안내
    fx_debug("could not parse any currencies")
    speak_en("Please say like: from Korea to Japan, or 1000 won to CAD.")