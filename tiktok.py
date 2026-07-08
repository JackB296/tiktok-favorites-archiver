import requests
import json
import re
import os
import time
import logging
import argparse
import csv
from datetime import datetime
from requests.exceptions import ChunkedEncodingError, ConnectionError, Timeout
import shutil
from moviepy.editor import ImageSequenceClip, AudioFileClip, concatenate_audioclips
from PIL import Image

# Configuration
COBALT_API_URL = "http://localhost:9000/"
HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json"
}
RETRY_DELAY = 0.5  # Seconds between each download attempt
DOWNLOAD_DIR = "downloads"  # Directory to download videos
IMG_DIR = "img_dir"  # Temporary directory for creating slideshows
LAST_DOWNLOADED_LINK_FILE = "last_downloaded_link.txt"  # File to store the last downloaded link
VIDEO_LINKS_FILE = "user_data_tiktok.json"  # TikTok data file
MANIFEST_FILE = "manifest.csv"  # provenance sidecar: maps each output file to its source link
DURATION_PER_IMAGE = 2.5  # Duration each slide is shown in the slideshow
TARGET_SIZE = (1280, 720)  # Target resolution for images
DEFAULT_AUDIO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "default.mp3")  # bundled fallback audio
# (connect timeout, read timeout) in seconds. Read timeout is per-chunk, so slow
# but progressing downloads are not killed; a truly stalled socket is.
REQUEST_TIMEOUT = (10, 30)
DOWNLOAD_CHUNK_SIZE = 1024 * 256  # 256 KB per streamed chunk

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_payload(url):
    return {
        "url": url,
        "videoQuality": "max",
        "allowH265": True,
        "audioFormat": "best",
        "tiktokFullAudio": True,
    }

