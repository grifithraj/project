import os
import io
import time
import requests
from fastapi import FastAPI, WebSocket, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from ultralytics import YOLO
from PIL import Image

app = FastAPI(title="Sentinel Cloud Hub")
model = YOLO("yolov8n-oiv7.pt")

# Sentinel Logic Rules
ALERT_TARGETS = ['person', 'elephant', 'tiger', 'man', 'woman'] 
IGNORE_TARGETS = ['cat', 'dog']

# Telegram Configuration (FILL THESE IN)
TELEGRAM_BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"

# Global State
active_phone_connection: WebSocket = None
latest_event_status = "System Armed. Waiting for events..."
latest_event_time = "N/A"

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

def send_telegram_alert(message, image_path=None):
    """Fires push notifications to your phone via Telegram."""
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                      data={'chat_id': TELEGRAM_CHAT_ID, 'text': message})
        if image_path:
            with open(image_path, 'rb') as photo:
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto", 
                              data={'chat_id': TELEGRAM_CHAT_ID}, files={'photo': photo})
    except Exception as e:
        print(f"Telegram failed: {e}")

# ==========================================
# 1. THE PHONE CAMERA TUNNEL
# ==========================================
html_content = """
<!DOCTYPE html>
<html><head><title>Sentinel Lens</title></head>
<body style="background: black; color: white; text-align: center;">
    <h2>Sentinel Lens Active</h2><p>Waiting for trigger...</p>
    <video id="video" width="100%" autoplay playsinline></video>
    <canvas id="canvas" width="640" height="480" style="display:none;"></canvas>
    <script>
        const video = document.getElementById('video');
        const canvas = document.getElementById('canvas');
        navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } })
            .then(stream => { video.srcObject = stream; });

        const ws = new WebSocket((window.location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + window.location.host + '/ws');
        ws.onmessage = (event) => {
            if (event.data === "CAPTURE") {
                canvas.getContext('2d').drawImage(video, 0, 0, 640, 480);
                canvas.toBlob(blob => {
                    const fd = new FormData(); fd.append("file", blob, "shot.jpg");
                    fetch('/process', { method: "POST", body: fd });
                }, 'image/jpeg', 0.8);
            }
        };
    </script>
</body></html>
"""

@app.get("/camera")
async def phone_camera_page(): return HTMLResponse(content=html_content)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global active_phone_connection
    await websocket.accept()
    active_phone_connection = websocket
    try:
        while True: await websocket.receive_text()
    except:
        active_phone_connection = None

# ==========================================
# 2. ESP32 ENDPOINTS (CAMERA & SENSORS)
# ==========================================
@app.get("/trigger")
async def trigger_from_esp32():
    if active_phone_connection:
        await active_phone_connection.send_text("CAPTURE")
        return {"status": "SUCCESS"}
    return {"status": "ERROR"}

@app.get("/sensor")
async def sensor_alert(type: str, value: float, alert_msg: str):
    global latest_event_status, latest_event_time
    latest_event_time = time.strftime("%Y-%m-%d %H:%M:%S")
    
    formatted_msg = f"⚠️ SENSOR TRIGGER: {type.upper()}\nDetails: {alert_msg}\nReading: {value}"
    latest_event_status = formatted_msg
    
    print(formatted_msg)
    send_telegram_alert(formatted_msg)
    return {"status": "SUCCESS"}

# ==========================================
# 3. AI PROCESSING
# ==========================================
@app.post("/process")
async def process_image(file: UploadFile = File(...)):
    global latest_event_status, latest_event_time
    image_bytes = await file.read()
    image = Image.open(io.BytesIO(image_bytes))
    
    results = model(image, conf=0.15)
    result = results[0] 
    
    image_path = "static/latest_alert.jpg"
    Image.fromarray(result.plot()[..., ::-1]).save(image_path)
    latest_event_time = time.strftime("%Y-%m-%d %H:%M:%S")

    detected_objects = [model.names[int(box.cls[0])].lower() for box in result.boxes]

    for obj in detected_objects:
        if obj in ALERT_TARGETS:
            msg = f"🔴 INTRUDER ALERT: {obj.upper()} DETECTED!"
            latest_event_status = msg
            send_telegram_alert(msg, image_path)
            return {"status": "ALERT"}
            
    latest_event_status = "🟢 CLEAR: Motion, but nothing of interest."
    return {"status": "CLEAR"}

# ==========================================
# 4. COMMAND DASHBOARD
# ==========================================
@app.get("/dashboard")
async def command_center():
    return HTMLResponse(content=f"""
    <html><head><meta http-equiv="refresh" content="5"><style>body{{background:#121212;color:white;text-align:center;font-family:sans-serif;}}img{{max-width:100%;border-radius:10px;margin-top:20px;}}</style></head>
    <body><h1>🛡️ Sentinel Hub</h1><h2 style="background:#333;padding:10px;border-radius:5px;">{latest_event_status}</h2><p>{latest_event_time}</p>
    <img src="/static/latest_alert.jpg?{time.time()}" onerror="this.style.display='none'"></body></html>
    """)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))