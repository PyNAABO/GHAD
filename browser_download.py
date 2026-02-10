#!/usr/bin/env python3
"""Smart browser-based downloader for pages with Cloudflare protection."""

import asyncio
import os
import sys
import subprocess
import time
import re
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright

DOWNLOAD_DIR = "downloads"

def run_yt_dlp(url, cookies_file=None):
    """Try yt-dlp with fallback options."""
    print(f"  [Browser] Trying yt-dlp...")
    cmd = ['yt-dlp', '--no-playlist', '-o', f'{DOWNLOAD_DIR}/%(title)s.%(ext)s']
    if cookies_file and os.path.exists(cookies_file):
        cmd.extend(['--cookies', cookies_file])
    cmd.extend(['--', url])
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode == 0:
        return True
    return False

async def find_video_urls_on_page(page, url):
    """Find all video URLs on page including embed/API sources."""
    video_urls = []
    
    # Look for video elements
    videos = await page.query_selector_all("video")
    for video in videos:
        src = await video.get_attribute("src")
        poster = await video.get_attribute("poster")
        if src:
            video_urls.append(('video_src', src))
        if poster:
            video_urls.append(('poster', poster))
    
    # Look for source elements
    sources = await page.query_selector_all("video source")
    for source in sources:
        src = await source.get_attribute("src")
        if src:
            video_urls.append(('source', src))
    
    # Look for embed/video URLs
    embeds = await page.query_selector_all("embed[src*='.mp4'], object[data*='.mp4'], iframe[src*='video'], iframe[src*='player']")
    for embed in embeds:
        src = await embed.get_attribute("src")
        if src:
            video_urls.append(('embed', src))
    
    # Look for data-src attributes (lazy loading)
    lazy = await page.query_selector_all("[data-src]")
    for el in lazy:
        src = await el.get_attribute("data-src")
        if src and any(x in src.lower() for x in ['.mp4', '.m3u8', '.webm', 'video', 'stream', 'player']):
            video_urls.append(('data-src', src))
    
    # Look for JavaScript configurations
    scripts = await page.query_selector_all("script")
    for script in scripts:
        content = await script.inner_html() or ""
        # Find URLs in script content
        urls = re.findall(r'["\']https?://[^"\']+\.(mp4|m3u8|webm)[^"\']*["\']', content)
        for u in urls:
            video_urls.append(('script', u.strip('"\'')))
    
    # Look for player configuration JSON
    json_configs = await page.query_selector_all("script[type='application/json'], script[type='application/ld+json']")
    for cfg in json_configs:
        content = await cfg.inner_html() or ""
        urls = re.findall(r'"(?:videoUrl|src|streamUrl|url|file)"["\']?\s*:\s*["\'](https?://[^"\']+)["\']', content)
        for u in urls:
            video_urls.append(('json', u))
    
    # Look for video page links
    links = await page.query_selector_all("a[href*='/videos/'], a[href*='/watch/'], a[href*='player']")
    for link in links[:10]:
        href = await link.get_attribute("href")
        if href:
            full_url = urljoin(url, href)
            video_urls.append(('page_link', full_url))
    
    return video_urls

async def try_get_video_from_api(page, url):
    """Try to find and extract from API endpoints."""
    # Look for API calls in page
    apis = await page.evaluate("""() => {
        const apis = [];
        // Check for global player config
        if (window.playerData) apis.push(JSON.stringify(window.playerData));
        if (window.videoData) apis.push(JSON.stringify(window.videoData));
        if (window.config) apis.push(JSON.stringify(window.config));
        if (window.videoConfig) apis.push(JSON.stringify(window.videoConfig));
        return apis;
    }""")
    
    for api in apis:
        if api:
            urls = re.findall(r'["\']?(https?://[^"\'<>\s]+(?:mp4|m3u8|manifest)[^"\'<>\s]*)["\']?', api)
            for u in urls:
                if not u.startswith('blob:'):
                    return u
    
    return None

