#!/usr/bin/env python3

"""
Download all images and videos from a Reddit user account and automatically remove duplicates.

Changes vs original:
- youtube_dl → yt-dlp (youtube_dl is abandoned and broken)
- Pushshift API → PRAW (official Reddit API, Pushshift is unreliable/dead)
- Fixed duplicate removal logic edge cases
- Added Reddit API credential handling

Requirements:
    pip install praw yt-dlp opencv-python imagededup

Reddit API credentials:
    1. Go to https://www.reddit.com/prefs/apps
    2. Click "create another app" → choose "script"
    3. Fill in name + redirect URI (e.g. http://localhost:8080)
    4. Copy client_id (under app name) and client_secret
    5. Pass them via --client-id and --client-secret, or set env vars:
       REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET
"""

import argparse
import datetime
import logging
import os
import sys
import time

import cv2
import praw
import requests
import yt_dlp
from imagededup.methods import PHash


url_list = []


# ── Reddit fetching ────────────────────────────────────────────────────────────

def get_reddit_client(client_id: str, client_secret: str) -> praw.Reddit:
    return praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent="Python:RedditDownloader:v2.0 (by u/your_username)",
    )


def get_posts(reddit: praw.Reddit, username: str, limit=None):
    """Yield submissions from a user. limit=None fetches all."""
    user = reddit.redditor(username)
    logging.info(f"Fetching submissions from u/{username}")
    # PRAW uses None for "no limit"
    for submission in user.submissions.new(limit=limit):
        yield submission


# ── Download helpers ───────────────────────────────────────────────────────────

def is_image_url(url: str) -> bool:
    image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
    return any(url.lower().endswith(ext) for ext in image_extensions)


def is_video_url(url: str) -> bool:
    video_extensions = (".mp4", ".webm", ".mov", ".mkv")
    video_domains = ("v.redd.it", "gfycat.com", "redgifs.com", "imgur.com")
    return any(url.lower().endswith(ext) for ext in video_extensions) or \
           any(domain in url for domain in video_domains) or \
           "gif" in url.lower()


def download_image(url: str, target_file: str) -> bool:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        with open(target_file, "wb") as f:
            f.write(res.content)
        logging.info(f"Image downloaded: {url} → {target_file}")
        return True
    except Exception as e:
        logging.error(f"Failed to download image {url}: {e}")
        return False


