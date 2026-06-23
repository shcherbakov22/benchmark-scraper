#!/usr/bin/env python3
"""
Notebookcheck CPU Benchmark Scraper — Multi-pass strategy

Strategy:
  1. Specs-only pass → get ALL CPUs with specs (no benchmark filtering)
  2. Benchmark passes → scrape each benchmark individually, merge by notebookcheck_id

This avoids Notebookcheck's "show only CPUs with data in selected columns" filter
that drops the list from ~1200 to ~200 when all columns are enabled.
"""

import json
import re
import sys
import time
import argparse
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.notebookcheck.net"

# ── Spec columns (always enabled) ──────────────────────────────────────
ALL_SPEC_COLUMNS = [
    "cpu_fullname", "codename", "series", "l2cache", "l3cache",
    "tdp", "tdp_turbo", "mhz", "turbo_mhz", "cores", "threads",
    "technology", "architecture", "64bit", "ai_npu_tops_int8",
    "ai_chip_total_tops_int8", "daysold", "gpu_name",
]

# ── Benchmark columns grouped by test ──────────────────────────────────
# Each group: (label, [form_field_names])
# We scrape each group separately to avoid filtering.
BENCHMARK_GROUPS = [
    ("cinebench_r10",   ["cinebench10_s", "cinebench10_m"]),
    ("cinebench_r15",   ["cinebench_r15_single", "cinebench_r15_multi"]),
    ("cinebench_r20",   ["cinebench_r20_single", "cinebench_r20_multi"]),
    ("cinebench_r23",   ["cinebench_r23_single", "cinebench_r23_multi"]),
    ("cinebench_2024",  ["cinebench_2024_single", "cinebench_2024_multi"]),
    ("cinebench_2026",  ["cinebench_2026_single", "cinebench_2026_multi"]),
    ("geekbench_2",     ["geekbench2"]),
    ("geekbench_3",     ["geekbench3_single", "geekbench3_multi"]),
    ("geekbench_4",     ["geekbench4_1_single", "geekbench4_1_multi"]),
    ("geekbench_5",     ["geekbench5_1_single", "geekbench5_1_multi"]),
    ("geekbench_6",     ["geekbench6_2_single", "geekbench6_2_multi"]),
    ("3dmark",          ["3dmark06cpu"]),
    ("x264",            ["x264_pass1", "x264_pass2"]),
    ("x265",            ["x265"]),
    ("truecrypt",       ["truecrypt_aes", "truecrypt_twofish", "truecrypt_serpent"]),
    ("blender",         ["blender", "blender3_cpu"]),
    ("7zip",            ["7-zip_single", "7-zip_multiple"]),
    ("superpi",         ["superpi1m", "superpi32m"]),
    ("wprime",          ["wprime_32", "wprime_1024"]),
    ("browser_tests",   ["sunspider", "octane2", "jetstream2", "jetstream2_2",
                         "speedometer", "webxprt3", "webxprt4"]),
    ("composite",       ["passmark_cpu", "crossmark"]),
]

# Single page containing ALL CPU types (desktop, laptop, smartphone)
# Row classes indicate type: desk_*=desktop, smartphone_*=mobile, even/odd=laptop
PAGE_SLUG = "Mobile-Processors-Benchmark-List.2436.0.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


# ── URL builder ────────────────────────────────────────────────────────
def build_url(slug: str, benchmark_fields: list[str] | None = None,
              include_archived: bool = False) -> str:
    """Build URL with spec columns + optional benchmark columns."""
    params = {
        "archive": 1 if include_archived else 0,
        "condensed": 0,
        "gpubenchmarks": 0,
        "id": 0,
        "perfrating": 1,
        "or": 0,
        "showCount": 0,
        "showBars": 1,
        "showPercent": 0,
        "settings_class_array[]": 1,
    }
    for col in ALL_SPEC_COLUMNS:
        params[col] = 1
    if benchmark_fields:
        for col in benchmark_fields:
            params[col] = 1
    return f"{BASE_URL}/{slug}?{urlencode(params, doseq=True)}"


# ── HTML parsing ───────────────────────────────────────────────────────
def clean_value(raw: str) -> str:
    return raw.strip().replace("\u00a0", " ").replace("\n", " ").strip()


