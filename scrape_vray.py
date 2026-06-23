#!/usr/bin/env python3
"""Scrape V-Ray Benchmark CPU leaderboard via public API.

API: https://benchmark.chaos.com/api/vray/v6/configs/vray
No auth required. Returns JSON with CPU name, cores, scores.
~1087 CPUs, paginated (size=50 per page).
"""

import json
import time
import urllib.request
import urllib.error

API_URL = "https://benchmark.chaos.com/api/vray/v6/configs/vray"
PAGE_SIZE = 50
DELAY = 1  # seconds between requests
MAX_RETRIES = 3


def fetch_page(index, retries=MAX_RETRIES):
    """Fetch one page of the V-Ray CPU leaderboard."""
    url = f"{API_URL}?size={PAGE_SIZE}&index={index}&order=desc&by=avg"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "Referer": "https://benchmark.chaos.com/vray/v6",
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, OSError) as e:
            print(f"    Retry {attempt+1}/{retries}: {e}")
            if attempt < retries - 1:
                time.sleep(5)
    raise RuntimeError(f"Failed to fetch page {index} after {retries} retries")


def main():
    # Get total count from first page
    print("Fetching first page...")
    first = fetch_page(1)
    total = first["totalCount"]
    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    print(f"Total CPUs: {total}, Pages: {total_pages}")

    all_configs = first["configs"]

    for page in range(2, total_pages + 1):
        print(f"  Page {page}/{total_pages}...")
        time.sleep(DELAY)
        data = fetch_page(page)
        all_configs.extend(data["configs"])

    # Write to JSON
    output = "vray_leaderboard.json"
    with open(output, "w") as f:
        json.dump(all_configs, f, indent=2)
    print(f"\nWrote {len(all_configs)} configs to {output}")

    # Write to TSV for easy inspection
    tsv_output = "vray_leaderboard.tsv"
    with open(tsv_output, "w") as f:
        headers = ["id", "cpu_name", "cpu_cores", "physical_cores", "logical_cores",
                    "mean_score", "median_score", "max_score",
                    "normalised_mean", "normalised_median", "normalised_max",
                    "scores_count"]
        f.write("\t".join(headers) + "\n")
        for c in all_configs:
            cpu = c["cpu"]
            details = cpu.get("details", {})
            row = [
                c["id"],
                cpu["name"],
                cpu["cores"],
                details.get("physicalCores", ""),
                details.get("logicalCores", ""),
                c["meanScore"],
                c["medianScore"],
                c["maxScore"],
                c["normalisedMeanScore"],
                c["normalisedMedianScore"],
                c["normalisedMaxScore"],
                c["scoresCount"],
            ]
            f.write("\t".join(str(v) for v in row) + "\n")
    print(f"Wrote TSV to {tsv_output}")


if __name__ == "__main__":
    main()
