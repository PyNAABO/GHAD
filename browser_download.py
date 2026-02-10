#!/usr/bin/env python3
"""Smart browser-based downloader for pages with multiple videos."""

import asyncio
import os
import sys
import subprocess
import time
import re
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright

DOWNLOAD_DIR = "downloads"

def run_yt_dlp(url):
    """Try yt-dlp first for page extraction."""
    print(f"  [Browser] Trying yt-dlp page extraction...")
    result = subprocess.run(
        ['yt-dlp', '--no-playlist', '-J', '--flat-playlist', url],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode == 0:
        return result.stdout
    return None

def extract_urls_from_json(json_output):
    """Extract URLs from yt-dlp JSON output."""
    try:
        import json
        data = json.loads(json_output)
        urls = []
        if 'url' in data:
            urls.append(data['url'])
        if 'entries' in data:
            for entry in data['entries']:
                if entry and 'url' in entry:
                    urls.append(entry['url'])
        return urls
    except:
        return []

async def find_main_video_on_page(page, url):
    """Find the main video on a page by looking for video elements and download links."""
    video_urls = []
    video_info = []

    # Look for <video> elements with src
    videos = await page.query_selector_all("video")
    for video in videos:
        src = await video.get_attribute("src")
        if src:
            video_urls.append(src)
            duration = await video.get_attribute("duration")
            info = await video.evaluate("""
                (el) => {
                    return {
                        width: el.videoWidth,
                        height: el.videoHeight,
                        duration: el.duration
                    };
                }
            """)
            video_info.append((src, info))
            print(f"  [Browser] Found <video> src: {src[:80]}...")

    # Look for video sources in <source> elements
    sources = await page.query_selector_all("video source")
    for source in sources:
        src = await source.get_attribute("src")
        if src and src not in video_urls:
            video_urls.append(src)
            print(f"  [Browser] Found <source> src: {src[:80]}...")

    # Look for download links with video extensions
    links = await page.query_selector_all("a[href*='.mp4'], a[href*='.m3u8'], a[href*='.webm'], a[href*='.mkv']")
    for link in links[:20]:  # Limit to first 20 links
        href = await link.get_attribute("href")
        if href:
            # Skip very small files (likely thumbnails/previews)
            text = await link.inner_text() or ""
            if any(x in text.lower() for x in ['preview', 'thumb', 'sample']):
                continue
            full_url = urljoin(url, href)
            if full_url not in video_urls:
                video_urls.append(full_url)
                print(f"  [Browser] Found download link: {href[:80]}...")

    # Look for data-src attributes (lazy loaded videos)
    lazy_videos = await page.query_selector_all("[data-src]")
    for lv in lazy_videos:
        src = await lv.get_attribute("data-src")
        if src and src not in video_urls:
            video_urls.append(src)
            print(f"  [Browser] Found lazy-loaded video: {src[:80]}...")

    return video_urls

async def find_largest_video(page, url):
    """Try to find the main/largest video on the page."""
    video_urls = await find_main_video_on_page(page, url)

    if not video_urls:
        return None

    # If multiple videos found, try to identify the main one
    # Usually the main video is in a player container or has specific attributes
    main_video = None

    # Look for video in player wrapper
    player = await page.query_selector(".player, #player, .video-player, [class*='player']")
    if player:
        videos = await player.query_selector_all("video")
        for video in videos:
            src = await video.get_attribute("src")
            if src:
                main_video = src
                print(f"  [Browser] Found video in player: {src[:80]}...")
                return main_video

    # Otherwise return the first/largest video
    return video_urls[0] if video_urls else None

async def download_with_browser(url, filename):
    """Open URL in browser and find main video."""
    print(f"  [Browser] Opening: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )

        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)  # Wait for videos to load

            # Try to click play if video is paused
            try:
                video = await page.query_selector("video")
                if video:
                    is_paused = await video.evaluate("el => el.paused")
                    if is_paused:
                        await video.click()
                        await page.wait_for_timeout(2000)
            except:
                pass

            # Find main video
            main_video = await find_largest_video(page, url)
            await browser.close()

            if main_video:
                if main_video.startswith("blob:"):
                    print(f"  [Browser] Blob URL detected - yt-dlp handles these better")
                    return False

                dest_path = os.path.join(DOWNLOAD_DIR, filename)
                print(f"  [Browser] Downloading main video: {main_video[:80]}...")

                # Use yt-dlp to download the video URL
                result = subprocess.run(
                    ['yt-dlp', '-o', dest_path, '--', main_video],
                    capture_output=True, text=True, timeout=600
                )
                if result.returncode == 0:
                    print(f"  [Browser] Saved: {dest_path}")
                    return True
                else:
                    print(f"  [Browser] yt-dlp failed: {result.stderr[:200]}")

            print(f"  [Browser] No main video found")
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