def parse_table(html: str) -> tuple[list[str], list[dict]]:
    """
    Parse the benchmark table.
    Returns (column_names, cpu_list) where each cpu dict maps column_name → value.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="sortable")
    if not table:
        return [], []

    # First header row has all individual column labels
    header_rows = [
        r for r in table.find_all("tr")
        if r.get("class") and "header" in r.get("class", [])
    ]
    if not header_rows:
        return [], []

    header_cells = header_rows[0].find_all("td")
    column_names: list[str] = []
    for cell in header_cells:
        name = clean_value(cell.get_text())
        safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
        safe = re.sub(r"_+", "_", safe).strip("_")
        column_names.append(safe)

    # Data rows (anything not a header)
    data_rows = [
        r for r in table.find_all("tr")
        if r.get("class") and "header" not in r.get("class", [])
    ]

    expected = len(column_names)
    cpus = []
    skipped = 0
    for row in data_rows:
        cells = row.find_all("td")
        if len(cells) != expected:
            skipped += 1
            continue

        # Detect CPU type from row class
        row_cls = " ".join(row.get("class", []))
        if "desk" in row_cls:
            cpu_type = "desktop"
        elif "smartphone" in row_cls:
            cpu_type = "smartphone"
        else:
            cpu_type = "laptop"

        cpu: dict = {"cpu_type": cpu_type}
        for i, cell in enumerate(cells):
            raw = clean_value(cell.get_text())

            # Cell 1 = Model (CPU name + link)
            if i == 1:
                cpu["name"] = raw
                link = cell.find("a")
                if link and link.get("href"):
                    href = link["href"]
                    match = re.search(r"(\d+)\.0\.html", href)
                    if match:
                        cpu["notebookcheck_id"] = int(match.group(1))
                    cpu["notebookcheck_url"] = f"{BASE_URL}/{href}"
                continue

            # Parse numeric values
            if raw and raw != "-":
                try:
                    numeric = re.sub(r"[n*].*$", "", raw).strip()
                    cpu[column_names[i]] = (
                        float(numeric) if "." in numeric else int(numeric)
                    )
                except (ValueError, AttributeError):
                    cpu[column_names[i]] = raw
            else:
                cpu[column_names[i]] = None

        cpus.append(cpu)

    if skipped:
        print(f"  [!] Skipped {skipped} malformed rows", file=sys.stderr)

    return column_names, cpus


# ── Merge logic ────────────────────────────────────────────────────────
def merge_cpu_data(base: list[dict], extra: list[dict],
                   column_names: list[str]) -> list[dict]:
    """
    Merge benchmark data from `extra` into `base` by notebookcheck_id.
    Only copies benchmark columns (skips Pos, name, notebookcheck_*).
    """
    # Build index of extra CPUs by ID
    extra_by_id: dict[int, dict] = {}
    for cpu in extra:
        nid = cpu.get("notebookcheck_id")
        if nid:
            extra_by_id[nid] = cpu

    # Columns to skip during merge (metadata, not data)
    skip_cols = {"Pos", "name", "notebookcheck_id", "notebookcheck_url"}
    benchmark_cols = [c for c in column_names if c not in skip_cols]

    merged_count = 0
    for cpu in base:
        nid = cpu.get("notebookcheck_id")
        if nid and nid in extra_by_id:
            for col in benchmark_cols:
                val = extra_by_id[nid].get(col)
                if val is not None:
                    cpu[col] = val
                    merged_count += 1

    print(f"  Merged {merged_count} benchmark values into {len(base)} CPUs")
    return base


# ── Core scrape function ───────────────────────────────────────────────
def scrape_all(include_archived: bool = False, delay: float = 3.0) -> list[dict]:
    """
    Multi-pass scrape for the unified CPU list:
      1. Specs-only pass → base CPU list (all types)
      2. Benchmark passes → merge each benchmark group
    """
    # ── Pass 1: Specs only ─────────────────────────────────────────
    url = build_url(PAGE_SLUG, benchmark_fields=None, include_archived=include_archived)
    print("[scrape] Pass 1 — Specs only")
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    _, base_cpus = parse_table(resp.text)
    print(f"[scrape] Base: {len(base_cpus)} CPUs")

    if not base_cpus:
        print("[scrape] [!] No CPUs found!", file=sys.stderr)
        return []

    # ── Pass 2..N: Benchmark groups ───────────────────────────────
    for group_label, fields in BENCHMARK_GROUPS:
        print(f"[scrape] Pass — {group_label} ({len(fields)} fields)", end=" ... ")
        sys.stdout.flush()

        time.sleep(delay)
        url = build_url(PAGE_SLUG, benchmark_fields=fields,
                        include_archived=include_archived)
        resp = requests.get(url, headers=HEADERS, timeout=60)
        if resp.status_code != 200:
            print(f"HTTP {resp.status_code}, skipping")
            continue

        col_names, extra_cpus = parse_table(resp.text)
        base_cpus = merge_cpu_data(base_cpus, extra_cpus, col_names)
        print(f"{len(extra_cpus)} rows fetched")

    return base_cpus


# ── CLI ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Scrape Notebookcheck CPU benchmarks (multi-pass)"
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived/discontinued CPUs",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory to save output JSON files",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="Seconds between requests (default: 3.0)",
    )
    args = parser.parse_args()

    # Scrape the unified list
    all_cpus = scrape_all(args.include_archived, args.delay)

    # Split by type and save
    types = {"desktop": [], "laptop": [], "smartphone": []}
    for cpu in all_cpus:
        t = cpu.get("cpu_type", "laptop")
        types[t].append(cpu)

    output_files = {
        "desktop": "desktop_cpus.json",
        "laptop": "laptop_cpus.json",
        "smartphone": "smartphone_cpus.json",
    }

    for cpu_type, filename in output_files.items():
        output_path = f"{args.output_dir}/{filename}"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(types[cpu_type], f, indent=2, ensure_ascii=False)

    # Also save combined
    combined_path = f"{args.output_dir}/all_cpus.json"
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(all_cpus, f, indent=2, ensure_ascii=False)

    # Summary
    print(f"\n{'=' * 50}")
    print(f"Total: {len(all_cpus)} CPUs scraped")
    for cpu_type in ("desktop", "laptop", "smartphone"):
        cpus = types[cpu_type]
        print(f"  {cpu_type}: {len(cpus)} CPUs → {output_files[cpu_type]}")
        if cpus:
            bench_cols = [c for c in cpus[0]
                          if c not in ("Pos", "name", "notebookcheck_id",
                                       "notebookcheck_url", "cpu_type")]
            filled = sum(1 for c in bench_cols if cpus[0].get(c) is not None)
            print(f"    Sample: {cpus[0]['name']} ({filled}/{len(bench_cols)} benchmarks)")
    print(f"  combined: all_cpus.json")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