def download_video(url: str, target_template: str) -> bool:
    ydl_opts = {
        "outtmpl": target_template,
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        logging.info(f"Video downloaded: {url}")
        return True
    except yt_dlp.utils.DownloadError as e:
        logging.error(f"Failed to download video {url}: {e}")
        return False


def process_submission(submission, output_dir: str):
    global url_list

    url = submission.url
    if url in url_list:
        return
    url_list.append(url)

    # Skip text posts
    if submission.is_self:
        return

    timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H%M%S")
    filename_base = url.split("/")[-1].split("?")[0]  # strip query params

    if is_video_url(url):
        target = os.path.join(output_dir, f"{timestamp}-%(id)s.%(ext)s")
        logging.info(f"Downloading video: {url}")
        download_video(url, target)

    elif is_image_url(url):
        # Preserve original extension, fall back to .jpg
        ext = os.path.splitext(filename_base)[-1] or ".jpg"
        target = os.path.join(output_dir, f"{timestamp}-{filename_base}{ext if ext not in filename_base else ''}")
        logging.info(f"Downloading image: {url}")
        download_image(url, target)

    else:
        # Try image first, then video
        logging.info(f"Unknown type, trying image then video: {url}")
        target_img = os.path.join(output_dir, f"{timestamp}-{filename_base}.jpg")
        if not download_image(url, target_img):
            target_vid = os.path.join(output_dir, f"{timestamp}-%(id)s.%(ext)s")
            download_video(url, target_vid)


# ── Deduplication ──────────────────────────────────────────────────────────────

def extract_first_frames(images_dir: str) -> dict:
    """
    Extract the first frame from each .mp4 file as a .jpg.
    Returns {frame_filename: video_filename}.
    """
    logging.info("Extracting first frames from videos...")
    video_frames = {}

    for filename in os.listdir(images_dir):
        if filename.lower().endswith(".mp4"):
            video_path = os.path.join(images_dir, filename)
            frame_path = video_path + ".jpg"
            cap = cv2.VideoCapture(video_path)
            success, frame = cap.read()
            cap.release()
            if success:
                cv2.imwrite(frame_path, frame)
                video_frames[os.path.basename(frame_path)] = filename
                logging.info(f"Frame extracted: {frame_path}")
            else:
                logging.error(f"Could not extract frame from {filename}")

    return video_frames


def remove_duplicates(duplicates: dict, video_frames: dict, images_dir: str):
    """
    Remove duplicate files.
    - If a duplicate is a video frame → delete the associated video + frame
    - Otherwise → delete the duplicate image
    """
    deleted = set()  # track already-deleted files to avoid double-delete

    for original, dups in duplicates.items():
        if not dups:
            continue

        for dup in dups:
            if dup in deleted:
                continue

            dup_path = os.path.join(images_dir, dup)

            if dup in video_frames:
                # Duplicate is a video frame → remove frame + video
                video_path = os.path.join(images_dir, video_frames[dup])
                for path in (dup_path, video_path):
                    if os.path.exists(path):
                        os.remove(path)
                        logging.info(f"Deleted duplicate video/frame: {path}")
                        deleted.add(os.path.basename(path))
            else:
                # Regular duplicate image
                if os.path.exists(dup_path):
                    os.remove(dup_path)
                    logging.info(f"Deleted duplicate image: {dup_path}")
                    deleted.add(dup)

    # Clean up all video frame .jpg files that were created for hashing
    for frame_file in video_frames:
        frame_path = os.path.join(images_dir, frame_file)
        if os.path.exists(frame_path) and frame_file not in deleted:
            os.remove(frame_path)
            logging.info(f"Cleaned up temp frame: {frame_path}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Download Reddit user media (updated v2)")
    parser.add_argument("-u", "--user", required=True, help="Reddit username to download from")
    parser.add_argument("-l", "--limit", type=int, default=None, help="Max number of posts (default: all)")
    parser.add_argument("--client-id", default=os.environ.get("REDDIT_CLIENT_ID"), help="Reddit API client ID")
    parser.add_argument("--client-secret", default=os.environ.get("REDDIT_CLIENT_SECRET"), help="Reddit API client secret")
    parser.add_argument("--skip-download", action="store_true", help="Skip downloading, only deduplicate existing files")
    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=logging.INFO,
        handlers=[
            logging.FileHandler("execution.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    if not args.client_id or not args.client_secret:
        print(
            "ERROR: Reddit API credentials required.\n"
            "Set --client-id and --client-secret, or use env vars:\n"
            "  export REDDIT_CLIENT_ID=your_id\n"
            "  export REDDIT_CLIENT_SECRET=your_secret\n"
            "Get credentials at: https://www.reddit.com/prefs/apps"
        )
        sys.exit(1)

    # Create output directory
    images_dir = os.path.join("output", args.user)
    os.makedirs(images_dir, exist_ok=True)
    logging.info(f"Output directory: {images_dir}")

    # Download phase
    if not args.skip_download:
        reddit = get_reddit_client(args.client_id, args.client_secret)
        logging.info(f"Starting download for u/{args.user} (limit={args.limit})")
        count = 0
        for submission in get_posts(reddit, args.user, limit=args.limit):
            process_submission(submission, images_dir)
            count += 1
            time.sleep(0.5)  # be polite to Reddit's API
        logging.info(f"Downloaded from {count} posts.")

    # Deduplication phase
    logging.info("Starting deduplication...")
    video_frames = extract_first_frames(images_dir)

    phasher = PHash()
    encodings = phasher.encode_images(image_dir=images_dir)
    duplicates = phasher.find_duplicates(encoding_map=encodings)

    logging.info(f"Found {sum(len(v) for v in duplicates.values())} duplicates across {len(duplicates)} originals")
    remove_duplicates(duplicates, video_frames, images_dir)

    logging.info("Done.")


if __name__ == "__main__":
    main()
