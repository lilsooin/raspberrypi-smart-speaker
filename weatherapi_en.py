import re
import os
import time
import requests
import subprocess
from datetime import datetime, timedelta
from gtts import gTTS

# === Settings ===
WEATHERAPI_KEY = os.environ.get("WEATHERAPI_KEY")   # API key
DEFAULT_CITY = "Toronto"
UNITS = "metric"   # metric = Celsius, imperial = Fahrenheit
LANG_TTS = "en"

CITY_ALIASES = {
    "toronto": "Toronto",
    "busan": "Busan",
    "seoul": "Seoul",
    "miyazaki": "Miyazaki",
    "tokyo": "Tokyo",
    "new york": "New York",
}

def normalize(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"[?!.,]", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t

# Parse date from query
def parse_when(text: str):
    today = datetime.now()
    target_date = today.date()
    label = "today"

    if "tomorrow" in text:
        target_date = (today + timedelta(days=1)).date()
        label = "tomorrow"
    elif "day after tomorrow" in text:
        target_date = (today + timedelta(days=2)).date()
        label = "the day after tomorrow"
    else:
        # weekday handling
        weekdays = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
        for wd in weekdays:
            if wd in text:
                target_idx = weekdays.index(wd)
                delta = (target_idx - today.weekday()) % 7
                target_date = (today + timedelta(days=delta)).date()
                label = wd if delta != 0 else "today"
                break
    return target_date, label

# Parse city
def parse_city(text: str):
    for k, v in CITY_ALIASES.items():
        if k in text:
            return v
    m = re.search(r"in ([a-zA-Z\s]+)", text)
    if m:
        return m.group(1).strip()
    return DEFAULT_CITY

# Detect intent
def detect_intent(text: str):
    if "temperature" in text:
        return "temperature"
    if "rain" in text or "precipitation" in text:
        return "precip"
    if "wind" in text:
        return "wind"
    if "forecast" in text or "tomorrow" in text or "day after" in text:
        return "forecast"
    return "current"

# Fetch current weather
def fetch_current_weather(city: str):
    url = f"http://api.weatherapi.com/v1/current.json"
    params = {"key": WEATHERAPI_KEY, "q": city, "aqi": "no"}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()

# Fetch forecast
def fetch_forecast(city: str, days=3):
    url = f"http://api.weatherapi.com/v1/forecast.json"
    params = {"key": WEATHERAPI_KEY, "q": city, "days": days, "aqi": "no", "alerts": "no"}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()

# Speak in English
def speak_en(text: str, outfile="tts.mp3"):
    tts = gTTS(text=text, lang=LANG_TTS)
    tts.save(outfile)
    subprocess.run(["mpg123", "-q", outfile])

def handle_weather_query(utterance: str):
    utterance = normalize(utterance)
    intent = detect_intent(utterance)
    target_date, date_label = parse_when(utterance)
    city = parse_city(utterance)

    try:
        if intent == "forecast" or target_date != datetime.now().date():
            data = fetch_forecast(city, days=5)
            forecast_days = data.get("forecast", {}).get("forecastday", [])
            pick = next((d for d in forecast_days if datetime.strptime(d["date"], "%Y-%m-%d").date() == target_date), None)
            if not pick:
                speak_en(f"I could not find the forecast for {city} on {date_label}.")
                return
            condition = pick["day"]["condition"]["text"]
            avg_temp = pick["day"]["avgtemp_c"]
            max_temp = pick["day"]["maxtemp_c"]
            min_temp = pick["day"]["mintemp_c"]
            rain_prob = pick["day"].get("daily_chance_of_rain", 0)
            wind = pick["day"]["maxwind_kph"]

            msg = f"The weather in {city} on {date_label} will be {condition}, with an average temperature of {avg_temp} degrees Celsius, a high of {max_temp}, a low of {min_temp}, {rain_prob} percent chance of rain, and winds up to {wind} kilometers per hour."
            speak_en(msg)
            return

        # current
        data = fetch_current_weather(city)
        condition = data["current"]["condition"]["text"]
        temp = data["current"]["temp_c"]
        wind = data["current"]["wind_kph"]
        precip = data["current"]["precip_mm"]

        if intent == "temperature":
            msg = f"The current temperature in {city} is {temp} degrees Celsius."
        elif intent == "precip":
            if precip > 0:
                msg = f"It is currently {condition} in {city}, with {precip} millimeters of precipitation."
            else:
                msg = f"It is currently {condition} in {city}, with no precipitation detected."
        elif intent == "wind":
            msg = f"The wind speed in {city} is {wind} kilometers per hour, and the weather is {condition}."
        else:
            msg = f"The weather in {city} right now is {condition}, with a temperature of {temp} degrees Celsius and winds at {wind} kilometers per hour."
        speak_en(msg)

    except requests.HTTPError:
        speak_en("There was a problem connecting to the weather service. Please check the city name or your network.")
    except Exception as e:
        speak_en("An unexpected error occurred. Please try again later.")

if __name__ == "__main__":
    test_queries = [
        "What's the weather today in Toronto?",
        "What's the weather today in Miyazaki?",
        "Tell me the forecast for tomorrow in Toronto.",
        "What's the temperature in Seoul?",
        "Is it raining in Miyazaki?",
        "What's the wind speed in Toronto?",
        "Weather on Friday in Toronto."
    ]
    for q in test_queries:
        print(">>", q)
        handle_weather_query(q)
        time.sleep(1.0)