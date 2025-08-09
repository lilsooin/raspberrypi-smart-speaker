#!/bin/bash

# ===== 사용자 설정 =====
BT_DEVICE_MAC="00:02:3C:C7:05:7A"       # Pebble V3 MAC 주소
VENV_PATH="$HOME/venv"                 # 가상환경 경로
PY_SCRIPT="$HOME/work/test.py"         # 실행할 Python 파일 경로
TMP_VOICE="$HOME/work/bt_status.mp3"   # 음성 안내 mp3 저장 경로

# ===== TTS 함수 (텍스트 → 음성) =====
say() {
  TEXT="$1"
  echo "🗣️ Speaking: $TEXT"
  python3 - <<EOF
from gtts import gTTS
tts = gTTS("$TEXT", lang="ko")
tts.save("$TMP_VOICE")
EOF
  mpg123 "$TMP_VOICE" >/dev/null 2>&1
}

# ===== 블루투스 연결 시도 루프 =====
echo "🔄 Trying to connect to $BT_DEVICE_MAC..."
for i in {1..60}; do
  bluetoothctl <<EOF | grep -q "Connection successful"
connect $BT_DEVICE_MAC
EOF

  if bluetoothctl info "$BT_DEVICE_MAC" | grep -q "Connected: yes"; then
    echo "✅ Connected to $BT_DEVICE_MAC"
    break
  fi

  # 안내 메시지는 첫 시도 후 한 번만 출력
  if [ "$i" -eq 1 ]; then
    say "스피커가 다른 기기와 연결 중입니다. 연결을 대기합니다."
  fi

  echo "⏳ Not connected. Retrying in 5s... ($i/60)"
  sleep 5
done

# 연결 실패 시 종료
if ! bluetoothctl info "$BT_DEVICE_MAC" | grep -q "Connected: yes"; then
  say "스피커를 연결할 수 없습니다. 종료합니다."
  echo "❌ Failed to connect to $BT_DEVICE_MAC"
  exit 1
fi

# ===== Sink 대기 및 설정 =====
echo "⏳ Waiting for Bluetooth audio sink to appear..."
for i in {1..15}; do
  SINK_NAME=$(pactl list short sinks | grep bluez_output | awk '{print $1}')
  if [ -n "$SINK_NAME" ]; then
    echo "✅ Sink found: $SINK_NAME"
    
    # sink 설정 후에만 say() 실행
    pactl set-default-sink "$SINK_NAME"

    say "스피커에 연결되었습니다."

    break
  fi
  sleep 1
done

if [ -z "$SINK_NAME" ]; then
  say "블루투스 오디오 출력 장치를 찾을 수 없습니다."
  echo "❌ Bluetooth sink not found after timeout."
  exit 1
fi

# ===== 가상환경 진입 및 Python 실행 =====
echo "🐍 Activating Python virtual environment..."
source "$VENV_PATH/bin/activate"

echo "🚀 Running Python script..."
python3 "$PY_SCRIPT"

# ===== 종료 =====
echo "✅ Finished."
