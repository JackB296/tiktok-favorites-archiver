"""Atomic streaming file downloads (requires ``requests``)."""
import os
import time
import logging
import requests
from requests.exceptions import ChunkedEncodingError, ConnectionError, HTTPError, Timeout

from core import config

_sleep = time.sleep  # indirection so tests can observe retry pacing without waiting

# HTTP statuses worth retrying: transient server errors, plus 408 (request
# timeout) and 429 (rate limited). 429 is a 4xx but is emphatically NOT
# permanent — Cobalt's tunnel endpoint returns it when the media-stream rate
# limit is hit, and the correct response is to back off and retry, not fail the
# whole item. Any other 4xx (404/410/…) stays permanent.
_RETRYABLE_STATUSES = frozenset({408, 429})


def _retry_wait(response, attempt):
    """Seconds to wait before the next retry: honor Retry-After, else back off."""
    header = getattr(response, "headers", {}).get("Retry-After") if response is not None else None
    if header:
        try:
            return min(float(header), 60.0)  # cap so one busy window can't stall a worker for minutes
        except (TypeError, ValueError):
            pass
    return min(config.RETRY_DELAY * (2 ** attempt), 60.0)  # exponential backoff, capped


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
            response = getattr(e, "response", None)
            status = getattr(response, "status_code", None)
            if status is None or (status < 500 and status not in _RETRYABLE_STATUSES):
                logging.exception(f"Failed to download {url}: HTTP {status}")
                break  # other 4xx is permanent; retrying won't help
            wait = _retry_wait(response, attempt)
            logging.warning(f"Error downloading {url}: HTTP {status}. Retrying {attempt + 1}/{max_retries} in {wait:.1f}s...")
            _sleep(wait)
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

