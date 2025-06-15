import network, urequests, time, neopixel
from machine import Pin, PWM # 匯入 PWM
from time import ticks_ms, ticks_diff # 非阻塞用

# --------------------------------------------------------------------------
# 環境設定
SSID, PASSWORD = 'C3PO-phone', 'iamthewifi'
BOT_TOKEN      = '7706866961:AAFpD_PlJpL4zLruB1x-3G92VoG70qPPw0c'
CHAT_ID        = '7643071691'

NEOPIXEL_PIN = 27
NUM_PIXELS = 16
np = neopixel.NeoPixel(Pin(NEOPIXEL_PIN), NUM_PIXELS)

# 馬達設定
MOTOR_PIN = 32
motor_pwm = PWM(Pin(MOTOR_PIN), freq=1000) # 馬達 PWM 物件，頻率 1kHz
MOTOR_RUN_SPEED = 32767 # 馬達運行速度 (約 50% 佔空比)
# --------------------------------------------------------------------------
# 狀態變數
current_mode      = "off" # NeoPixel 燈條模式
motor_running     = False # 新增馬達運行狀態：True = 運行, False = 停止
motor_on_time_ms = 0      # 紀錄馬達開啟時間，用於非阻塞控制
motor_state_on = True     # 馬達當前是高電位（轉動）還是低電位（停止）

# ─── Sleep 模式狀態機 ───────────────────────────────────────────────────
sleep_phase       = None    # None=未啟動, 0=等待5s, 1=逐顆熄燈
sleep_mark_ms     = 0       # 時戳基準
sleep_led_idx     = 0       # 下次要關的 LED index
# --------------------------------------------------------------------------
# Wi-Fi
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("連接中 Wi-Fi...", end="")
        wlan.connect(SSID, PASSWORD)
        for _ in range(10):
            if wlan.isconnected(): break
            print(".", end="")
            time.sleep(1)
        print()
    if wlan.isconnected():
        print("✅ Wi-Fi 已連線：", wlan.ifconfig()[0])
        return True
    print("❌ Wi-Fi 連線失敗")
    return False
