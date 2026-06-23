#!/usr/bin/env python3
"""Test nodriver against Geekbench Cloudflare protection."""
import asyncio
import nodriver as uc

async def test_geekbench():
    print("Launching Chrome with nodriver...")
    browser = await uc.start(
        headless=False,
        browser_executable_path='/usr/bin/vivaldi',
        browser_args=[
            '--no-first-run',
            '--no-default-browser-check',
        ],
    )
    print("Chrome launched, navigating to Geekbench...")

    # Test 1: Navigate to search page (highest single-core for 9600x)
    url = 'https://browser.geekbench.com/v6/cpu/search?q=9600x&sort=score&dir=desc'
    page = await browser.get(url)
    print(f"Navigated to: {url}")

    # Wait for page to load (Cloudflare might challenge)
    print("Waiting for page to load...")
    await asyncio.sleep(8)

    # Check title
    title = await page.evaluate('document.title')
    print(f"Page title: {title}")

    # Extract first result
    html = await page.get_content()
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')

    # Find all score entries
    scores = soup.select('.list-col-text-score')
    if scores:
        print(f"\nFound {len(scores)} score elements")
        # First result: single-core and multi-core
        single = scores[0].get_text(strip=True) if len(scores) > 0 else 'N/A'
        multi = scores[1].get_text(strip=True) if len(scores) > 1 else 'N/A'
        print(f"Highest single-core: {single}")
        print(f"Highest multi-core:  {multi}")

        # Extract CPU model
        models = soup.select('.list-col-model')
        if models:
            print(f"CPU model: {models[0].get_text(strip=True)}")

        # Extract system info
        systems = soup.select('.list-col-subtitle + a')
        if systems:
            print(f"System: {systems[0].get_text(strip=True)}")
    else:
        print("No scores found! Page might be blocked.")
        # Save HTML for debugging
        with open('/tmp/gb_nodriver_debug.html', 'w') as f:
            f.write(html[:5000])
        print("Saved debug HTML to /tmp/gb_nodriver_debug.html")

    # Test 2: Navigate to ascending order (lowest scores)
    print("\n--- Test 2: Lowest scores (dir=asc) ---")
    url2 = 'https://browser.geekbench.com/v6/cpu/search?q=9600x&sort=score&dir=asc'
    page2 = await browser.get(url2)
    print(f"Navigated to: {url2}")
    await asyncio.sleep(8)

    title2 = await page2.evaluate('document.title')
    print(f"Page title: {title2}")

    html2 = await page2.get_content()
    soup2 = BeautifulSoup(html2, 'html.parser')
    scores2 = soup2.select('.list-col-text-score')
    if scores2:
        single_low = scores2[0].get_text(strip=True)
        multi_low = scores2[1].get_text(strip=True)
        print(f"Lowest single-core: {single_low}")
        print(f"Lowest multi-core:  {multi_low}")
    else:
        print("No scores found on ascending page!")

    # Test 3: Multi-core sort
    print("\n--- Test 3: Multi-core sort (sort=multicore_score) ---")
    url3 = 'https://browser.geekbench.com/v6/cpu/search?q=9600x&sort=multicore_score&dir=desc'
    page3 = await browser.get(url3)
    await asyncio.sleep(8)

    title3 = await page3.evaluate('document.title')
    print(f"Page title: {title3}")

    html3 = await page3.get_content()
    soup3 = BeautifulSoup(html3, 'html.parser')
    scores3 = soup3.select('.list-col-text-score')
    if scores3:
        single_mc = scores3[0].get_text(strip=True)
        multi_mc = scores3[1].get_text(strip=True)
        print(f"Top result single-core: {single_mc}")
        print(f"Top result multi-core:  {multi_mc}")
    else:
        print("No scores found on multi-core sort page!")

    print("\n--- All tests done ---")
    browser.stop()

if __name__ == '__main__':
    asyncio.run(test_geekbench())
