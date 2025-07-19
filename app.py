import os
import uuid
import threading
import time
from datetime import datetime
from flask import Flask, render_template, Response, request, send_from_directory, redirect, url_for, flash, jsonify, send_file, session
from ultralytics import YOLO
import cv2
import zipfile
import io
import tempfile
from twilio.rest import Client
from twilio.base.exceptions import TwilioException
import sqlite3
import re

app = Flask(__name__)
app.secret_key = 'replace-with-your-secret-key'
UPLOAD_FOLDER = 'static/outputs'
SCREENSHOT_FOLDER = 'static/screenshots'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SCREENSHOT_FOLDER, exist_ok=True)

MODEL_PATH = 'best.pt'
model = YOLO(MODEL_PATH)

# --- Twilio Configuration ---
try:
    from config import (
        TWILIO_ACCOUNT_SID, 
        TWILIO_AUTH_TOKEN, 
        TWILIO_PHONE_NUMBER, 
        ADMIN_PHONE_NUMBER, 
        CONFIDENCE_THRESHOLD,
        ALERT_COOLDOWN
    )
except ImportError:
    # Fallback values if config.py doesn't exist
    TWILIO_ACCOUNT_SID = 'your_account_sid_here'
    TWILIO_AUTH_TOKEN = 'your_auth_token_here'
    TWILIO_PHONE_NUMBER = 'your_twilio_phone_number_here'
    ADMIN_PHONE_NUMBER = 'admin_phone_number_here'
    CONFIDENCE_THRESHOLD = 0.7
    ALERT_COOLDOWN = 60

# Initialize Twilio client
try:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    TWILIO_ENABLED = True
except Exception as e:
    print(f"Twilio initialization failed: {e}")
    TWILIO_ENABLED = False

# --- Global frame buffers and threading ---
latest_frame = None
last_boxes = []  # List of (x1, y1, x2, y2, conf, label)
last_lock = threading.Lock()
camera_thread = None
yolo_thread = None
threads_running = False
last_alert_time = 0  # To prevent spam alerts
ALERT_COOLDOWN = 60  # Seconds between alerts
last_detection_time = 0  # Track last detection timestamp (seconds since epoch)

CAMERA_INDEX = 0
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
DETECTION_SKIP = 4  # Run YOLO every Nth frame for speed

# --- Detection record (in-memory for now) ---
detection_history = []  # List of dicts: {filename, timestamp}

PROGRESS_FOLDER = os.path.join(tempfile.gettempdir(), 'gun_detection_progress')
os.makedirs(PROGRESS_FOLDER, exist_ok=True)