# --------------------------------------------------------------------------
# NeoPixel 基本操作
def turn_on_pixels(color=(255, 255, 255), brightness=255):
    r, g, b = color
    adjusted_color = (r * brightness // 255, g * brightness // 255, b * brightness // 255)
    for i in range(NUM_PIXELS):
        np[i] = adjusted_color
    np.write()
def turn_off_pixels():
    for i in range(NUM_PIXELS): np[i] = (0,0,0)
    np.write()
# 彩虹

# --- 彩虹色帶工具 ─────────────────────────────────────────────
def wheel(pos):
    """產生彩虹顏色"""
    if pos < 0 or pos > 255:
        return (0, 0, 0)
    if pos < 85:
        return (255 - pos * 3, pos * 3, 0)
    elif pos < 170:
        pos -= 85
        return (0, 255 - pos * 3, pos * 3)
    else:
        pos -= 170
        return (pos * 3, 0, 255 - pos * 3)

def rainbow_cycle(step):
    for i in range(NUM_PIXELS):
        color = wheel((int(i * 256 / NUM_PIXELS) + step) & 255)
        np[i] = color
    np.write()

# === 加在檔案開頭區域（與其他 def 並列）===============================
last_update_id = None # 初始化全域變數

def init_current_state():
    """
    啟動時：
    1. 讀取未讀訊息（最多 1 筆）
    2. 將 last_update_id 設為最新，讓舊訊息全部作廢
    3. 可選：根據這最後一筆文字，設定 LED 和馬達初始狀態
    """
    global last_update_id, current_mode, sleep_phase, sleep_mark_ms, motor_running

    try:
        url = (f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
               f"?limit=1&timeout=0")
        resp = urequests.get(url)
        if resp.status_code == 200:
            results = resp.json().get("result", [])
            if results:
                msg            = results[-1]        # 最後一筆
                last_update_id = msg["update_id"]    # 直接捨棄以前的
                text = msg["message"].get("text", "").lower()
                print("⚡️ 開機讀到最後指令：", text)

                # ---- 初始狀態（可依需求刪改）----
                if   text == "on"      : current_mode = "on"
                elif text == "rainbow" : current_mode = "rainbow"
                elif text == "blue"    : current_mode = "blue"
                elif text == "sleep"   :
                    current_mode  = "sleep"
                    sleep_phase   = 0
                    sleep_mark_ms = ticks_ms()
                elif text == "run"     : motor_running = True # 讀到 run 則馬達啟動
                elif text == "stop"    : motor_running = False # 讀到 stop 則馬達停止
                else:                      current_mode = "off"
        resp.close()
    except Exception as e:
        print("Init Telegram 失敗：", e)

# --------------------------------------------------------------------------
# 非阻塞 Sleep 狀態機
def handle_sleep_mode():
    global sleep_phase, sleep_mark_ms, sleep_led_idx, current_mode
    now = ticks_ms()

    # Phase 0──先保持 5 秒
    if sleep_phase == 0 and ticks_diff(now, sleep_mark_ms) >= 5000:
        sleep_phase   = 1
        sleep_mark_ms = now
        sleep_led_idx = 0
        return

    # Phase 1──每秒關一顆
    if sleep_phase == 1 and ticks_diff(now, sleep_mark_ms) >= 1000:
        if sleep_led_idx < NUM_PIXELS:
            np[sleep_led_idx] = (0,0,0)
            np.write()
            sleep_led_idx += 1
            sleep_mark_ms = now         # 下一秒再來
        else:
            # 全部熄滅，復歸
            current_mode  = "off"
            sleep_phase   = None

# --------------------------------------------------------------------------
# 馬達運行狀態機 (非阻塞)
def handle_motor_control():
    global motor_running, motor_on_time_ms, motor_state_on
    now = ticks_ms()

    if motor_running:
        # 判斷馬達是否需要切換狀態 (轉動/停止)
        if motor_state_on: # 目前正在轉動 (高電位)
            if ticks_diff(now, motor_on_time_ms) >= 500: # 轉動 05秒
                motor_pwm.duty_u16(0) # 馬達停止 (佔空比 0)
                motor_state_on = False
                motor_on_time_ms = now # 重設時間標記
                print("馬達停止 (waiting 2s)")
        else: # 目前正在停止 (低電位)
            if ticks_diff(now, motor_on_time_ms) >= 2000: # 停止 2 秒
                motor_pwm.duty_u16(MOTOR_RUN_SPEED) # 馬達轉動
                motor_state_on = True
                motor_on_time_ms = now # 重設時間標記
                print(f"馬達轉動 (speed: {MOTOR_RUN_SPEED}, waiting 05s)")
    else:
        # 如果 motor_running 為 False，確保馬達停止
        if motor_pwm.duty_u16() != 0: # 避免重複設定，減少寫入
            motor_pwm.duty_u16(0)
            print("馬達已停止")
        motor_on_time_ms = now # 重設時間標記，以防下次啟動時立即切換狀態
        motor_state_on = True # 預設下次啟動從轉動開始

# --------------------------------------------------------------------------
# Telegram 輪詢（帶 offset）
def check_telegram():
    global current_mode, sleep_phase, sleep_mark_ms, last_update_id, motor_running
    try:
        base = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

        # 正確拼出查詢字串
        if last_update_id is None:       # 第一次輪詢
            url = f"{base}?timeout=0"
        else:
            url = f"{base}?offset={last_update_id+1}&timeout=0"

        resp = urequests.get(url)
        if resp.status_code == 200:
            for msg in resp.json().get("result", []):
                last_update_id = msg["update_id"]    # 記最新 id
                text = msg["message"].get("text", "").lower()
                print("📨", text)

                if text == "on":
                    current_mode = "on"
                elif text == "off":
                    current_mode = "off"
                elif text == "rainbow":
                    current_mode = "rainbow"
                elif text == "blue":
                    current_mode = "blue"
                elif text == "sleep":
                    current_mode  = "sleep"
                    sleep_phase   = 0
                    sleep_mark_ms = ticks_ms()
                elif text == "run": # 新增馬達運行指令
                    motor_running = True
                    print("接收到 'run' 指令，馬達即將運行。")
                elif text == "stop": # 新增馬達停止指令
                    motor_running = False
                    print("接收到 'stop' 指令，馬達將停止。")
                else: # 避免無效指令影響現有模式
                    pass # 不做任何改變，保持 current_mode 和 motor_running 不變
        else:
            print("HTTP 狀態碼：", resp.status_code)
        resp.close()

    except Exception as e:
        print("Telegram 連線錯誤：", e)

# --------------------------------------------------------------------------
# Main
if connect_wifi():
    # 預設馬達停止
    motor_pwm.duty_u16(0)
    motor_running = False
    motor_on_time_ms = ticks_ms() # 初始化時間戳
    motor_state_on = True # 預設下次啟動從轉動開始

    init_current_state() # 初始化狀態，會讀取最後一條指令來設定燈和馬達

    print("✨ 啟動主迴圈 …")
    step = 0
    while True:
        check_telegram() # 約每 ~0.1 s 檢查一次

        # NeoPixel 燈條模式控制
        if current_mode == "on":
            turn_on_pixels()
        elif current_mode == "off":
            turn_off_pixels()
        elif current_mode == "rainbow":
            rainbow_cycle(step)
            step = (step + 10) % 256
        elif current_mode == "blue":
            turn_on_pixels((0,0,255))
        elif current_mode == "sleep":
            handle_sleep_mode()

        # 馬達控制 (非阻塞)
        handle_motor_control()

        time.sleep(0.1) # 主迴圈最長只睡 0.1 s
