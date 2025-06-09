import network, urequests, time, neopixel
from machine import Pin
from time import ticks_ms, ticks_diff          # 非阻塞用
# --------------------------------------------------------------------------
# 環境設定
SSID, PASSWORD = 'C3PO-phone', 'iamthewifi'
BOT_TOKEN      = '7706866961:AAFpD_PlJpL4zLruB1x-3G92VoG70qPPw0c'
CHAT_ID        = '7643071691'

NEOPIXEL_PIN = 26
NUM_PIXELS = 16
np = neopixel.NeoPixel(Pin(NEOPIXEL_PIN), NUM_PIXELS)
# --------------------------------------------------------------------------
# 狀態變數
current_mode      = "off"

# ─── Sleep 模式狀態機 ───────────────────────────────────────────────────
sleep_phase       = None      # None=未啟動, 0=等待5s, 1=逐顆熄燈
sleep_mark_ms     = 0         # 時戳基準
sleep_led_idx     = 0         # 下次要關的 LED index
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

def init_current_state():
    """
    啟動時：
    1. 讀取未讀訊息（最多 1 筆）
    2. 將 last_update_id 設為最新，讓舊訊息全部作廢
    3. 可選：根據這最後一筆文字，設定 LED 初始狀態
    """
    global last_update_id, current_mode, sleep_phase, sleep_mark_ms

    try:
        url = (f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
               f"?limit=1&timeout=0")
        resp = urequests.get(url)
        if resp.status_code == 200:
            results = resp.json().get("result", [])
            if results:
                msg            = results[-1]          # 最後一筆
                last_update_id = msg["update_id"]     # 直接捨棄以前的
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
                else:                   current_mode = "off"
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
            sleep_mark_ms = now        # 下一秒再來
        else:
            # 全部熄滅，復歸
            current_mode  = "off"
            sleep_phase   = None
# --------------------------------------------------------------------------
# Telegram 輪詢（帶 offset）
last_update_id = None   # 全域

def check_telegram():
    global current_mode, sleep_phase, sleep_mark_ms, last_update_id
    try:
        base = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

        # 正確拼出查詢字串
        if last_update_id is None:        # 第一次輪詢
            url = f"{base}?timeout=0"
        else:
            url = f"{base}?offset={last_update_id+1}&timeout=0"

        resp = urequests.get(url)
        if resp.status_code == 200:
            for msg in resp.json().get("result", []):
                last_update_id = msg["update_id"]   # 記最新 id
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
        else:
            print("HTTP 狀態碼：", resp.status_code)
        resp.close()

    except Exception as e:
        print("Telegram 連線錯誤：", e)

# --------------------------------------------------------------------------
# Main
if connect_wifi():
    init_current_state()
    print("✨ 啟動主迴圈 …")
    step = 0
    while True:
        check_telegram()                      # 約每 ~0.1 s 檢查一次
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
        time.sleep(0.1)                       # 主迴圈最長只睡 0.1 s
