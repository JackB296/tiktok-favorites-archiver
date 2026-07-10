"""Slideshow MP4 encoder.

Rendering rules (per spec): the canvas is the **largest image in the post**
(max width x max height, rounded up to even for H.264), every image centered on
a black background at its native size — **no downscaling, no blurred fill**,
2.5s/image, high-quality encode. Portrait posts therefore come out portrait and
show full-height (pillarboxed) on a 16:9 TV via Plex.

``PIL``/``moviepy`` are imported lazily so ``compute_canvas_size`` (pure) is
unit-testable without them.
"""
import os
import shutil
import tempfile
import logging

from core import config


def _even(n):
    """Round up to the nearest even integer (H.264 requires even dimensions)."""
    n = int(n)
    return n if n % 2 == 0 else n + 1


def compute_canvas_size(sizes):
    """Given ``[(w, h), ...]`` return the canvas ``(W, H)`` = the largest width and
    largest height across the images, rounded up to even. No image exceeds this
    box, so every image is padded (never downscaled)."""
    if not sizes:
        return (2, 2)
    max_w = max(w for w, h in sizes)
    max_h = max(h for w, h in sizes)
    return (_even(max_w), _even(max_h))


def _pad_image(src, dest, canvas_size):
    from PIL import Image
    with Image.open(src) as opened:
        im = opened.convert("RGB")
        canvas = Image.new("RGB", canvas_size, (0, 0, 0))
        offset = ((canvas_size[0] - im.width) // 2, (canvas_size[1] - im.height) // 2)
        canvas.paste(im, offset)
        canvas.save(dest, quality=95)


def create_slideshow(images, audio, output_filename, duration_per_image=config.DURATION_PER_IMAGE):
    """Encode a slideshow MP4 atomically. Returns True on success.

    Non-destructive: the input images are read for their sizes and padded into a
    throwaway temp dir; the originals are left untouched so the web carousel can
    use the raw images.
    """
    from PIL import Image
    from moviepy.editor import ImageSequenceClip, AudioFileClip, concatenate_audioclips

    if not images:
        logging.error("create_slideshow called with no images")
        return False

    tmp_output = output_filename + ".part.mp4"
    tmpdir = tempfile.mkdtemp(prefix="slideshow_")
    clip = audio_clip = looped_audio = None
    try:
        sizes = []
        for path in images:
            with Image.open(path) as im:
                sizes.append(im.size)
        canvas = compute_canvas_size(sizes)

        frames = []
        for idx, path in enumerate(images):
            frame = os.path.join(tmpdir, f"frame_{idx:04d}.jpg")
            _pad_image(path, frame, canvas)
            frames.append(frame)

        clip = ImageSequenceClip(frames, durations=[duration_per_image] * len(frames))
        audio_clip = AudioFileClip(audio)
        total = len(frames) * duration_per_image
        num_loops = int(total / audio_clip.duration) + 1
        looped_audio = concatenate_audioclips([audio_clip] * num_loops).subclip(0, total)
        clip = clip.set_audio(looped_audio)
        clip.write_videofile(
            tmp_output, codec="libx264", fps=24,
            ffmpeg_params=["-crf", "18", "-pix_fmt", "yuv420p"],
        )
        os.replace(tmp_output, output_filename)
        return True
    except Exception as e:
        logging.exception(f"Failed to create slideshow: {e}")
        if os.path.exists(tmp_output):
            try:
                os.remove(tmp_output)
            except OSError:
                pass
        return False
    finally:
        for c in (clip, looped_audio, audio_clip):
            if c is not None:
                try:
                    c.close()
                except Exception:
                    pass
        shutil.rmtree(tmpdir, ignore_errors=True)
