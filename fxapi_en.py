# fxapi_en.py
import re
import requests
from weatherapi_en import speak_en  # 기존 TTS 재사용

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

# 입력에서 금액/페어 파싱: "1000 kor to usd", "kor to usd", "jp to cad", "5000 won to cad"
RE_AMOUNT_PAIR = re.compile(
    r"""
    ^\s*
    (?:(?P<amount>\d+(?:\.\d+)?)\s+)?           # 옵션: 금액
    (?P<from>[A-Za-z]{2,8})\s*                  # from 통화 별칭
    (?:to|in|->|→)\s*                           # to 키워드
    (?P<to>[A-Za-z]{2,8})\s*$                   # to 통화 별칭
    """,
    re.I | re.X,
)

def _norm_ccy(token: str) -> str | None:
    t = token.strip().lower()
    return ALIASES.get(t) or (t.upper() if t.upper() in {"KRW","JPY","USD","CAD"} else None)

def _fetch_rate(base: str, target: str, amount: float | None):
    params = []
    if amount is not None:
        params.append(f"amount={amount}")
    params.append(f"from={base}")
    params.append(f"to={target}")
    url = f"{FRANKFURTER}/latest?" + "&".join(params)
    r = requests.get(url, timeout=5)
    r.raise_for_status()
    data = r.json()
    # Frankfurter: {"amount":..., "base":"USD","date":"YYYY-MM-DD","rates":{"CAD":1.37}}
    rate = data["rates"][target]
    # amount가 있으면 rate는 이미 변환된 금액, 없으면 1 base 대비 환율
    return float(rate)

def handle_fx_query(q: str):
    m = RE_AMOUNT_PAIR.search(q)
    if not m:
        speak_en("Say like: kor to usd, or 1000 won to cad.")
        return

    amount_s = m.group("amount")
    amount = float(amount_s) if amount_s else None
    from_alias = m.group("from")
    to_alias = m.group("to")

    base = _norm_ccy(from_alias)
    target = _norm_ccy(to_alias)
    if not base or not target:
        speak_en("I couldn't recognize the currencies. Try kor to usd or jp to cad.")
        return

    # 허용 페어만 처리
    if (base, target) not in ALLOWED_PAIRS:
        speak_en("That pair is not supported. Try kor to usd, kor to cad, kor to jp, jp to cad, jp to usd, jp to kor, or usd to cad.")
        return

    try:
        rate_or_amount = _fetch_rate(base, target, amount)
        if amount is None:
            # 1 base → rate target
            speak_en(f"One {base} is {rate_or_amount:.4f} {target}.")
        else:
            # amount base → converted target amount
            speak_en(f"{amount:.2f} {base} is {rate_or_amount:.2f} {target}.")
    except Exception:
        speak_en("I couldn't fetch the exchange rate right now.")