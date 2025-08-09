import speech_recognition as sr

# Create Recognizer object
recognizer = sr.Recognizer()

# Use default microphone (change device_index if needed)
with sr.Microphone(device_index=3) as source:
    print("🎤 Speak now (about 5 seconds)...")
    recognizer.adjust_for_ambient_noise(source)  # Adjust for ambient noise
    audio = recognizer.listen(source, timeout=5)

try:
    print("🧠 Recognizing...")
    # Use Google STT (requires internet)
    text = recognizer.recognize_google(audio, language='ja-JP')
    print("📝 Recognized text:", text)
except sr.UnknownValueError:
    print("😕 Recognition failed: Could not understand audio.")
except sr.RequestError as e:
    print(f"❌ Google API error: {e}")