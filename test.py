from gtts import gTTS
import os

text = "리코 메차 헨타이"  #
tts = gTTS(text=text, lang='ko')  # lang='ja'는 일본어
tts.save("hello_world.mp3")
os.system("mpg123 hello_world.mp3")