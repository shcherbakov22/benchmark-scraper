#!/usr/bin/env python3
"""Scrape Geekbench 6 search results (high/low scores) for each CPU.

Optimized: ~9s per CPU (4 queries × 2.3s) after initial Cloudflare bypass.
Filters out invalid scores (0, suspiciously low values).

Usage:
    python3 scrape_geekbench_search.py              # scrape all CPUs
    python3 scrape_geekbench_search.py --limit 100  # first 100 only
"""
import asyncio
import argparse
import os
import re
import sqlite3
import time
from bs4 import BeautifulSoup

import nodriver as uc

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "benchmarks.sqlite")

SEARCH_URL = "https://browser.geekbench.com/v6/cpu/search?q={query}&sort={sort}&dir={direction}"

DELAY_PER_QUERY = 1.5   # minimum reliable wait after CF bypass
DELAY_BETWEEN_CPUS = 0.5

# Filter: ignore scores below these thresholds (likely invalid/broken submissions)
MIN_SINGLE_CORE = 100   # real CPUs score > 300
MIN_MULTI_CORE = 200    # real CPUs score > 1000


def init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS geekbench_search (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            cpu_id          INTEGER NOT NULL REFERENCES cpus(id) ON DELETE CASCADE,
            cpu_name        TEXT NOT NULL,
            single_high     INTEGER,
            single_low      INTEGER,
            multi_high      INTEGER,
            multi_low       INTEGER,
            results_count   INTEGER,
            scraped_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_gb_search_cpu_id ON geekbench_search (cpu_id);
        CREATE INDEX IF NOT EXISTS idx_gb_search_cpu_name ON geekbench_search (cpu_name);
    """)
    conn.commit()


def get_cpu_names(conn, source=None, limit=None):
    query = """
        SELECT c.id, c.name FROM cpus c
        WHERE NOT EXISTS (SELECT 1 FROM geekbench_search gs WHERE gs.cpu_id = c.id)
    """
    if source == "notebookcheck":
        query += " AND c.nb_id IS NOT NULL"
    elif source == "vray":
        query += " AND c.vray_id IS NOT NULL"
    elif source == "geekbench":
        query += " AND c.geekbench_id IS NOT NULL"
    query += " ORDER BY c.id"
    if limit:
        query += " LIMIT ?"
    return conn.execute(query, (limit,) if limit else ()).fetchall()


def sanitize_query(name):
    name = name.strip()
    m = re.search(r'(M\d+\s+(Max|Pro|Ultra))', name)
    if m: return m.group(1).strip()
    m = re.search(r'(i[3-9]-\d+[A-Z]?)', name)
    if m: return m.group(1)
    m = re.search(r'(Core\s+Ultra\s+\d+\s+\d+[A-Z]?)', name)
    if m: return m.group(1)
    m = re.search(r'(Ryzen\s+AI\s+\d+\s+[A-Z]+\s+\d+[A-Z]*|Ryzen\s+\d+\s+\d+[A-Z0-9]+)', name)
    if m: return m.group(1)
    m = re.search(r'(Threadripper\s+(?:PRO\s+)?\d+[A-Z]+)', name)
    if m: return m.group(1)
    m = re.search(r'(EPYC\s+\d+[A-Z]+)', name)
    if m: return m.group(1)
    m = re.search(r'(Snapdragon\s+[A-Z0-9]+(?:\s+[A-Za-z]+)?)', name)
    if m: return m.group(1)
    clean = re.sub(r'\d+-Core.*', '', name).strip()
    clean = re.sub(r'\d+\s*MHz.*', '', clean).strip()
    clean = re.sub(r'\(\d+\s*cores?.*', '', clean).strip()
    parts = clean.split()
    if len(parts) >= 3: return ' '.join(parts[-3:])
    return ' '.join(parts[-2:]) if len(parts) >= 2 else parts[0]


def parse_search_results(html, sort_field, direction):
    """Parse search results, filtering invalid scores.

    For 'desc': first valid result = high score
    For 'asc':  first valid result = low score (skip invalid 0/near-0)
    """
    soup = BeautifulSoup(html, 'html.parser')
    total_count = 0
    small = soup.select_one('h2 small')
    if small:
        m = re.search(r'(\d[\d,]*)', small.get_text())
        if m:
            total_count = int(m.group(1).replace(',', ''))

    rows = soup.select('.list-col-inner')
    for row in rows:
        scores = row.select('.list-col-text-score')
        if len(scores) >= 2:
            single = int(scores[0].get_text(strip=True))
            multi = int(scores[1].get_text(strip=True))

            # Filter invalid scores
            if single < MIN_SINGLE_CORE or multi < MIN_MULTI_CORE:
                continue
            if single <= 0 or multi <= 0:
                continue

            return {'single': single, 'multi': multi, 'total_count': total_count}

    return None


async def scrape_cpu(browser, cpu_id, cpu_name):
    query = sanitize_query(cpu_name)
    result = {
        'cpu_id': cpu_id, 'cpu_name': cpu_name, 'query': query,
        'single_high': None, 'single_low': None,
        'multi_high': None, 'multi_low': None,
        'results_count': 0, 'error': None,
    }

    queries = [
        ('score', 'desc', 'single_high'),
        ('score', 'asc', 'single_low'),
        ('multicore_score', 'desc', 'multi_high'),
        ('multicore_score', 'asc', 'multi_low'),
    ]

    for sort_field, direction, field in queries:
        url = SEARCH_URL.format(query=query, sort=sort_field, direction=direction)
        page = await browser.get(url)
        await asyncio.sleep(DELAY_PER_QUERY)

        title = await page.evaluate('document.title')
        if 'Just a moment' in title or 'Checking your browser' in title:
            await asyncio.sleep(10)
            title = await page.evaluate('document.title')
            if 'Just a moment' in title:
                result['error'] = f'Cloudflare blocked: {field}'
                return result

        html = await page.get_content()
        parsed = parse_search_results(html, sort_field, direction)

        if parsed:
            result[field] = parsed['single'] if 'single' in field else parsed['multi']
            if field == 'single_high':
                result['results_count'] = parsed['total_count']
        else:
            result['error'] = f'No valid results for {field} ({query})'
            return result

    return result


async def run_scraper(args):
    conn = sqlite3.connect(DB_PATH)
    init_schema(conn)

    cpus = get_cpu_names(conn, source=args.source, limit=args.limit)
    total = len(cpus)
    print(f"Scraping {total} CPUs (source={args.source or 'all'}, limit={args.limit})")
    print(f"Delay: {DELAY_PER_QUERY}s/query, {DELAY_BETWEEN_CPUS}s between CPUs")
    print(f"Filters: min_single={MIN_SINGLE_CORE}, min_multi={MIN_MULTI_CORE}")
    print()

    print("Bypassing Cloudflare...")
    browser = await uc.start(
        headless=False,
        browser_executable_path='/usr/bin/vivaldi',
        browser_args=['--no-first-run', '--no-default-browser-check'],
    )
    page = await browser.get('https://browser.geekbench.com/')
    await asyncio.sleep(8)
    print("Ready.\n")

    success = 0
    failures = 0
    errors = []
    t_start = time.time()

    for i, (cpu_id, cpu_name) in enumerate(cpus, 1):
        query = sanitize_query(cpu_name)
        print(f"[{i}/{total}] {cpu_name} → '{query}'", end=' ', flush=True)

        t0 = time.time()
        result = await scrape_cpu(browser, cpu_id, cpu_name)
        elapsed = time.time() - t0

        if result['error']:
            print(f"✗ {result['error']} ({elapsed:.1f}s)")
            failures += 1
            errors.append((cpu_name, result['error']))
        else:
            print(f"✓ s:{result['single_high']}/{result['single_low']} "
                  f"m:{result['multi_high']}/{result['multi_low']} "
                  f"({result['results_count']} results, {elapsed:.1f}s)")
            success += 1
            conn.execute("""
                INSERT INTO geekbench_search (cpu_id, cpu_name, single_high, single_low,
                                              multi_high, multi_low, results_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (cpu_id, cpu_name, result['single_high'], result['single_low'],
                  result['multi_high'], result['multi_low'], result['results_count']))
            conn.commit()

        if i < total:
            await asyncio.sleep(DELAY_BETWEEN_CPUS)

    elapsed_total = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"Done: {success}/{total} success, {failures}/{total} failed")
    print(f"Time: {elapsed_total/3600:.1f}h ({elapsed_total/60:.0f}min), "
          f"Avg: {elapsed_total/max(total,1):.1f}s/CPU")
    if errors:
        print(f"\nFailed:")
        for name, err in errors[:10]:
            print(f"  - {name}: {err}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")

    conn.close()
    browser.stop()


def main():
    parser = argparse.ArgumentParser(description="Scrape Geekbench 6 search results")
    parser.add_argument("--limit", type=int, help="Limit to first N CPUs")
    parser.add_argument("--source", choices=["notebookcheck", "vray", "geekbench"])
    args = parser.parse_args()
    asyncio.run(run_scraper(args))


if __name__ == "__main__":
    main()
