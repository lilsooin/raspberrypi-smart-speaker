# fxapi_en.py
import re
import requests
from weatherapi_en import speak_en  # 기존 TTS 재사용
import time
import json


FRANKFURTER = "https://api.frankfurter.dev"

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
    ("KRW", "JPY"),  # kor → jp
    ("JPY", "CAD"),
    ("JPY", "USD"),
    ("JPY", "KRW"),  # jp → kor
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

# 2) 연결어 없이 두 통화가 연속으로 나오는 패턴: "<from> <to>"
RE_TWO_CURRENCIES = re.compile(
    r"(?<![A-Za-z0-9])(?P<from>[A-Za-z]{2,12})\s+(?P<to>[A-Za-z]{2,12})(?![A-Za-z])",
    re.I
)

FILLERS = {
    "currency","exchange","rate","rates","hello","there","the"
}

CONNECTORS = {"to","in","into"}


def _norm_ccy(tok: str) -> str | None:
    t = tok.strip().lower()
    return ALIASES.get(t) or (t.upper() if t.upper() in {"KRW","JPY","USD","CAD"} else None)

def _tokenize(s: str):
    # 영문/숫자 토큰만 추출 (대소문자 무시)
    return re.findall(r"[A-Za-z]+|\d+(?:\.\d+)?", s.lower())

def infer_pair_freeform(s: str):
    """
    'to'가 없거나 ASR이 누락해도 문장 내 통화 토큰만 모아
    - 연결어가 있으면 직전/직후 통화를 (from→to)
    - 없으면 문장 내 마지막 2개 통화를 (from→to)
    를 반환. 없으면 (None, None)
    """
    tokens = _tokenize(s)

    # 통화 후보 위치 수집
    cur_idxs = []  # [(idx, code)]
    for i, t in enumerate(tokens):
        if t in FILLERS:
            continue
        code = _norm_ccy(t)
        if code:
            cur_idxs.append((i, code))

    if not cur_idxs:
        return (None, None)

    # 1) 연결어 기준으로 from→to 추정
    conn_idx = next((i for i, t in enumerate(tokens) if t in CONNECTORS), None)
    if conn_idx is not None:
        # conn 이전의 마지막 통화, conn 이후의 첫 통화
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
        # 연결어는 있는데 한쪽이 비면, 마지막 2개 추정으로 폴백

    # 2) 마지막 2개 통화로 추정
    if len(cur_idxs) >= 2:
        _, a = cur_idxs[-2]
        _, b = cur_idxs[-1]
        return (a, b)

    # 통화가 1개뿐이면 불충분
    return (None, None)

# 더 튼튼한 fetch
def _fetch_rate(base: str, target: str, amount: float | None, timeout_sec=4.0, retries=1):
    def fetch_frankfurter(domain):
        params = []
        if amount is not None:
            params.append(f"amount={amount}")
        params += [f"from={base}", f"to={target}"]
        url = f"https://{domain}/latest?" + "&".join(params)
        r = requests.get(url, timeout=timeout_sec)
        status = r.status_code
        try:
            data = r.json()
        except Exception:
            data = {"_raw": r.text}
        if status != 200:
            raise RuntimeError(f"Frankfurter {domain} HTTP {status} data={data}")
        if "rates" not in data or target not in data["rates"]:
            raise RuntimeError(f"Frankfurter {domain} missing rate for {target}: {data}")
        return float(data["rates"][target])

    def fetch_exchangerate_host():
        amt = amount if amount is not None else 1
        url = f"https://api.exchangerate.host/convert?from={base}&to={target}&amount={amt}"
        r = requests.get(url, timeout=timeout_sec)
        status = r.status_code
        try:
            data = r.json()
        except Exception:
            data = {"_raw": r.text}
        if status != 200 or data.get("success") is False:
            raise RuntimeError(f"exchangerate.host HTTP {status} data={data}")
        return float(data.get("result"))

    last_exc = None
    for _ in range(retries + 1):
        try:
            return fetch_frankfurter("api.frankfurter.dev")
        except Exception as e1:
            last_exc = e1
            try:
                return fetch_frankfurter("api.frankfurter.app")
            except Exception as e2:
                last_exc = e2
                try:
                    return fetch_exchangerate_host()
                except Exception as e3:
                    last_exc = e3
        time.sleep(0.15)

    print("[FX] fetch failed:", repr(last_exc))
    raise last_exc

def handle_fx_query(q: str):
    s = q.strip()
    print("s >> " + s)

    # 1) 금액+from/to 패턴 먼저 시도
    m = RE_AMOUNT_FROM_TO.search(s)
    print(f"m >> {m}")
    if m:
        amount = float(m.group("amount")) if m.group("amount") else None
        base = _norm_ccy(m.group("from"))
        target = _norm_ccy(m.group("to"))
        # if base in "JPY" and target in "KRW":
        #    amount * 100
        # elif base in "KRW" and target in "JPY":
            
       if not base or not target:
            print("I couldn't recognize the currencies. Try saying from Korea to Japan.")
            speak_en("I couldn't recognize the currencies. Try saying from Korea to Japan.")
            return
        if (base, target) not in ALLOWED_PAIRS:
            print("That pair is not supported.")
            speak_en("That pair is not supported.")
            return
        try:
            val = _fetch_rate(base, target, amount)
            if amount is None:
                print(f"one {base} is {val:.4f} {target}.")
                speak_en(f"One {base} is {val:.4f} {target}.")
            else:
                print(f"{amount:.2f} {base} is {val:.2f} {target}.")
                speak_en(f"{amount:.2f} {base} is {val:.2f} {target}.")
        except Exception:
            print("I couldn't fetch the exchange rate right now.")
            speak_en("I couldn't fetch the exchange rate right now.")
        return

    # 2) 자유형 파싱: 연결어 없어도 마지막 두 통화로 추정
    base, target = infer_pair_freeform(s)
    if base and target:
        # 허용 페어 확인 + 역순 보정
        try_pairs = []
        if (base, target) in ALLOWED_PAIRS:
            try_pairs.append((base, target))
        if (target, base) in ALLOWED_PAIRS:
            try_pairs.append((target, base))
        if try_pairs:
            for b, t in try_pairs:
                try:
                    val = _fetch_rate(b, t, None)
                    print(f"One {b} is {val:.4f} {t}.")
                    speak_en(f"One {b} is {val:.4f} {t}.")
                    return
                except Exception:
                    pass
        # 통화는 맞게 잡았는데 지원 페어가 아니면 안내
        print("That pair is not supported.")
        speak_en("That pair is not supported.")
        return

    # 3) 여전히 못 찾으면 간단 안내
    print("Please say like: from Korea to Japan, or 1000 won to CAD.")
    speak_en("Please say like: from Korea to Japan, or 1000 won to CAD.")