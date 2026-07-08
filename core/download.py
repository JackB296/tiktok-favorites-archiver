"""Atomic streaming file downloads (requires ``requests``)."""
import os
import time
import logging
import requests
from requests.exceptions import ChunkedEncodingError, ConnectionError, Timeout

from core import config


def download_file(url, filename, max_retries=5):
    tmp_filename = filename + ".part"
    for attempt in range(max_retries):
        try:
            response = requests.get(url, stream=True, timeout=config.REQUEST_TIMEOUT)
            response.raise_for_status()
            with open(tmp_filename, "wb") as f:
                for chunk in response.iter_content(chunk_size=config.DOWNLOAD_CHUNK_SIZE):
                    f.write(chunk)
            if os.path.getsize(tmp_filename) == 0:
                logging.warning(f"Downloaded 0 bytes for {url}. Retrying {attempt + 1}/{max_retries}...")
                os.remove(tmp_filename)
                time.sleep(config.RETRY_DELAY)
                continue
            os.replace(tmp_filename, filename)
            logging.info(f"Downloaded: {filename}")
            return True
        except (ChunkedEncodingError, ConnectionError, Timeout) as e:
            logging.error(f"Error downloading {url}: {e}. Retrying {attempt + 1}/{max_retries}...")
            time.sleep(config.RETRY_DELAY)
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
