import librosa
import numpy as np
from gtts import gTTS
import os

# 🎤 사용자에게 파일 경로 입력받기
file_path = input("🔍 분석할 오디오 파일 경로를 입력하세요 (예: test.wav, sample.mp3): ").strip()

# 📁 파일 존재 여부 확인
if not os.path.exists(file_path):
    print("❌ 해당 파일이 존재하지 않습니다.")
    exit()

# 🎶 입력 음성 재생 (mpg123로 대체도 가능)
print("🔊 입력한 오디오를 재생합니다...")
os.system(f"mpg123 \"{file_path}\"")

# 📥 오디오 로딩 후 성별 분석
y, sr = librosa.load(file_path, sr=None)
f0 = librosa.yin(y, fmin=50, fmax=300, sr=sr)
f0_nonzero = f0[f0 > 0]
mean_f0 = np.mean(f0_nonzero)
gender = "male" if mean_f0 < 165 else "female"

print(f"\n📈 평균 기본 주파수: {mean_f0:.2f} Hz")
print(f"🧑‍⚖️ 추정 성별: {gender.title()}")

# 🔊 TTS 안내 생성 및 재생
tts_text = f"This is a {gender} voice."
tts = gTTS(tts_text, lang='en')
tts.save("gender_result.mp3")
os.system("mpg123 gender_result.mp3")