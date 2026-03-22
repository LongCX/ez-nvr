#!/usr/bin/python3

# basic parameters
before_s = 2.5       # start copying video N seconds before motion is triggered
after_s = 2          # end copying video N seconds after motion has ended
min_copy_break_s = 5.9  # don't stop copying if next motion trigger sooner than this
ignore_start_s = 2   # seconds don't search for motion in beginning of input file
ignore_end_s = 2     # seconds don't search for motion at end of input file

# cmd window log
ffmpeg_loglevel = 31  # see https://ffmpeg.org/ffmpeg.html#Generic-options

# advanced filter parameters
step_len_f = 20           # compare every n frame
min_threshold_score = 0.0095   # default threshold. a score above indicates motion
test_duration_s = 7       # seek for a (motionless'ish) segment this long
max_threshold_score = 0.04
segments_smooth = 0       # assign median score from n segments before/after to smooth
segments_to_start = 2     # this many segments in a row above threshold triggers motion start
segments_to_end = 10      # this many segments in a row below threshold triggers motion end

# output settings
DELETE_ORIGINAL_AFTER_EXTRACT = True  # delete source MP4 after motion clips are extracted

import os
import random
import statistics
import subprocess
from datetime import datetime, timedelta
from datetime import datetime, timedelta

# find all video files
OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/storage')
input_files = []
for root, dirs, files in os.walk(OUTPUT_DIR):
    for file in files:
        if file.lower().endswith(".mp4"):
            # skip files that look like motion clips already (e.g. _motion_001.mp4)
            if "_motion_" not in file:
                full_path = os.path.join(root, file)
                input_files.append(full_path)

