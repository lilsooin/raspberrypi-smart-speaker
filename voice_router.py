# voice_router.py
from weatherapi_en import handle_weather_query

WAKE_WORDS = ["computer", "hey assistant", "hey buddy"]

def strip_wakeword(text: str) -> str:
    t = text.strip()
    low = t.lower()
    for w in WAKE_WORDS:
        if low.startswith(w):
            return t[len(w):].lstrip(" ,.:!?")
    return t

def route_domain(text: str) -> str:
    t = text.lower()
    if any(k in t for k in [
        "weather","temperature","temp","forecast","rain","precip",
        "wind","sunny","cloudy","snow","humidity"
    ]):
        return "weather"
    return "unknown"

def on_asr_final(recognized_text: str, confidence: float | None = None):
    # 필요시 confidence로 필터링 가능
    q = strip_wakeword(recognized_text)
    if route_domain(q) == "weather":
        handle_weather_query(q)
    else:
        print(f"[Router] Unknown domain: {q}")