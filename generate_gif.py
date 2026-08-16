"""
Generate LinkedIn post GIF (1080x1080) from linkedin_post.html using Selenium + Pillow.

Prerequisites:
    pip install selenium pillow
    # Chrome/Chromium must be installed (chromedriver auto-managed by selenium 4.6+)

Usage:
    python generate_gif.py
    # Output: linkedin_post.gif
"""
import os
import time
import tempfile
import shutil
from pathlib import Path

from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


# ─── Config ───────────────────────────────────────────────────────────────────
HTML_FILE = Path(__file__).parent / "linkedin_post.html"
OUTPUT_GIF = Path(__file__).parent / "linkedin_post.gif"

WIDTH = 1080
HEIGHT = 1080
FPS = 15
DURATION_SEC = 11
TOTAL_FRAMES = FPS * DURATION_SEC
FRAME_DELAY_MS = int(1000 / FPS)

# GIF optimization
MAX_COLORS = 256
OPTIMIZE = True


def setup_driver():
    """Create headless Chrome driver at exact post dimensions."""
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument(f"--window-size={WIDTH},{HEIGHT}")
    opts.add_argument("--force-device-scale-factor=1")
    opts.add_argument("--hide-scrollbars")

    driver = webdriver.Chrome(options=opts)
    driver.set_window_size(WIDTH, HEIGHT)
    return driver


def capture_frames(driver, tmp_dir):
    """Capture screenshots at regular intervals."""
    html_url = HTML_FILE.as_uri()
    driver.get(html_url)

    # Wait for page to fully load
    time.sleep(1)

    # Inject CSS to remove body background and isolate the post element
    driver.execute_script("""
        document.body.style.margin = '0';
        document.body.style.padding = '0';
        document.body.style.display = 'block';
        document.body.style.minHeight = 'auto';
        document.body.style.background = '#0d1117';
        const post = document.querySelector('.post');
        post.style.position = 'fixed';
        post.style.top = '0';
        post.style.left = '0';
    """)

    time.sleep(0.5)

    frames = []
    interval = 1.0 / FPS

    print(f"Capturing {TOTAL_FRAMES} frames at {FPS} fps...")

    for i in range(TOTAL_FRAMES):
        frame_path = os.path.join(tmp_dir, f"frame_{i:04d}.png")
        driver.save_screenshot(frame_path)
        frames.append(frame_path)

        if (i + 1) % FPS == 0:
            print(f"  {i + 1}/{TOTAL_FRAMES} frames ({(i+1)//FPS}s)")

        time.sleep(interval)

    return frames


def build_gif(frame_paths, output_path):
    """Assemble frames into an optimized GIF."""
    print(f"\nBuilding GIF from {len(frame_paths)} frames...")

    images = []
    for path in frame_paths:
        img = Image.open(path).convert("RGBA")
        # Crop to exact 1080x1080 if window captured extra chrome
        if img.size != (WIDTH, HEIGHT):
            img = img.crop((0, 0, WIDTH, HEIGHT))
        # Convert to palette mode for GIF
        img = img.convert("RGB").quantize(colors=MAX_COLORS, method=Image.MEDIANCUT)
        images.append(img)

    # Save as animated GIF
    images[0].save(
        output_path,
        save_all=True,
        append_images=images[1:],
        duration=FRAME_DELAY_MS,
        loop=0,
        optimize=OPTIMIZE,
    )

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"\nDone! Saved: {output_path}")
    print(f"Size: {size_mb:.2f} MB")
    print(f"Dimensions: {WIDTH}x{HEIGHT}")
    print(f"Duration: {DURATION_SEC}s at {FPS}fps")

    if size_mb > 5:
        print("\nWARNING: GIF is over 5MB. For faster LinkedIn loading, try:")
        print("  - Reduce FPS to 10")
        print("  - Reduce DURATION_SEC")
        print("  - Reduce MAX_COLORS to 128")


def main():
    if not HTML_FILE.exists():
        print(f"ERROR: {HTML_FILE} not found. Run from the project directory.")
        return

    tmp_dir = tempfile.mkdtemp(prefix="gif_frames_")

    try:
        driver = setup_driver()
        try:
            # Reset animation by reloading at capture start
            frames = capture_frames(driver, tmp_dir)
        finally:
            driver.quit()

        build_gif(frames, OUTPUT_GIF)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
