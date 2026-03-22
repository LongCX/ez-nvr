#!/usr/bin/python3

# basic parameters
before_s = 2.5          # start copying video N seconds before motion is triggered
after_s = 2             # end copying video N seconds after motion has ended
min_copy_break_s = 5.9  # don't stop copying if next motion trigger sooner than this
ignore_start_s = 2      # seconds don't search for motion in beginning of input file
ignore_end_s = 2        # seconds don't search for motion at end of input file

# advanced filter parameters
step_len_f = 20               # compare every n frame
min_threshold_score = 0.0095  # default threshold; a score above indicates motion
test_duration_s = 7           # seek for a (motionless'ish) segment this long
max_threshold_score = 0.04
segments_smooth = 0           # assign median score from n segments before/after
segments_to_start = 2         # this many segments in a row above threshold triggers motion start
segments_to_end = 10          # this many segments in a row below threshold triggers motion end

# output settings
DELETE_ORIGINAL_AFTER_EXTRACT = True  # delete source MP4 after motion clips are extracted

import os
import random
import statistics
import subprocess
from datetime import datetime, timedelta

# find all video files
OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/storage')
input_files = []
for root, dirs, files in os.walk(OUTPUT_DIR):
    for file in files:
        if file.lower().endswith(".mp4") and "_motion_" not in file:
            input_files.append(os.path.join(root, file))

