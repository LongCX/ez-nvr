import os
import re
import subprocess
from pathlib import Path

# ==============================
# CONFIGURATION
# ==============================
# Root directory containing .mkv files (and subfolders)
WATCH_DIR = os.environ.get('OUTPUT_DIR', '/storage')

# Regex pattern to match date-like folder names (e.g., 2025-11-07)
DATE_FOLDER_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ==============================
# FUNCTION: Validate folder
# ==============================
def is_valid_date_folder(path: Path) -> bool:
    """
    Check if the given path (or any of its parents) matches YYYY-MM-DD format.
    Returns True if the file is inside such a directory.
    """
    for parent in path.parents:
        if DATE_FOLDER_PATTERN.match(parent.name):
            return True
    return False


# ==============================
# FUNCTION: Convert MKV → MP4
# ==============================
def convert_file(mkv_path: Path):
    """
    Convert a single MKV file to MP4 using ffmpeg with stream copy (-c copy).
    If conversion succeeds, delete the original MKV file.
    """
    mp4_path = mkv_path.with_suffix(".mp4")

    # Skip if MP4 file already exists
    if mp4_path.exists():
        print(f"[SKIP] {mp4_path} already exists, skipping.")
        return

    print(f"[CONVERT] {mkv_path} → {mp4_path}")

    cmd = [
        "ffmpeg", "-hide_banner", "-y", "-loglevel", "error",
        "-i", str(mkv_path),
        "-c:v", "copy",                   # Copy streams without re-encoding
        "-c:a", "aac", "-b:a", "128k",    # convert pcm_alaw → aac (supported by mp4) 
        "-movflags", "+faststart",        # Optimize for web playback
        "-avoid_negative_ts", "make_zero",# Normalize timestamps
        str(mp4_path)
    ]

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print(f"[OK] Converted successfully: {mp4_path}")
        try:
            mkv_path.unlink()
            print(f"[DELETE] Removed: {mkv_path}")
        except Exception as e:
            print(f"[WARN] Could not delete {mkv_path}: {e}")
    else:
        print(f"[ERROR] Conversion failed: {mkv_path}")


# ==============================
# MAIN FUNCTION
# ==============================
def main():
    """
    Scan all subdirectories inside WATCH_DIR for .mkv files.
    Only process files located in folders named like YYYY-MM-DD.
    """
    base_path = Path(WATCH_DIR)

    if not base_path.exists():
        print(f"[ERROR] Directory not found: {WATCH_DIR}")
        return

    # Recursively find all MKV files
    mkv_files = sorted(base_path.rglob("*.mkv"))

    if not mkv_files:
        print("[INFO] No .mkv files found.")
        return

    print(f"[INFO] Found {len(mkv_files)} .mkv files (before filtering).")

    # Filter only those in date-formatted folders
    valid_mkv_files = [f for f in mkv_files if is_valid_date_folder(f)]

    if not valid_mkv_files:
        print("[INFO] No .mkv files inside valid date folders.")
        return

    print(f"[INFO] {len(valid_mkv_files)} files are in valid date folders.")

    for mkv in valid_mkv_files:
        try:
            convert_file(mkv)
        except Exception as e:
            print(f"[ERROR] Failed to process {mkv}: {e}")

    print("[DONE] Conversion cycle completed.")


# ==============================
# ENTRY POINT
# ==============================
if __name__ == "__main__":
    main()