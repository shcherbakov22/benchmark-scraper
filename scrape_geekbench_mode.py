#!/usr/bin/env python3
"""
Geekbench scraper — Recent results + mode scoring.
Fetches recent submissions, deduplicates by system, filters VMs/outliers,
computes mode score from ±2% bins.

One request per CPU (~10s), ~12h for full dataset.
3 parallel workers supported.

Usage: python3 scrape_geekbench_mode.py [--limit N] [--resume] [--worker W] [--workers M]
"""
import sqlite3
import json
import re
import time
import sys
import urllib.parse
from curl_cffi import requests
from bs4 import BeautifulSoup

DB_PATH = "benchmarks.sqlite"
OUTPUT = "geekbench_mode_results.json"
DELAY = 0.5
MAX_RETRIES = 3
RETRY_DELAY = 2
WORKER_ID = None
TOTAL_WORKERS = 1

VM_KEYWORDS = ['vmware', 'virtual', 'kvm', 'qemu', 'hyper-v', 'virtualbox', 'xen', 'proxmox']

def sanitize_name(name: str) -> str:
    q = name
    q = re.sub(r'^Intel\s+Core\s+', '', q, flags=re.I)
    q = re.sub(r'^Apple\s+', '', q, flags=re.I)
    q = re.sub(r'^AMD\s+(Ryzen|EPYC|Threadripper)\s+', r'\1 ', q, flags=re.I)
    q = re.sub(r'^Qualcomm\s+', '', q, flags=re.I)
    q = re.sub(r'Core\s+Ultra\s+(\d+)\s+(\d+[A-Z]*)\s*Plus\s*$', r'Core Ultra \1 \2', q, flags=re.I)
    q = re.sub(r'^(M\d+)\s+(Pro|Max)\s+\d+-Core\s*$', r'\1 \2', q, flags=re.I)
    q = re.sub(r'^(M\d+)\s*$', r'\1', q, flags=re.I)
    q = re.sub(r'\s+(\d+)\s*(Core|Cores?)\s*$', '', q, flags=re.I)
    q = re.sub(r'Snapdragon\s+X2\s+.*$', r'Snapdragon X2 Elite', q, flags=re.I)
    q = re.sub(r'Snapdragon\s+X\s+(Elite|Plus)\s+.*$', r'Snapdragon X \1', q, flags=re.I)
    q = re.sub(r'[^\w\s\-]', ' ', q)
    q = re.sub(r'\s+', ' ', q).strip()
    return q

def fetch_url(url: str) -> requests.Response:
    for attempt in range(MAX_RETRIES):
        r = requests.get(url, impersonate="safari", timeout=20)
        if r.status_code == 200:
            return r
        if r.status_code in (403, 429):
            wait = RETRY_DELAY * (2 ** attempt) + (WORKER_ID or 0) * 0.5
            print(f"  ⏳ HTTP {r.status_code}, retry in {wait:.0f}s...", flush=True)
            time.sleep(wait)
        else:
            return r
    return r

