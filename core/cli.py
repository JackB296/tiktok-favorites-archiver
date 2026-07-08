"""Command-line entry point: the original single-run download flow.

Behaviour-identical to the pre-split ``tiktok.py`` — argparse overrides the four
runtime settings on ``config`` before the run so every module observes them.
"""
import os
import json
import time
import logging
import argparse
import shutil
import requests

from core import config
from core.cobalt import create_payload, check_cobalt
from core.download import download_file, download_images
from core.export import load_all_links, read_video_links, write_last_downloaded_link
from core.manifest import get_next_starting_count, append_manifest, backfill_manifest
from core.slideshow import create_slideshow


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download your favorited TikTok videos and photo slideshows "
                    "from a TikTok data export, via a self-hosted Cobalt instance.",
    )
    parser.add_argument("--cobalt-url", default=config.COBALT_API_URL,
                        help="Address of your Cobalt instance (default: %(default)s)")
    parser.add_argument("--data-file", default=config.VIDEO_LINKS_FILE,
                        help="Path to your TikTok data export JSON (default: %(default)s)")
    parser.add_argument("--download-dir", default=config.DOWNLOAD_DIR,
                        help="Directory for finished videos (default: %(default)s)")
    parser.add_argument("--retry-delay", type=float, default=config.RETRY_DELAY,
                        help="Seconds between download attempts and requests (default: %(default)s)")
    return parser.parse_args()


def main():
    args = parse_args()
    config.COBALT_API_URL = args.cobalt_url
    config.DOWNLOAD_DIR = args.download_dir
    config.VIDEO_LINKS_FILE = args.data_file
    config.RETRY_DELAY = args.retry_delay

    config.setup_logging()

    os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)
    if not check_cobalt(config.COBALT_API_URL):
        logging.error("Cobalt is unreachable — aborting. Start your Cobalt instance or fix --cobalt-url.")
        return
    if shutil.which("ffmpeg") is None:
        logging.warning("ffmpeg not found on PATH; slideshow encoding may fail if MoviePy can't supply it.")
    backfill_manifest(config.DOWNLOAD_DIR, load_all_links(config.VIDEO_LINKS_FILE))
    video_links = read_video_links(config.VIDEO_LINKS_FILE)
    start_count = get_next_starting_count(config.DOWNLOAD_DIR)
    for count, video_link in enumerate(video_links, start_count):
        payload = create_payload(video_link)
        try:
            response = requests.post(
                config.COBALT_API_URL, headers=config.HEADERS,
                data=json.dumps(payload), timeout=config.REQUEST_TIMEOUT,
            )
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to reach Cobalt for {video_link}: {e}")
            time.sleep(config.RETRY_DELAY)
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
                    filename = os.path.join(config.DOWNLOAD_DIR, f"{count}.mp4")
                    if not download_file(download_url, filename):
                        logging.error(f"Failed to download video: {video_link}")
                    else:
                        append_manifest(config.DOWNLOAD_DIR, f"{count}.mp4", video_link, "video", "ok")
            elif status == "picker":
                picker = data.get("picker", [])
                if picker and picker[0].get("type") == "photo":
                    image_urls = [item["url"] for item in picker]
                    audio_url = data.get("audio")
                    if image_urls:
                        os.makedirs(config.IMG_DIR, exist_ok=True)
                        image_files = download_images(image_urls, config.IMG_DIR)
                        if not image_files:
                            logging.error(f"All slide images failed to download for {video_link}")
                            shutil.rmtree(config.IMG_DIR, ignore_errors=True)
                        else:
                            if audio_url:
                                audio_file = os.path.join(config.IMG_DIR, "audio.mp3")
                                if not download_file(audio_url, audio_file):
                                    logging.warning("The audio for this slideshow no longer exists, using default audio")
                                    try:
                                        shutil.copy(config.DEFAULT_AUDIO, audio_file)
                                    except OSError as e:
                                        logging.error(f"Could not copy default audio from {config.DEFAULT_AUDIO}: {e}")
                                        audio_file = config.DEFAULT_AUDIO
                            else:
                                logging.warning("No audio found in picker response, using default audio")
                                audio_file = config.DEFAULT_AUDIO
                            filename = os.path.join(config.DOWNLOAD_DIR, f"{count}.mp4")
                            create_slideshow(image_files, audio_file, filename, config.DURATION_PER_IMAGE)
                            shutil.rmtree(config.IMG_DIR)
                            if os.path.exists(filename):
                                append_manifest(config.DOWNLOAD_DIR, f"{count}.mp4", video_link, "slideshow", "ok")
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
        write_last_downloaded_link(config.LAST_DOWNLOADED_LINK_FILE, video_link)
        time.sleep(config.RETRY_DELAY)
