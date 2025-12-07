#!/usr/bin/python3

#basic parameters
before_s = 2.5 #start copying video N seconds before motion is triggered  
after_s = 2 #end copying video N seconds after motion has ended
min_copy_break_s = 5.9 #dont stop copying if next motion trigger sooner than this
ignore_start_s = 2 #seconds dont search for motion in beginning of input file
ignore_end_s = 2 #seconds dont search for motion at end of input file

#cmd window log
ffmpeg_loglevel = 31 #see https://ffmpeg.org/ffmpeg.html#Generic-options


#advanced filter parameters
step_len_f = 20 #compare every n frame
min_threshold_score = 0.0095 #default threshold. a score above indicates motion
test_duration_s = 7 #seek for a (motionless'ish) segment this long. threshold automatically adjusts up if necessary (and possible)
max_threshold_score = 0.04
segments_smooth = 0 #assign median score from n segments before and after to smooth out scores
segments_to_start = 2 #this many segments in a row above threshold triggers motion start
segments_to_end = 10 #this many segments in a row below threshold triggers motion end

import os
import random
import statistics        

#find all video files
OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/storage')
input_files = []
for root, dirs, files in os.walk(OUTPUT_DIR):
    for file in files:
        if file.lower().endswith(".mp4"):
            full_path = os.path.join(root, file)
            input_files.append(full_path)

#do this for each video file
for input_file in input_files:
    video_dir = os.path.dirname(input_file)
    video_name = os.path.splitext(os.path.basename(input_file))[0]
    txt_path = os.path.join(video_dir, video_name + ".txt")
    if os.path.exists(txt_path):
        print(f"⚠️  Ignore (already got the result): {txt_path}")
        continue

    print("Processing "+input_file)
    randint = random.randint(10000,99999)
    temp_file = "temp-scenescores-" + str(randint) + ".txt"
    if os.path.isfile(temp_file):
        os.remove(temp_file)
    command = "ffmpeg -loglevel "+str(ffmpeg_loglevel)+ " -i \""+input_file+"\" -vf select='not(mod(n\,"+str(step_len_f)+"))',select='gte(scene\,0)',metadata=print:file="+temp_file+" -an -f null -" 
    os.system(command)

    f = []
    f_pts = []
    f_pts_time = []
    f_scene_score = []
    pts=0
    pts_time=0
    scene_score=0
    with open(temp_file) as file:
        text = file.read()    
    i = -1
    while True:
        i = text.find('frame', i+1)
        if i == -1:
            break
        i = text.find(':', i) + 1
        j = text.find(' ', i)
        f.append(int(text[i:j]))
        i = text.find('pts', i+1)
        i = text.find(':', i) + 1
        j = text.find(' ', i)
        f_pts.append(int(text[i:j]))
        i = text.find('pts_time', i+1)
        i = text.find(':', i) + 1
        j = text.find('\n', i)
        f_pts_time.append(float(text[i:j]))
        i = text.find('scene_score', i+1)
        i = text.find('=', i) + 1
        j = text.find('\n', i)
        f_scene_score.append(float(text[i:j]))
    os.remove(temp_file)

    #give each frame a median score from +/- N frames
    f_median_score = []
    for x in f:
        f_median_score.append(statistics.median(f_scene_score[max(0,x-segments_smooth):x+segments_smooth+1]))

    #try to increase threshold if no motionless period found 
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

    #frame's score indicates CHANGE or not [0,1]
    f_change = []
    for x in f:
        if f_median_score[x] >= file_threshold_score:
            f_change.append(1)
        else:
            f_change.append(0)

    #frame's TRIGGER score [-1,0,+1]
    f_trigger = []
    x_max = len(f) - max(segments_to_start,segments_to_end)
    for x in f:
        if x >= x_max:
            f_trigger.append(0)
            continue
        run_above = 0
        for y in range(segments_to_start):
            if f_median_score[x+y] > file_threshold_score:
                run_above += 1
        if run_above == segments_to_start:
            f_trigger.append(1)
        else:
            run_above = 0
            for y in range(segments_to_end):
                if f_median_score[x+y] > file_threshold_score:
                    run_above += 1
            if run_above == 0:
                f_trigger.append(-1)
            else:
                f_trigger.append(0)

    #based on trigger scores, select "smart" COPY start and end points [-1,0,+1]
    f_copy = []
    is_copying = 0
    last_start_s = 0
    last_end_s = 0
    end_time_s = f_pts_time[len(f)-1]
    for x in f:
        f_copy.append(0)
        if f_pts_time[x] < ignore_start_s:
            continue
        if x >= x_max or f_pts_time[x] > end_time_s - ignore_end_s:
            if is_copying == 1:
                #copy_end_s.append(f_pts_time[x])
                f_copy[x] = -1
            continue

        #start copy?
        if is_copying == 0:
            if f_pts_time[x] > end_time_s - ignore_end_s: #near end, don't make new starting point
                continue
            if f_trigger[x] == 1:
                #copy_start_s.append(f_pts_time[x])
                f_copy[x] = 1
                last_start_s = f_pts_time[x]
                is_copying = 1
                continue

        #end copy?
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
                    #copy_end_s.append(f_pts_time[x])
                    f_copy[x] = -1
                    last_end_s = f_pts_time[x]
                    is_copying = 0
                continue

    #set copy start and end times
    copy_start_s = []
    copy_end_s = []
    for x in f:
        if f_copy[x] == 1:
            copy_start_s.append(f_pts_time[x])
        if f_copy[x] == -1:
            copy_end_s.append(f_pts_time[x])    

    #adjust start and end times
    for x in range(len(copy_start_s)):
        copy_start_s[x] = max(copy_start_s[x] - before_s, 0)
        copy_end_s[x] = min(copy_end_s[x] + after_s, end_time_s)

    if len(copy_start_s) > 0:
        with open(txt_path, "w", encoding="utf-8") as fi:        
            for x in range(len(copy_start_s)):
                fi.write(f"{(copy_start_s[x]):.2f} - {(copy_end_s[x]):.2f}\n")
    else:
        os.remove(input_file)
    