# process each video file
for input_file in input_files:
    video_dir = os.path.dirname(input_file)
    video_name = os.path.splitext(os.path.basename(input_file))[0]

    # skip if motion clips already exist for this file
    existing_clips = [
        fn for fn in os.listdir(video_dir)
        if fn.startswith(video_name + "_motion_") and fn.endswith(".mp4")
    ]
    if existing_clips:
        print(f"Ignore (motion clips already exist): {video_name}")
        continue

    print(f"Processing {input_file}")

    # ── Scene detection ────────────────────────────────────────────────────────
    randint = random.randint(10000, 99999)
    temp_file = os.path.join(video_dir, f"temp-scenescores-{randint}.txt")

    # Build the -vf filter string — no shell involved so no escaping issues
    vf_filter = (
        f"select=not(mod(n\\,{step_len_f})),"
        f"select=gte(scene\\,0),"
        f"metadata=print:file={temp_file}"
    )

    cmd_scene = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", input_file,
        "-vf", vf_filter,
        "-an", "-f", "null", "/dev/null"
    ]

    result = subprocess.run(cmd_scene, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Scene detection failed:\n{result.stderr}")
        if os.path.isfile(temp_file):
            os.remove(temp_file)
        continue

    if not os.path.isfile(temp_file):
        print(f"Scene score file not created for {input_file}, skipping.")
        continue

    with open(temp_file) as fh:
        text = fh.read()
    os.remove(temp_file)

    if not text.strip():
        print(f"No scene data found in {input_file}, skipping.")
        continue

    # ── Parse scene score output ───────────────────────────────────────────────
    f = []
    f_pts_time = []
    f_scene_score = []

    i = -1
    while True:
        i = text.find('frame:', i + 1)
        if i == -1:
            break
        colon = text.find(':', i) + 1
        space = text.find(' ', colon)
        frame_idx = int(text[colon:space])

        pts_pos = text.find('pts_time:', i)
        colon2 = pts_pos + len('pts_time:')
        nl = text.find('\n', colon2)
        pts_time_val = float(text[colon2:nl])

        ss_pos = text.find('scene_score=', i)
        eq = ss_pos + len('scene_score=')
        nl2 = text.find('\n', eq)
        scene_score_val = float(text[eq:nl2])

        f.append(frame_idx)
        f_pts_time.append(pts_time_val)
        f_scene_score.append(scene_score_val)

        i = nl2

    if not f:
        print(f"Could not parse scene scores for {input_file}, skipping.")
        continue

    # ── Compute median scores ──────────────────────────────────────────────────
    n = len(f)
    f_median_score = [
        statistics.median(f_scene_score[max(0, i - segments_smooth): i + segments_smooth + 1])
        for i in range(n)
    ]

    # ── Auto-adjust threshold ──────────────────────────────────────────────────
    file_threshold_score = min_threshold_score
    while True:
        longest_motionless_s = 0
        last_change_s = 0
        run_s = 0
        for i in range(n):
            if f_median_score[i] < file_threshold_score:
                run_s = f_pts_time[i] - last_change_s
            else:
                if longest_motionless_s < run_s:
                    longest_motionless_s = run_s
                last_change_s = f_pts_time[i]
        if longest_motionless_s <= test_duration_s:
            file_threshold_score += min_threshold_score
            if file_threshold_score > max_threshold_score:
                file_threshold_score = min_threshold_score
                break
        else:
            break

    # ── Trigger detection ──────────────────────────────────────────────────────
    x_max = n - max(segments_to_start, segments_to_end)

    f_trigger = []
    for i in range(n):
        if i >= x_max:
            f_trigger.append(0)
            continue
        run_above = sum(
            1 for y in range(segments_to_start)
            if f_median_score[i + y] > file_threshold_score
        )
        if run_above == segments_to_start:
            f_trigger.append(1)
        else:
            run_above = sum(
                1 for y in range(segments_to_end)
                if f_median_score[i + y] > file_threshold_score
            )
            f_trigger.append(-1 if run_above == 0 else 0)

    # ── Copy segment selection ─────────────────────────────────────────────────
    f_copy = [0] * n
    is_copying = False
    end_time_s = f_pts_time[-1]

    for i in range(n):
        t = f_pts_time[i]

        if t < ignore_start_s:
            continue
        if i >= x_max or t > end_time_s - ignore_end_s:
            if is_copying:
                f_copy[i] = -1
                is_copying = False
            continue

        if not is_copying:
            if f_trigger[i] == 1:
                f_copy[i] = 1
                is_copying = True
        else:
            if f_trigger[i] == -1:
                can_end = True
                y = i + 1
                while y < x_max:
                    if f_trigger[y] == 1:
                        can_end = False
                        break
                    if f_pts_time[y] - t > min_copy_break_s:
                        break
                    y += 1
                if can_end:
                    f_copy[i] = -1
                    is_copying = False

    copy_start_s = [f_pts_time[i] for i in range(n) if f_copy[i] == 1]
    copy_end_s   = [f_pts_time[i] for i in range(n) if f_copy[i] == -1]

    # pad start/end
    copy_start_s = [max(s - before_s, 0)         for s in copy_start_s]
    copy_end_s   = [min(e + after_s, end_time_s) for e in copy_end_s]

    # ── Clip name helper ───────────────────────────────────────────────────────
    recording_start_dt = None
    try:
        recording_start_dt = datetime.strptime(video_name, "%Y-%m-%dT%H-%M-%S")
    except ValueError:
        pass  # fallback to offset seconds if filename format differs

    def make_clip_name(start_offset, end_offset):
        if recording_start_dt:
            s = (recording_start_dt + timedelta(seconds=start_offset)).strftime("%H-%M-%S")
            e = (recording_start_dt + timedelta(seconds=end_offset)).strftime("%H-%M-%S")
        else:
            s = f"{int(start_offset):05d}s"
            e = f"{int(end_offset):05d}s"
        return f"{video_name}_motion_{s}_to_{e}.mp4"

    # ── Extract clips ──────────────────────────────────────────────────────────
    if copy_start_s:
        extracted = []
        for idx, (start, end) in enumerate(zip(copy_start_s, copy_end_s), start=1):
            clip_name = make_clip_name(start, end)
            clip_path = os.path.join(video_dir, clip_name)

            cmd_cut = [
                "ffmpeg", "-hide_banner", "-y", "-loglevel", "error",
                "-ss", f"{start:.2f}",
                "-to", f"{end:.2f}",
                "-i", input_file,
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                clip_path
            ]
            res = subprocess.run(cmd_cut, capture_output=True, text=True)
            if res.returncode == 0:
                print(f"Clip {idx}: {clip_name}  ({end - start:.1f}s)")
                extracted.append(clip_path)
            else:
                print(f"Failed clip {idx}:\n{res.stderr}")

        if DELETE_ORIGINAL_AFTER_EXTRACT and extracted:
            try:
                os.remove(input_file)
                print(f"Deleted source: {input_file}")
            except Exception as e:
                print(f"Could not delete source {input_file}: {e}")
    else:
        try:
            os.remove(input_file)
            print(f"No motion detected, deleted: {input_file}")
        except Exception as e:
            print(f"Could not delete {input_file}: {e}")