# do this for each video file
for input_file in input_files:
    video_dir = os.path.dirname(input_file)
    video_name = os.path.splitext(os.path.basename(input_file))[0]

    # check if motion clips already exist for this file → skip
    existing_clips = [
        f for f in os.listdir(video_dir)
        if f.startswith(video_name + "_motion_") and f.endswith(".mp4")
    ]
    if existing_clips:
        print(f"⚠️  Ignore (motion clips already exist): {video_name}")
        continue

    print(f"Processing {input_file}")
    randint = random.randint(10000, 99999)
    temp_file = "temp-scenescores-" + str(randint) + ".txt"
    if os.path.isfile(temp_file):
        os.remove(temp_file)

    command = (
        f"ffmpeg -loglevel {ffmpeg_loglevel}"
        f" -i \"{input_file}\""
        f" -vf select='not(mod(n\\,{step_len_f}))',select='gte(scene\\,0)',"
        f"metadata=print:file={temp_file}"
        f" -an -f null -"
    )
    os.system(command)

    f = []
    f_pts = []
    f_pts_time = []
    f_scene_score = []
    with open(temp_file) as file:
        text = file.read()
    i = -1
    while True:
        i = text.find('frame', i + 1)
        if i == -1:
            break
        i = text.find(':', i) + 1
        j = text.find(' ', i)
        f.append(int(text[i:j]))
        i = text.find('pts', i + 1)
        i = text.find(':', i) + 1
        j = text.find(' ', i)
        f_pts.append(int(text[i:j]))
        i = text.find('pts_time', i + 1)
        i = text.find(':', i) + 1
        j = text.find('\n', i)
        f_pts_time.append(float(text[i:j]))
        i = text.find('scene_score', i + 1)
        i = text.find('=', i) + 1
        j = text.find('\n', i)
        f_scene_score.append(float(text[i:j]))
    os.remove(temp_file)

    # give each frame a median score from +/- N frames
    f_median_score = []
    for x in f:
        f_median_score.append(
            statistics.median(f_scene_score[max(0, x - segments_smooth):x + segments_smooth + 1])
        )

    # try to increase threshold if no motionless period found
    file_threshold_score = min_threshold_score
    while True:
        longest_motionless_s = 0
        last_change_s = 0
        run_s = 0
        for x in f:
            if f_median_score[x] < file_threshold_score:
                run_s = f_pts_time[x] - last_change_s
            else:
                if longest_motionless_s < run_s:
                    longest_motionless_s = run_s
                last_change_s = f_pts_time[x]
        if longest_motionless_s <= test_duration_s:
            file_threshold_score += min_threshold_score
            if file_threshold_score > max_threshold_score:
                file_threshold_score = min_threshold_score
                break
        else:
            break

    # frame's score indicates CHANGE or not [0,1]
    f_change = []
    for x in f:
        f_change.append(1 if f_median_score[x] >= file_threshold_score else 0)

    # frame's TRIGGER score [-1, 0, +1]
    f_trigger = []
    x_max = len(f) - max(segments_to_start, segments_to_end)
    for x in f:
        if x >= x_max:
            f_trigger.append(0)
            continue
        run_above = sum(1 for y in range(segments_to_start) if f_median_score[x + y] > file_threshold_score)
        if run_above == segments_to_start:
            f_trigger.append(1)
        else:
            run_above = sum(1 for y in range(segments_to_end) if f_median_score[x + y] > file_threshold_score)
            f_trigger.append(-1 if run_above == 0 else 0)

    # based on trigger scores, select "smart" COPY start and end points
    f_copy = []
    is_copying = 0
    end_time_s = f_pts_time[len(f) - 1]
    for x in f:
        f_copy.append(0)
        if f_pts_time[x] < ignore_start_s:
            continue
        if x >= x_max or f_pts_time[x] > end_time_s - ignore_end_s:
            if is_copying == 1:
                f_copy[x] = -1
            continue

        if is_copying == 0:
            if f_pts_time[x] > end_time_s - ignore_end_s:
                continue
            if f_trigger[x] == 1:
                f_copy[x] = 1
                is_copying = 1
                continue

        if is_copying == 1:
            if f_trigger[x] == -1:
                can_end = 1
                y = x
                while True:
                    y += 1
                    if y >= x_max:
                        break
                    if f_trigger[y] == 1:
                        can_end = 0
                        break
                    if f_pts_time[y] - f_pts_time[x] > min_copy_break_s:
                        break
                if can_end == 1:
                    f_copy[x] = -1
                    is_copying = 0
                continue

    # set copy start and end times
    copy_start_s = []
    copy_end_s = []
    for x in f:
        if f_copy[x] == 1:
            copy_start_s.append(f_pts_time[x])
        if f_copy[x] == -1:
            copy_end_s.append(f_pts_time[x])

    # adjust start and end times
    for x in range(len(copy_start_s)):
        copy_start_s[x] = max(copy_start_s[x] - before_s, 0)
        copy_end_s[x] = min(copy_end_s[x] + after_s, end_time_s)

    # ─────────────────────────────────────────────────────────────
    # EXTRACT MOTION SEGMENTS AS VIDEO CLIPS (replaces txt output)
    # ─────────────────────────────────────────────────────────────

    # Parse recording start time from filename: 2025-01-15T14-30-00
    recording_start_dt = None
    try:
        recording_start_dt = datetime.strptime(video_name, "%Y-%m-%dT%H-%M-%S")
    except ValueError:
        pass  # fallback: dùng offset giây nếu tên file không đúng định dạng

    def make_clip_name(start_offset, end_offset):
        if recording_start_dt:
            t_start = recording_start_dt + timedelta(seconds=start_offset)
            t_end   = recording_start_dt + timedelta(seconds=end_offset)
            s = t_start.strftime("%H-%M-%S")
            e = t_end.strftime("%H-%M-%S")
        else:
            s = f"{int(start_offset):05d}s"
            e = f"{int(end_offset):05d}s"
        return f"{video_name}_motion_{s}_to_{e}.mp4"

    if len(copy_start_s) > 0:
        extracted = []
        for idx, (start, end) in enumerate(zip(copy_start_s, copy_end_s), start=1):
            clip_name = make_clip_name(start, end)
            clip_path = os.path.join(video_dir, clip_name)

            cmd = [
                "ffmpeg", "-hide_banner", "-y",
                "-loglevel", "error",
                "-ss", f"{start:.2f}",
                "-to", f"{end:.2f}",
                "-i", input_file,
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                clip_path
            ]

            result = subprocess.run(cmd)
            if result.returncode == 0:
                duration = end - start
                print(f"✅ Clip {idx}: {clip_name}  ({duration:.1f}s)")
                extracted.append(clip_path)
            else:
                print(f"❌ Failed to extract clip {idx} from {input_file}")

        # optionally delete the source file after all clips are extracted
        if DELETE_ORIGINAL_AFTER_EXTRACT and extracted:
            try:
                os.remove(input_file)
                print(f"🗑️  Deleted source: {input_file}")
            except Exception as e:
                print(f"⚠️  Could not delete source {input_file}: {e}")
    else:
        # no motion detected → delete the original (same behaviour as before)
        try:
            os.remove(input_file)
            print(f"🗑️  No motion detected, deleted: {input_file}")
        except Exception as e:
            print(f"⚠️  Could not delete {input_file}: {e}")
