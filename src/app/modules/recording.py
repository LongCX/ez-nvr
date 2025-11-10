import os
import time
import cv2
import datetime
import subprocess
from utils.filesystem import get_output_path, get_raw_path, mkdir_dest, mkdir_raw
from utils.logger import log_info, log_error
from utils.common import stop_flags, stop_flags_lock

# ============================
# CONFIG CHO MOTION
# ============================
MIN_AREA = 800
NO_MOTION_TIMEOUT = 5     # hết chuyển động bao nhiêu giây thì dừng FFmpeg


def start_recording(cam_config, stop_flag):
    cam_name = cam_config['camera_name']
    cam_ip = cam_config['camera_ip']
    rtsp_url = cam_config['camera_rtsp']
    codec = cam_config['camera_codec']

    output_path = get_output_path(cam_name)
    raw_path = get_raw_path(cam_name)
    netcheck = 0

    mkdir_dest(output_path)
    mkdir_raw(raw_path)

    # ============================
    # CHECK CONNECTIVITY
    # ============================
    while True:
        if stop_flag.is_set():
            break

        response = os.system(f"ping -c 1 {cam_ip} > /dev/null 2>&1")
        if response == 0:
            log_info(f"NVR: Connection established to {cam_name} at {cam_ip}")
            break
        else:
            netcheck += 1
            if netcheck == 1:
                log_error(f"NVR: No connection to {cam_name} at {cam_ip}")
            if netcheck == 5:
                log_info(f"NVR: Waiting for connection to {cam_name} at {cam_ip}")
            if netcheck == 99:
                netcheck = 4
        time.sleep(60)

    # ============================
    # OPEN RTSP STREAM FOR MOTION DETECTION
    # ============================
    cap = cv2.VideoCapture(rtsp_url)
    if not cap.isOpened():
        log_error(f"NVR: Cannot open RTSP for {cam_name}")
        return

    bg = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=25, detectShadows=True)

    ffmpeg_process = None
    last_motion = 0
    recording = False

    log_info(f"NVR: Motion detection started for {cam_name}")

    # ============================
    # MAIN LOOP
    # ============================
    while not stop_flag.is_set():

        ret, frame = cap.read()
        if not ret:
            log_error(f"NVR: Lost RTSP stream for {cam_name}, reconnecting...")
            time.sleep(3)
            cap.release()
            cap = cv2.VideoCapture(rtsp_url)
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mask = bg.apply(gray)
        thresh = cv2.threshold(mask, 250, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        motion = any(cv2.contourArea(c) > MIN_AREA for c in contours)

        # ============================
        # CÓ CHUYỂN ĐỘNG → BẮT ĐẦU GHI
        # ============================
        if motion:
            last_motion = time.time()
            if not recording:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
                output_file = f"{raw_path}/{timestamp}.mkv"

                ffmpeg_cmd = (
                    f"ffmpeg -hide_banner -y -loglevel error "
                    f"-rtsp_transport tcp -use_wallclock_as_timestamps 1 "
                    f"-i \"{rtsp_url}\" "
                    f"-c \"{codec}\" "
                    f"\"{output_file}\""
                )

                log_info(f"NVR: Motion detected → Start recording: {output_file}")
                ffmpeg_process = subprocess.Popen(
                    ffmpeg_cmd, shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                recording = True

        # ============================
        # HẾT CHUYỂN ĐỘNG → STOP FFMPEG
        # ============================
        if recording and (time.time() - last_motion > NO_MOTION_TIMEOUT):
            log_info(f"NVR: No motion → Stop recording for {cam_name}")
            ffmpeg_process.terminate()
            recording = False
            ffmpeg_process = None

    # ============================
    # STOP FLAG
    # ============================
    if ffmpeg_process:
        ffmpeg_process.terminate()

    cap.release()
    log_info(f"NVR: Stop camera {cam_name}")
    return ffmpeg_process


def stop_recording(cam_name):
    with stop_flags_lock:
        if cam_name in stop_flags:
            stop_flags[cam_name].set()
        else:
            log_error(f"NVR: Camera {cam_name} not found in stop_flags.")
