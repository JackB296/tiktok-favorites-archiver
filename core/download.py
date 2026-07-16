"""Atomic streaming file downloads (requires ``requests``)."""
import os
import time
import logging
import requests
from requests.exceptions import ChunkedEncodingError, ConnectionError, HTTPError, Timeout

from core import config

_sleep = time.sleep  # indirection so tests can observe retry pacing without waiting


def download_file(url, filename, max_retries=5):
    tmp_filename = filename + ".part"
    for attempt in range(max_retries):
        try:
            response = requests.get(url, stream=True, timeout=config.REQUEST_TIMEOUT)
            try:
                response.raise_for_status()
                with open(tmp_filename, "wb") as f:
                    for chunk in response.iter_content(chunk_size=config.DOWNLOAD_CHUNK_SIZE):
                        f.write(chunk)
            finally:
                response.close()
            if os.path.getsize(tmp_filename) == 0:
                logging.warning(f"Downloaded 0 bytes for {url}. Retrying {attempt + 1}/{max_retries}...")
                os.remove(tmp_filename)
                _sleep(config.RETRY_DELAY)
                continue
            os.replace(tmp_filename, filename)
            logging.info(f"Downloaded: {filename}")
            return True
        except HTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status is None or status < 500:
                logging.exception(f"Failed to download {url}: HTTP {status}")
                break  # 4xx is permanent; retrying won't help
            logging.error(f"Error downloading {url}: HTTP {status}. Retrying {attempt + 1}/{max_retries}...")
            _sleep(config.RETRY_DELAY)
        except (ChunkedEncodingError, ConnectionError, Timeout) as e:
            logging.error(f"Error downloading {url}: {e}. Retrying {attempt + 1}/{max_retries}...")
            _sleep(config.RETRY_DELAY)
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