# --- User Database Initialization ---
DB_PATH = 'users.db'
def init_user_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT NOT NULL
    )''')
    # Predefined users
    users = [(f'user{i}', f'password{i}') for i in range(1, 11)]
    for username, password in users:
        c.execute('INSERT OR IGNORE INTO users (username, password) VALUES (?, ?)', (username, password))
    conn.commit()
    conn.close()

init_user_db()

def send_sms_alert(confidence, weapon_type, timestamp):
    """Send SMS alert when weapon is detected with high confidence"""
    global last_alert_time
    
    current_time = time.time()
    if current_time - last_alert_time < ALERT_COOLDOWN:
        return  # Still in cooldown period
    
    if not TWILIO_ENABLED:
        print(f"SMS Alert (Twilio disabled): Weapon detected with {confidence:.2f} confidence at {timestamp}")
        return
    
    try:
        message_body = f"🚨 WEAPON DETECTED! 🚨\n\nType: {weapon_type}\nConfidence: {confidence:.2f}\nTime: {timestamp}\n\nLocation: Gun Detection System"
        
        message = twilio_client.messages.create(
            body=message_body,
            from_=TWILIO_PHONE_NUMBER,
            to=ADMIN_PHONE_NUMBER
        )
        
        last_alert_time = current_time
        print(f"SMS Alert sent successfully: {message.sid}")
        
    except TwilioException as e:
        print(f"Failed to send SMS alert: {e}")
    except Exception as e:
        print(f"Unexpected error sending SMS: {e}")

# --- Multi-camera support ---
camera_threads = {}
frame_buffers = {}
thread_locks = {}
thread_running = {}
last_detection_times = {}  # cam_key: timestamp
screenshot_cooldowns = {} # cam_key: timestamp of last screenshot

# Helper to get a unique key for each camera (by index or url)
def get_camera_key(cam_idx=None, cam_url=None):
    if cam_url:
        return f"url_{cam_url}"
    return f"idx_{cam_idx if cam_idx is not None else 0}"

# Multi-camera capture and detection

def camera_capture_multi(cam_key, cam_idx=None, cam_url=None):
    cap = cv2.VideoCapture(cam_url if cam_url else cam_idx)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, 30)
    while thread_running.get(cam_key, False) and cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            continue
        with thread_locks[cam_key]:
            frame_buffers[cam_key]['latest_frame'] = frame.copy()
        time.sleep(0.01)
    cap.release()


def yolo_inference_multi(cam_key):
    frame_count = 0
    while thread_running.get(cam_key, False):
        with thread_locks[cam_key]:
            frame = frame_buffers[cam_key]['latest_frame'].copy() if frame_buffers[cam_key]['latest_frame'] is not None else None
        if frame is not None and frame_count % DETECTION_SKIP == 0:
            results = model(frame)
            boxes = []
            for box in results[0].boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0])
                label = int(box.cls[0])
                if conf >= CONFIDENCE_THRESHOLD:
                    boxes.append((int(x1), int(y1), int(x2), int(y2), conf, label))
            # Save boxes for overlay
            with thread_locks[cam_key]:
                frame_buffers[cam_key]['last_boxes'] = boxes
            # If detection found, update last_detection_times
            if len(boxes) > 0:
                last_detection_times[cam_key] = time.time()
                # --- Send SMS alert for first detected box ---
                conf, label = boxes[0][4], boxes[0][5]
                weapon_type = model.names[label] if hasattr(model, 'names') else str(label)
                timestamp_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                send_sms_alert(conf, weapon_type, timestamp_str)
                # --- Screenshot logic with cooldown ---
                now = time.time()
                cooldown = 10  # seconds
                last_shot = screenshot_cooldowns.get(cam_key, 0)
                if now - last_shot >= cooldown:
                    # Save screenshot with bounding boxes
                    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f'screenshot_{cam_key}_{timestamp_str}.jpg'
                    filepath = os.path.join(SCREENSHOT_FOLDER, filename)
                    annotated_frame = draw_boxes(frame.copy(), boxes)
                    cv2.imwrite(filepath, annotated_frame)
                    screenshot_cooldowns[cam_key] = now
        frame_count += 1
        time.sleep(0.001)


def start_camera_threads(cam_key, cam_idx=None, cam_url=None):
    if thread_running.get(cam_key, False):
        return
    thread_running[cam_key] = True
    frame_buffers[cam_key] = {'latest_frame': None, 'last_boxes': []}
    thread_locks[cam_key] = threading.Lock()
    camera_threads[cam_key] = [
        threading.Thread(target=camera_capture_multi, args=(cam_key, cam_idx, cam_url), daemon=True),
        threading.Thread(target=yolo_inference_multi, args=(cam_key,), daemon=True)
    ]
    for t in camera_threads[cam_key]:
        t.start()


def stop_camera_threads(cam_key):
    thread_running[cam_key] = False
    time.sleep(0.2)
    # Clean up all resources for this camera
    if cam_key in frame_buffers:
        del frame_buffers[cam_key]
    if cam_key in camera_threads:
        del camera_threads[cam_key]
    if cam_key in thread_locks:
        del thread_locks[cam_key]
    if cam_key in last_detection_times:
        del last_detection_times[cam_key]
    if cam_key in screenshot_cooldowns:
        del screenshot_cooldowns[cam_key]


def draw_boxes(frame, boxes):
    names = model.names if hasattr(model, 'names') else {0: 'Weapon'}
    for (x1, y1, x2, y2, conf, label) in boxes:
        color = (0, 0, 255)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label_text = f"{names.get(label, str(label))}: {conf:.2f}"
        cv2.putText(frame, label_text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    return frame


def gen_frames_multi(cam_key, cam_idx=None, cam_url=None):
    start_camera_threads(cam_key, cam_idx, cam_url)
    while thread_running.get(cam_key, False):
        with thread_locks[cam_key]:
            frame = frame_buffers[cam_key]['latest_frame'].copy() if frame_buffers[cam_key]['latest_frame'] is not None else None
            boxes = list(frame_buffers[cam_key]['last_boxes'])
        if frame is not None:
            frame = draw_boxes(frame, boxes)
            ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.01)

# --- Login Required Decorator ---
from functools import wraps

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Login Route ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE username=? AND password=?', (username, password))
        user = c.fetchone()
        conn.close()
        if user:
            session['username'] = username
            flash('Login successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'danger')
    return render_template('login.html')

# --- Logout Route ---
@app.route('/logout')
@login_required
def logout():
    session.pop('username', None)
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

# --- Password Change Route ---
@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        username = session['username']
        # Password requirements
        pw_valid = (
            len(new_password) >= 10 and
            re.search(r'[A-Z]', new_password) and
            re.search(r'[a-z]', new_password) and
            re.search(r'\d', new_password) and
            re.search(r'[^A-Za-z0-9]', new_password)
        )
        if not pw_valid:
            flash('Password must be at least 10 characters and include uppercase, lowercase, digit, and special character.', 'danger')
            return render_template('change_password.html')
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT password FROM users WHERE username=?', (username,))
        user = c.fetchone()
        if user and user[0] == current_password:
            c.execute('UPDATE users SET password=? WHERE username=?', (new_password, username))
            conn.commit()
            flash('Password changed successfully.', 'success')
        else:
            flash('Current password is incorrect.', 'danger')
        conn.close()
    return render_template('change_password.html')

# --- Protect existing routes ---
@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/video_feed')
@login_required
def video_feed():
    cam_idx = request.args.get('cam', default=None, type=int)
    cam_url = request.args.get('url', default=None, type=str)
    cam_key = get_camera_key(cam_idx, cam_url)
    return Response(gen_frames_multi(cam_key, cam_idx, cam_url),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/stop_video')
@login_required
def stop_video():
    cam_idx = request.args.get('cam', default=None, type=int)
    cam_url = request.args.get('url', default=None, type=str)
    cam_key = get_camera_key(cam_idx, cam_url)
    stop_camera_threads(cam_key)
    return '', 204

@app.route('/upload_video', methods=['POST'])
@login_required
def upload_video():
    if 'video' not in request.files or request.files['video'].filename == '':
        flash('No video selected.')
        return redirect(url_for('index'))
    vid = request.files['video']
    job_id = uuid.uuid4().hex
    # Save original
    filename = f"{job_id}_{vid.filename}"
    in_path = os.path.join(UPLOAD_FOLDER, filename)
    vid.save(in_path)
    out_filename = f"processed_{filename}"
    out_path = os.path.join(UPLOAD_FOLDER, out_filename)
    cap = cv2.VideoCapture(in_path)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(out_path, fourcc, fps, (width, height))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    processed_frames = 0
    progress_path = os.path.join(PROGRESS_FOLDER, f'progress_{job_id}.txt')
    
    # Track if we've sent an alert for this video
    alert_sent = False
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        res = model(frame)
        
        # Filter boxes for high-confidence only
        high_conf_boxes = []
        names = model.names if hasattr(model, 'names') else {0: 'Weapon'}
        for box in res[0].boxes:
            conf = float(box.conf[0])
            if conf >= CONFIDENCE_THRESHOLD:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                label = int(box.cls[0])
                high_conf_boxes.append((int(x1), int(y1), int(x2), int(y2), conf, label))
        annotated = frame.copy()
        for (x1, y1, x2, y2, conf, label) in high_conf_boxes:
            color = (0, 0, 255)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            label_text = f"{names.get(label, str(label))}: {conf:.2f}"
            cv2.putText(annotated, label_text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        writer.write(annotated)
        processed_frames += 1
        percent = int((processed_frames / total_frames) * 100)
        with open(progress_path, 'w') as f:
            f.write(str(percent))
    cap.release()
    writer.release()
    # Mark as 100% and remove progress file after a short delay
    with open(progress_path, 'w') as f:
        f.write('100')
    time.sleep(0.5)
    try:
        os.remove(progress_path)
    except Exception:
        pass
    # If AJAX, return JSON with job_id
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'job_id': job_id, 'success': True})
    return redirect(url_for('download_file', filename=out_filename))

@app.route('/api/video_progress')
@login_required
def video_progress():
    job_id = request.args.get('job_id')
    if not job_id:
        return jsonify({'percent': 0})
    progress_path = os.path.join(PROGRESS_FOLDER, f'progress_{job_id}.txt')
    if not os.path.exists(progress_path):
        return jsonify({'percent': 100})
    try:
        with open(progress_path, 'r') as f:
            percent = int(f.read().strip())
    except Exception:
        percent = 0
    return jsonify({'percent': percent})

@app.route('/download/<filename>')
@login_required
def download_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

@app.route('/api/get_screenshots')
@login_required
def get_screenshots():
    # List all screenshots in folder, newest first
    files = []
    for fname in os.listdir(SCREENSHOT_FOLDER):
        if fname.lower().endswith('.jpg'):
            fpath = os.path.join(SCREENSHOT_FOLDER, fname)
            mtime = os.path.getmtime(fpath)
            files.append({
                'filename': fname,
                'timestamp': datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S'),
                'url': f'/static/screenshots/{fname}'
            })
    files.sort(key=lambda x: x['timestamp'], reverse=True)
    return jsonify(files)

@app.route('/history')
@login_required
def history():
    return render_template('history.html')

@app.route('/api/download_all_screenshots')
@login_required
def download_all_screenshots():
    # Create a zip in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w') as zf:
        for fname in os.listdir(SCREENSHOT_FOLDER):
            if fname.lower().endswith('.jpg'):
                fpath = os.path.join(SCREENSHOT_FOLDER, fname)
                zf.write(fpath, arcname=fname)
    zip_buffer.seek(0)
    return send_file(zip_buffer, mimetype='application/zip', as_attachment=True, download_name='all_screenshots.zip')

@app.route('/api/trigger_highlight', methods=['GET'])
def trigger_highlight():
    # Find all cameras with detection in last 10 seconds
    now = time.time()
    cameras = []
    for cam_key, t in last_detection_times.items():
        if now - t < 10:
            if cam_key.startswith('idx_'):
                try:
                    cam_idx = int(cam_key.split('_')[1])
                    cameras.append(cam_idx + 1)  # 1-based for frontend
                except:
                    pass
            # For url cameras, you can add logic if needed
    return jsonify({'cameras': cameras})

if __name__ == '__main__':
    app.run(debug=True)