def compute_mode(scores: list, bin_pct=0.02) -> int:
    """Compute mode using percentage-based bins."""
    if not scores:
        return 0
    avg = sum(scores) / len(scores)
    bin_size = max(1, int(avg * bin_pct))
    bins = {}
    for s in scores:
        bin_key = (s // bin_size) * bin_size
        bins.setdefault(bin_key, []).append(s)
    mode_bin = max(bins, key=lambda k: len(bins[k]))
    return sum(bins[mode_bin]) // len(bins[mode_bin])

def scrape_cpu(cpu_id: int, cpu_name: str, db_cores: int) -> dict:
    q = sanitize_name(cpu_name)
    result = {"cpu_id": cpu_id, "cpu_name": cpu_name, "query": q, "db_cores": db_cores}

    url = f"https://browser.geekbench.com/v6/cpu/search?q={urllib.parse.quote(q)}&sort=recent"
    r = fetch_url(url)

    if r.status_code != 200:
        result["error"] = f"http_{r.status_code}"
        return result

    soup = BeautifulSoup(r.text, "html.parser")

    if "no results" in r.text.lower() or "not found" in r.text.lower():
        result["error"] = "no_results"
        return result

    items = soup.select(".list-col-inner")
    if not items:
        result["error"] = "no_items"
        return result

    seen_systems = set()
    valid_singles = []
    valid_multis = []
    filtered_reasons = []

    for item in items:
        scores = item.select(".list-col-text-score")
        single = int(scores[0].get_text(strip=True)) if len(scores) > 0 else 0
        multi = int(scores[1].get_text(strip=True)) if len(scores) > 1 else 0

        model = item.select_one(".list-col-model")
        lines = [l.strip() for l in model.get_text('\n').split('\n') if l.strip()]
        clock_mhz = int(re.search(r'(\d+)', lines[1]).group(1)) if len(lines) > 1 and re.search(r'(\d+)', lines[1]) else 0
        cores = int(re.search(r'(\d+)', lines[2]).group(1)) if len(lines) > 2 and re.search(r'(\d+)', lines[2]) else 0

        sys_link = item.select_one("a[href*='/v6/cpu/']")
        system = sys_link.get_text(strip=True) if sys_link else ""

        # Filters
        if system in seen_systems:
            filtered_reasons.append("dup")
            continue
        seen_systems.add(system)

        if any(kw in system.lower() for kw in VM_KEYWORDS):
            filtered_reasons.append("vm")
            continue

        if db_cores and cores < db_cores:
            filtered_reasons.append(f"low_cores({cores}<{db_cores})")
            continue

        if clock_mhz < 1000 or clock_mhz > 5500:
            filtered_reasons.append(f"bad_clock({clock_mhz})")
            continue

        if single <= 0 or multi <= 0:
            filtered_reasons.append("zero")
            continue

        valid_singles.append(single)
        valid_multis.append(multi)

    result["total_results"] = len(items)
    result["valid_count"] = len(valid_singles)
    result["filtered"] = filtered_reasons

    if not valid_singles:
        result["error"] = "no_valid_results"
        return result

    result["single_mode"] = compute_mode(valid_singles)
    result["multi_mode"] = compute_mode(valid_multis)
    result["single_median"] = sorted(valid_singles)[len(valid_singles) // 2]
    result["multi_median"] = sorted(valid_multis)[len(valid_multis) // 2]
    result["all_singles"] = sorted(valid_singles, reverse=True)
    result["all_multis"] = sorted(valid_multis, reverse=True)

    return result

def main():
    args = sys.argv[1:]
    limit = None
    resume = "--resume" in args

    for i, arg in enumerate(args):
        if arg == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
        elif arg == "--worker" and i + 1 < len(args):
            global WORKER_ID, TOTAL_WORKERS
            WORKER_ID = int(args[i + 1])
        elif arg == "--workers" and i + 1 < len(args):
            TOTAL_WORKERS = int(args[i + 1])

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT c.id, c.name, c.cores FROM cpus c ORDER BY c.id").fetchall()
    conn.close()

    if WORKER_ID is not None and TOTAL_WORKERS > 1:
        rows = [r for i, r in enumerate(rows) if i % TOTAL_WORKERS == WORKER_ID]
        print(f"Worker {WORKER_ID}/{TOTAL_WORKERS}")

    if limit:
        rows = rows[:limit]
    total = len(rows)
    print(f"CPUs to scrape: {total}")

    worker_output = OUTPUT.replace('.json', f'_{WORKER_ID}.json') if WORKER_ID is not None else OUTPUT

    existing = {}
    if resume:
        try:
            with open(worker_output) as f:
                data = json.load(f)
                existing = {r['cpu_id']: r for r in data}
                rows = [r for r in rows if r[0] not in existing]
                total = len(rows)
                print(f"Resuming: {len(existing)} done, {total} remaining")
        except FileNotFoundError:
            pass

    results = list(existing.values())
    success = 0
    failed = 0

    for i, (cpu_id, cpu_name, db_cores) in enumerate(rows, 1):
        t0 = time.time()
        q = sanitize_name(cpu_name)
        print(f"\n[{i}/{total}] {cpu_name} ({db_cores}C) → '{q}'", end="", flush=True)

        result = scrape_cpu(cpu_id, cpu_name, db_cores or 0)
        elapsed = time.time() - t0

        if "error" in result:
            print(f" ✗ {result['error']} ({elapsed:.1f}s)", flush=True)
            failed += 1
        else:
            sm = result.get('single_mode', '?')
            mm = result.get('multi_mode', '?')
            n = result.get('valid_count', 0)
            print(f" ✓ mode: s={sm} m={mm} (n={n}, {elapsed:.1f}s)", flush=True)
            success += 1

        results.append(result)

        if i % 50 == 0:
            with open(worker_output, 'w') as f:
                json.dump(results, f, indent=2)

    with open(worker_output, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n{'='*60}")
    print(f"Done! Valid: {success}, Failed: {failed}")
    print(f"Saved {len(results)} to {worker_output}")

if __name__ == "__main__":
    main()
