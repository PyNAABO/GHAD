#!/usr/bin/env python3
"""Smart browser-based downloader for pages with Cloudflare protection."""

import asyncio
import os
import sys
import subprocess
import time
import re
import tempfile
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright

DOWNLOAD_DIR = "downloads"

VIDEO_EXTENSIONS = ('.mp4', '.m3u8', '.webm', '.mkv', '.avi', '.mov')
MIN_VIDEO_SIZE = 1024 * 1024  # 1MB minimum for a real video

def get_file_size(path):
    """Get file size in bytes."""
    try:
        return os.path.getsize(path)
    except:
        return 0

async def find_video_urls_on_page(page, url):
    """Find all video URLs on page including embed/API sources."""
    video_urls = []
    
    videos = await page.query_selector_all("video")
    for video in videos:
        src = await video.get_attribute("src")
        if src and not src.startswith('blob:'):
            video_urls.append(('video', src))
        
        try:
            effective_src = await video.evaluate("el => el.src")
            if effective_src and effective_src != src and not effective_src.startswith('blob:'):
                video_urls.append(('video_effective', effective_src))
        except:
            pass
    
    sources = await page.query_selector_all("video source")
    for source in sources:
        src = await source.get_attribute("src")
        if src and not src.startswith('blob:'):
            video_urls.append(('source', src))
    
    data_srcs = await page.query_selector_all("[data-src*='.mp4'], [data-src*='.m3u8'], [data-src*='video']")
    for el in data_srcs:
        src = await el.get_attribute("data-src")
        if src and not src.startswith('blob:'):
            video_urls.append(('data-src', src))
    
    scripts = await page.query_selector_all("script")
    for script in scripts:
        content = await script.inner_html() or ""
        urls = re.findall(r'["\'](https?://[^"\']+\.(?:mp4|m3u8|webm)[^"\']*)["\']', content)
        for u in urls:
            if not u.startswith('blob:'):
                video_urls.append(('script', u.strip('"\'')))
    
    json_configs = await page.query_selector_all("script[type='application/json'], script[type='application/ld+json']")
    for cfg in json_configs:
        content = await cfg.inner_html() or ""
        urls = re.findall(r'"(?:videoUrl|src|streamUrl|url|file)"["\']?\s*:\s*["\'](https?://[^"\']+)["\']', content)
        for u in urls:
            if not u.startswith('blob:'):
                video_urls.append(('json', u))
    
    links = await page.query_selector_all("a[href*='/download/'], a[href*='/get_file/'], a[href*='.mp4']")
    for link in links[:10]:
        href = await link.get_attribute("href")
        if href and any(x in href.lower() for x in ['.mp4', '.m3u8', 'video', 'download']):
            full_url = urljoin(url, href)
            video_urls.append(('download_link', full_url))
    
    seen = set()
    unique_urls = []
    for src_type, vurl in video_urls:
        if vurl not in seen:
            seen.add(vurl)
            unique_urls.append((src_type, vurl))
    
    return unique_urls

async def try_get_video_from_api(page, url):
    """Try to find and extract from API endpoints."""
    apis = await page.evaluate(""" "() => {
        const apis = [];
        if (window.playerData) apis.push(JSON.stringify(window.playerData));
        if (window.videoData) apis.push(JSON.stringify(window.videoData));
        if (window.config) apis.push(JSON.stringify(window.config));
        if (window.videoConfig) apis.push(JSON.stringify(window.videoConfig));
        if (window.video) apis.push(JSON.stringify(window.video));
        return apis;
    }""")
    
    for api in apis:
        if api:
            urls = re.findall(r'["\']?(https?://[^"\'<>\s]+(?:mp4|m3u8|manifest)[^"\'<>\s]*)["\']?', api)
            for u in urls:
                if not u.startswith('blob:') and any(x in u.lower() for x in VIDEO_EXTENSIONS):
                    return u
    
    return None

async def download_with_browser(url, filename, cookies_file=None):
    """Open URL in browser and extract video using browser session."""
    print(f"  [Browser] Opening: {url}")
    
    async with async_playwright() as p:
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
        
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = {runtime: {}, app: {}};
        """)
        
        page = await context.new_page()
        
        try:
            print(f"  [Browser] Waiting for page to load...")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
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
            
            await page.wait_for_timeout(10000)
            
            try:
                play_btn = page.locator("button:has-text('Play'), .play-btn, [class*='play']:visible")
                if await play_btn.count() > 0:
                    print(f"  [Browser] Clicking play button...")
                    await play_btn.first.click()
                    await page.wait_for_timeout(5000)
            except:
                pass
            
            video_urls = await find_video_urls_on_page(page, url)
            
            video_urls = [(src_type, vurl) for src_type, vurl in video_urls 
                         if not any(x in vurl.lower() for x in ['.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', 'poster', 'thumbnail', 'avatar', 'logo'])]
            
            for src_type, vurl in video_urls[:15]:
                print(f"  [Browser] Found [{src_type}]: {vurl[:120]}...")
            
            if not video_urls:
                print(f"  [Browser] No video URLs found on page")
                await browser.close()
                return False
            
            # Get cookies from browser context
            cookies = await context.cookies()
            cookie_dict = {c['name']: c['value'] for c in cookies}
            
            # Try to download using browser's session
            for src_type, vurl in video_urls:
                if vurl.startswith('blob:'):
                    continue
                if not vurl.startswith('http'):
                    continue
                
                print(f"  [Browser] Downloading {src_type} URL using browser session...")
                dest_path = os.path.join(DOWNLOAD_DIR, filename)
                
                try:
                    # Download using aria2c with cookies
                    import tempfile
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.cookies', delete=False) as cf:
                        for c in cookies:
                            cf.write(f"{c['domain']}\tTRUE\t/\tFALSE\t0\t{c['name']}\t{c['value']}\n")
                        cookie_file = cf.name
                    
                    cmd = ['aria2c', '--seed-time=0', '-x8', '-s8', '-k1M', '--dir', DOWNLOAD_DIR, '--cookie', cookie_file, '-o', filename, vurl]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                    
                    os.unlink(cookie_file)
                    
                    if result.returncode == 0:
                        if os.path.exists(dest_path):
                            size = get_file_size(dest_path)
                            ext = os.path.splitext(dest_path)[1].lower()
                            
                            if size >= MIN_VIDEO_SIZE or ext in VIDEO_EXTENSIONS:
                                print(f"  [Browser] Success! ({size/1024/1024:.2f} MB)")
                                await browser.close()
                                return True
                            else:
                                print(f"  [Browser] File too small ({size/1024:.1f} KB)")
                                os.remove(dest_path)
                except Exception as e:
                    print(f"  [Browser] Download error: {e}")
                
                print(f"  [Browser] aria2c failed, trying yt-dlp with cookies...")
                
                # Fallback to yt-dlp with cookies
                cmd = ['yt-dlp', '-o', dest_path]
                if cookies_file and os.path.exists(cookies_file):
                    cmd.extend(['--cookies', cookies_file])
                cmd.extend(['--', vurl])
                
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                
                if result.returncode == 0:
                    if os.path.exists(dest_path):
                        size = get_file_size(dest_path)
                        if size >= MIN_VIDEO_SIZE:
                            print(f"  [Browser] Success with yt-dlp! ({size/1024/1024:.2f} MB)")
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
