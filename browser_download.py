#!/usr/bin/env python3
"""Browser-based download fallback using Playwright."""

import asyncio
import os
import sys
import subprocess
import time
from playwright.async_api import async_playwright

DOWNLOAD_DIR = "downloads"

def download_with_curl(url, dest_path, timeout=120):
    """Download file using curl with retries."""
    for attempt in range(3):
        try:
            result = subprocess.run(
                ['curl', '-L', '-o', dest_path, '--max-time', str(timeout), '--retry', '2', url],
                capture_output=True, text=True, timeout=timeout+10
            )
            if result.returncode == 0 and os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
                return True
            print(f"  Attempt {attempt+1}: curl failed")
        except Exception as e:
            print(f"  Attempt {attempt+1} error: {e}")
        time.sleep(2)
    return False

async def download_with_browser(url, filename):
    """Open URL in browser and find video URL."""
    print(f"  [Browser] Opening: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        )

        page = await context.new_page()
        video_url = None

        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)

            videos = await page.query_selector_all("video")
            for video in videos:
                src = await video.get_attribute("src")
                if src and ("mp4" in src or "m3u8" in src):
                    video_url = src
                    print(f"  [Browser] Found video element")
                    break

            if not video_url:
                links = await page.query_selector_all("a[href*='.mp4'], a[href*='.m3u8']")
                for link in links[:3]:
                    href = await link.get_attribute("href")
                    if href and href.startswith("http"):
                        video_url = href
                        print(f"  [Browser] Found download link")
                        break

            await browser.close()

            if video_url and not video_url.startswith("blob:"):
                dest_path = os.path.join(DOWNLOAD_DIR, filename)
                print(f"  [Browser] Downloading...")
                if download_with_curl(video_url, dest_path):
                    print(f"  [Browser] Saved: {dest_path}")
                    return True

            print(f"  [Browser] No video found")
            return False

        except Exception as e:
            print(f"  [Browser] Error: {e}")
            await browser.close()
            return False

async def main():
    if len(sys.argv) < 3:
        print("Usage: browser_download.py <url> <filename>")
        sys.exit(1)

    url = sys.argv[1]
    filename = sys.argv[2]

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    success = await download_with_browser(url, filename)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