def download_file(url, filename, max_retries=5):
    tmp_filename = filename + ".part"
    for attempt in range(max_retries):
        try:
            response = requests.get(url, stream=True, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            with open(tmp_filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    f.write(chunk)
            if os.path.getsize(tmp_filename) == 0:
                logging.warning(f"Downloaded 0 bytes for {url}. Retrying {attempt + 1}/{max_retries}...")
                os.remove(tmp_filename)
                time.sleep(RETRY_DELAY)
                continue
            os.replace(tmp_filename, filename)
            logging.info(f"Downloaded: {filename}")
            return True
        except (ChunkedEncodingError, ConnectionError, Timeout) as e:
            logging.error(f"Error downloading {url}: {e}. Retrying {attempt + 1}/{max_retries}...")
            time.sleep(RETRY_DELAY)
        except Exception as e:
            logging.exception(f"Failed to download {url} due to an unexpected error: {e}")
            break
    if os.path.exists(tmp_filename):
        try:
            os.remove(tmp_filename)
        except OSError:
            pass
    logging.error(f"Failed to download {url} after {max_retries} attempts.")
    return False

def download_images(image_urls, download_dir):
    image_filenames = []
    for idx, img_url in enumerate(image_urls):
        filename = os.path.join(download_dir, f"slide_{idx}.jpg")
        if download_file(img_url, filename):
            image_filenames.append(filename)
    return image_filenames

def load_all_links(file_path):
    """Return every favorited link from the export, in processing order.

    This is the full, un-filtered list; `read_video_links` layers the resume
    bookmark on top of it, and `backfill_manifest` uses it to map file N -> link N.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as json_file:
            data = json.load(json_file)
    except FileNotFoundError:
        logging.error(f"Video links file not found: {file_path}")
        return []
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from file: {file_path}")
        return []

    item_favorite_list = data.get("Activity", {}).get("Favorite Videos", {}).get("FavoriteVideoList", [])

    return [
        re.sub(r'tiktokv.com', 'tiktok.com', item["Link"])
        for item in item_favorite_list if "Link" in item
    ][::-1]

def read_video_links(file_path):
    modified_lines = load_all_links(file_path)

    last_downloaded_link = read_last_downloaded_link(LAST_DOWNLOADED_LINK_FILE)
    if last_downloaded_link:
        try:
            last_link_index = modified_lines.index(last_downloaded_link)
            return modified_lines[last_link_index + 1:]
        except ValueError:
            return modified_lines
    return modified_lines

def resize_and_pad_image(image_path, target_size):
    try:
        image = Image.open(image_path)
        image.thumbnail(target_size, Image.Resampling.LANCZOS)
        new_image = Image.new("RGB", target_size, (0, 0, 0))
        new_image.paste(image, ((target_size[0] - image.width) // 2, (target_size[1] - image.height) // 2))
        new_image.save(image_path)
    except Exception as e:
        logging.exception(f"Failed to resize and pad image {image_path}: {e}")

def preprocess_images(image_paths, target_size):
    for image_path in image_paths:
        resize_and_pad_image(image_path, target_size)

def get_next_starting_count(directory):
    if not os.path.exists(directory):
        return 1
    existing_files = os.listdir(directory)
    video_numbers = [int(f.split('.')[0]) for f in existing_files if f.endswith('.mp4') and f.split('.')[0].isdigit()]
    return max(video_numbers, default=0) + 1

def read_last_downloaded_link(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            last_link = f.read().strip()
    except FileNotFoundError:
        last_link = None
    return last_link

def write_last_downloaded_link(file_path, last_link):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(last_link)
    except Exception as e:
        logging.error(f"Error writing last downloaded link: {e}")

def append_manifest(download_dir, filename, link, media_type, status):
    """Append one provenance row (creating the CSV with a header if needed)."""
    manifest_path = os.path.join(download_dir, MANIFEST_FILE)
    file_exists = os.path.exists(manifest_path)
    try:
        with open(manifest_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["file", "link", "type", "status", "timestamp"])
            writer.writerow([filename, link, media_type, status,
                             datetime.now().isoformat(timespec="seconds")])
    except OSError as e:
        logging.error(f"Could not write manifest {manifest_path}: {e}")

def backfill_manifest(download_dir, all_links):
    """Best-effort provenance for files downloaded before the manifest existed.

    File `N.mp4` maps to the Nth link in the export's processing order, which is
    exact for a single uninterrupted run over one export. Runs where links failed
    near a resume boundary can shift this, so backfilled rows are marked
    status="backfilled" (vs "ok" for rows recorded live) and type="unknown"
    (a bare .mp4 doesn't reveal whether it was a video or a rebuilt slideshow).
    """
    if not os.path.isdir(download_dir):
        return
    manifest_path = os.path.join(download_dir, MANIFEST_FILE)
    recorded = set()
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, newline='', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    recorded.add(row.get("file"))
        except OSError as e:
            logging.error(f"Could not read manifest {manifest_path}: {e}")
            return

    mp4s = [f for f in os.listdir(download_dir)
            if f.endswith('.mp4') and f.split('.')[0].isdigit() and f not in recorded]
    added = 0
    for filename in sorted(mp4s, key=lambda x: int(x.split('.')[0])):
        n = int(filename.split('.')[0])
        link = all_links[n - 1] if 1 <= n <= len(all_links) else ""
        append_manifest(download_dir, filename, link, "unknown", "backfilled")
        added += 1
    if added:
        logging.info(f"Backfilled {added} pre-existing file(s) into {manifest_path} (best-effort provenance)")

def create_slideshow(images, audio, output_filename, duration_per_image):
    preprocess_images(images, TARGET_SIZE)
    tmp_output = output_filename + ".part.mp4"
    clip = ImageSequenceClip(images, durations=[duration_per_image] * len(images))
    audio_clip = None
    looped_audio = None

    try:
        audio_clip = AudioFileClip(audio)
        slideshow_duration = len(images) * duration_per_image

        num_loops = int(slideshow_duration / audio_clip.duration) + 1
        looped_audio = concatenate_audioclips([audio_clip] * num_loops)
        looped_audio = looped_audio.subclip(0, slideshow_duration)

        clip = clip.set_audio(looped_audio)
        clip.write_videofile(tmp_output, codec="libx264", fps=24)
        os.replace(tmp_output, output_filename)
    except Exception as e:
        logging.exception(f"Failed to create slideshow: {e}")
        if os.path.exists(tmp_output):
            try:
                os.remove(tmp_output)
            except OSError:
                pass
    finally:
        for c in (clip, looped_audio, audio_clip):
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass

def parse_args():
    parser = argparse.ArgumentParser(
        description="Download your favorited TikTok videos and photo slideshows "
                    "from a TikTok data export, via a self-hosted Cobalt instance.",
    )
    parser.add_argument("--cobalt-url", default=COBALT_API_URL,
                        help="Address of your Cobalt instance (default: %(default)s)")
    parser.add_argument("--data-file", default=VIDEO_LINKS_FILE,
                        help="Path to your TikTok data export JSON (default: %(default)s)")
    parser.add_argument("--download-dir", default=DOWNLOAD_DIR,
                        help="Directory for finished videos (default: %(default)s)")
    parser.add_argument("--retry-delay", type=float, default=RETRY_DELAY,
                        help="Seconds between download attempts and requests (default: %(default)s)")
    return parser.parse_args()

def check_cobalt(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Cannot reach Cobalt at {url}: {e}")
        return False

def main():
    args = parse_args()
    global COBALT_API_URL, DOWNLOAD_DIR, VIDEO_LINKS_FILE, RETRY_DELAY
    COBALT_API_URL = args.cobalt_url
    DOWNLOAD_DIR = args.download_dir
    VIDEO_LINKS_FILE = args.data_file
    RETRY_DELAY = args.retry_delay

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    if not check_cobalt(COBALT_API_URL):
        logging.error("Cobalt is unreachable — aborting. Start your Cobalt instance or fix --cobalt-url.")
        return
    if shutil.which("ffmpeg") is None:
        logging.warning("ffmpeg not found on PATH; slideshow encoding may fail if MoviePy can't supply it.")
    backfill_manifest(DOWNLOAD_DIR, load_all_links(VIDEO_LINKS_FILE))
    video_links = read_video_links(VIDEO_LINKS_FILE)
    start_count = get_next_starting_count(DOWNLOAD_DIR)
    for count, video_link in enumerate(video_links, start_count):
        payload = create_payload(video_link)
        try:
            response = requests.post(
                COBALT_API_URL, headers=HEADERS,
                data=json.dumps(payload), timeout=REQUEST_TIMEOUT,
            )
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to reach Cobalt for {video_link}: {e}")
            time.sleep(RETRY_DELAY)
            continue
        if response.status_code == 200:
            data = response.json()
            logging.info(f"Response for {video_link}: {data}")

            status = data.get("status")

            if status in ["redirect", "tunnel"]:
                download_url = data.get("url")
                if not download_url:
                    logging.error(f"No download URL in Cobalt response for {video_link}")
                else:
                    filename = os.path.join(DOWNLOAD_DIR, f"{count}.mp4")
                    if not download_file(download_url, filename):
                        logging.error(f"Failed to download video: {video_link}")
                    else:
                        append_manifest(DOWNLOAD_DIR, f"{count}.mp4", video_link, "video", "ok")
            elif status == "picker":
                picker = data.get("picker", [])
                if picker and picker[0].get("type") == "photo":
                    image_urls = [item["url"] for item in picker]
                    audio_url = data.get("audio")
                    if image_urls:
                        os.makedirs(IMG_DIR, exist_ok=True)
                        image_files = download_images(image_urls, IMG_DIR)
                        if not image_files:
                            logging.error(f"All slide images failed to download for {video_link}")
                            shutil.rmtree(IMG_DIR, ignore_errors=True)
                        else:
                            if audio_url:
                                audio_file = os.path.join(IMG_DIR, "audio.mp3")
                                if not download_file(audio_url, audio_file):
                                    logging.warning("The audio for this slideshow no longer exists, using default audio")
                                    try:
                                        shutil.copy(DEFAULT_AUDIO, audio_file)
                                    except OSError as e:
                                        logging.error(f"Could not copy default audio from {DEFAULT_AUDIO}: {e}")
                                        audio_file = DEFAULT_AUDIO
                            else:
                                logging.warning("No audio found in picker response, using default audio")
                                audio_file = DEFAULT_AUDIO
                            filename = os.path.join(DOWNLOAD_DIR, f"{count}.mp4")
                            create_slideshow(image_files, audio_file, filename, DURATION_PER_IMAGE)
                            shutil.rmtree(IMG_DIR)
                            if os.path.exists(filename):
                                append_manifest(DOWNLOAD_DIR, f"{count}.mp4", video_link, "slideshow", "ok")
                            else:
                                logging.error(f"Slideshow produced no output file for {video_link}")
                    else:
                        logging.error(f"No images found in picker response for {video_link}")
                else:
                    logging.error(f"Picker response contains unsupported media types for {video_link}")
            elif status == "error":
                error_info = data.get("error", {})
                logging.error(f"Error in response for {video_link}: {error_info}")
            else:
                logging.error(f"Unknown status '{status}' in response for {video_link}")
        else:
            logging.error(f"Failed to process video {video_link}: HTTP {response.status_code}")
            logging.error(f"Response: {response.text}")

        # Record this link as processed so an interrupted run resumes from the
        # next link instead of re-scanning from the start.
        write_last_downloaded_link(LAST_DOWNLOADED_LINK_FILE, video_link)
        time.sleep(RETRY_DELAY)

if __name__ == "__main__":
    main()