async def download_with_browser(url, filename, cookies_file=None):
    """Open URL in browser and extract video using multiple methods."""
    print(f"  [Browser] Opening: {url}")
    
    async with async_playwright() as p:
        # Try Chrome first, fall back to Chromium
        browser_path = None
        try:
            browser_path = '/usr/bin/google-chrome'
            if not os.path.exists(browser_path):
                browser_path = None
        except:
            pass
        
        browser_args = [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--window-size=1920,1080',
            '--start-maximized',
            '--disable-blink-features=AutomationControlled',
            '--disable-web-security',
            '--enable-features=NetworkService',
        ]
        
        if browser_path:
            print(f"  [Browser] Using Chrome")
            browser = await p.chromium.launch(
                headless=True,
                executable_path=browser_path,
                args=browser_args
            )
        else:
            print(f"  [Browser] Using Chromium")
            browser = await p.chromium.launch(
                headless=True,
                args=browser_args
            )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            permissions=[],
            ignore_https_errors=True,
        )
        
        # Stealth: remove webdriver detection
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = {runtime: {}, app: {}};
        """)
        
        page = await context.new_page()
        
        try:
            # Wait for Cloudflare protection if present
            print(f"  [Browser] Waiting for page to load...")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Wait for Cloudflare challenge
            try:
                await page.wait_for_function("""
                    () => {
                        return !document.querySelector('#cf-challenge-running') && 
                               !document.querySelector('.challenge-running') &&
                               !document.querySelector('[id*="challenge"]') &&
                               document.readyState === 'complete';
                    }
                """, timeout=30000)
                print(f"  [Browser] Cloudflare challenge passed")
            except:
                print(f"  [Browser] Could not verify Cloudflare clearance, continuing...")
            
            # Wait additional time for dynamic content
            await page.wait_for_timeout(8000)
            
            # Try clicking play button if exists
            try:
                play_btn = page.locator("button:has-text('Play'), .play-btn, [class*='play']:visible")
                if await play_btn.count() > 0:
                    await play_btn.first.click()
                    await page.wait_for_timeout(3000)
            except:
                pass
            
            # Get video URLs found
            video_urls = await find_video_urls_on_page(page, url)
            
            # Print all found URLs
            for src_type, vurl in video_urls[:15]:
                print(f"  [Browser] Found [{src_type}]: {vurl[:100]}...")
            
            # Try to find a working URL
            for src_type, vurl in video_urls:
                if vurl.startswith('blob:'):
                    # Try to get the source from video element
                    continue
                if vurl.startswith('http') and not any(x in vurl for x in ['cloudflare', '403', 'captcha']):
                    print(f"  [Browser] Trying {src_type} URL...")
                    dest_path = os.path.join(DOWNLOAD_DIR, filename)
                    cmd = ['yt-dlp', '-o', dest_path]
                    if cookies_file and os.path.exists(cookies_file):
                        cmd.extend(['--cookies', cookies_file])
                    cmd.extend(['--', vurl])
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                    if result.returncode == 0:
                        print(f"  [Browser] Success with {src_type}!")
                        await browser.close()
                        return True
                    else:
                        err_msg = result.stderr[:200] if result.stderr else 'Unknown error'
                        print(f"  [Browser] Failed: {err_msg}")
            
            # Try API extraction
            api_url = await try_get_video_from_api(page, url)
            if api_url:
                print(f"  [Browser] Trying API URL...")
                dest_path = os.path.join(DOWNLOAD_DIR, filename)
                cmd = ['yt-dlp', '-o', dest_path]
                if cookies_file and os.path.exists(cookies_file):
                    cmd.extend(['--cookies', cookies_file])
                cmd.extend(['--', api_url])
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                if result.returncode == 0:
                    print(f"  [Browser] API URL worked!")
                    await browser.close()
                    return True
            
            await browser.close()
            print(f"  [Browser] No working video URL found")
            return False
            
        except Exception as e:
            print(f"  [Browser] Error: {e}")
            await browser.close()
            return False

async def main():
    if len(sys.argv) < 3:
        print("Usage: browser_download.py <url> <filename> [cookies.txt]")
        sys.exit(1)
    
    url = sys.argv[1]
    filename = sys.argv[2]
    cookies_file = sys.argv[3] if len(sys.argv) > 3 else None
    
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    success = await download_with_browser(url, filename, cookies_file)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())
