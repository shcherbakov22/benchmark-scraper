#!/usr/bin/env python3
"""
Normalize and clean scraped Notebookcheck CPU data.

Fixes:
  - notebookcheck_url duplicate prefix
  - Cores_Threads → split into cores / threads
  - L2_Cache_L3_Cache → split into l2_cache_mb / l3_cache_mb
  - MHz_-_Turbo → split into base_mhz / boost_mhz
  - Perf_Rating → parse to float (percentage)
  - Graphics_Card → null out wrong "UHD Graphics 750" defaults
  - Architecture → infer from codename/series when null
  - 64_Bit → rename to is_64bit
  - TDP_Turbo → rename to tdp_turbo_watt
  - Drop Days_old (stale on re-scrape)
  - Drop AI_NPU / AI_Chip (all-null in current dataset)
  - Rename all keys to snake_case
"""

import json
import re
import sys
from pathlib import Path

# Patterns for cache sizes: "96MB + 384MB", "32MB + 24MB", "22MB", "512KB + 3MB", "512KB"
CACHE_RE = re.compile(
    r"(?:(\d+(?:\.\d+)?)\s*(KB|MB|GB))"  # group 1: value, group 2: unit
    r"(?:\s*\+\s*"
    r"(\d+(?:\.\d+)?)\s*(KB|MB|GB))?"     # group 3: value, group 4: unit
)

# Cores/Threads: "96/192", "18/18", "1/1"
CORES_RE = re.compile(r"(\d+)/(\d+)")

# MHz range: "2500 \u2011 5100" (non-breaking hyphen), "3400 \u2011 3900", or single "3000"
MHZ_RE = re.compile(r"(\d+)\s*[‑\-–]\s*(\d+)")

# Perf_Rating: "~69.250%", "~3014%", "~95.550%", "~0.150%", or plain number 5.9
PERF_RE = re.compile(r"~?([\d.]+)%?")

# Codenames that indicate ARM
ARM_CODENAMES = {
    "cortex-a", "cortex-m", "cortex-x", "cortex-i", "cortex-e",
    "kryo", "exynos", "kirin", "snapdragon", "dimensity",
    "apple", "m1", "m2", "m3", "m4", "m5", "a1", "a12", "a13", "a14", "a15", "a16", "a17",
    "falcon", "maia", "xclipse",
}

# Series that indicate ARM
ARM_SERIES = {
    "m1", "m2", "m3", "m4", "m5", "a1", "a12", "a13", "a14", "a15", "a16", "a17",
    "snapdragon", "kirin", "exynos", "dimensity", "tensilica", "mt", "helio",
}

# Names that indicate ARM
ARM_NAME_PATTERNS = [
    r"apple\s+m\d", r"apple\s+a\d", r"snapdragon", r"kirin", r"exynos",
    r"dimensity", r"mt[68]\d+", r"helio", r"tensilica", r"rk\d+",
    r"mediatek", r"mali", r"cortex",
]


def to_snake(key: str) -> str:
    """Convert Notebookcheck column names to clean snake_case."""
    replacements = {
        "cpu_type": "cpu_type",
        "Pos": "rank",
        "name": "name",
        "notebookcheck_id": "nb_id",
        "notebookcheck_url": "nb_url",
        "Codename": "codename",
        "Series": "series",
        "L2_Cache_L3_Cache": "cache",  # will be split, original dropped
        "TDP_Watt": "tdp_watt",
        "TDP_Turbo": "tdp_turbo_watt",
        "MHz_-_Turbo": "mhz",  # will be split, original dropped
        "Cores_Threads": "cores_threads",  # will be split, original dropped
        "Process_nm": "process_nm",
        "Architecture": "architecture",
        "64_Bit": "is_64bit",
        "AI_NPU_TOPS_INT8": "ai_npu_tops",
        "AI_Chip_TOPS_INT8": "ai_chip_tops",
        "Days_old": "days_old",
        "Graphics_Card": "graphics_card",
        "Perf_Rating": "perf_rating",
    }
    if key in replacements:
        return replacements[key]
    # Benchmark columns: convert underscores and hyphens to snake_case
    k = key.replace("-", "_").lower().strip("_")
    return k


def parse_cache(raw: str | None) -> tuple[float | None, float | None]:
    """Parse '96MB + 384MB' → (96.0, 384.0) in MB."""
    if not raw or not raw.strip():
        return None, None
    m = CACHE_RE.search(raw)
    if not m:
        return raw, None

    val1, unit1 = float(m.group(1)), (m.group(2) or "MB")
    val2, unit2 = m.group(3), (m.group(4) or unit1)

    def to_mb(v, u):
        if u == "KB":
            return v / 1024
        if u == "GB":
            return v * 1024
        return v

    l2 = to_mb(val1, unit1)
    l3 = to_mb(float(val2), unit2) if val2 else None
    return l2, l3


def parse_cores(raw) -> tuple[int | None, int | None]:
    """Parse '96/192' → (96, 192)."""
    if raw is None:
        return None, None
    if isinstance(raw, (int, float)):
        return int(raw), None
    m = CORES_RE.search(str(raw))
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def parse_mhz(raw) -> tuple[int | None, int | None]:
    """Parse '2500 ‑ 5100' or 3000 → (base, boost)."""
    if raw is None:
        return None, None
    if isinstance(raw, (int, float)):
        return int(raw), None
    s = str(raw).strip()
    m = MHZ_RE.search(s)
    if m:
        return int(m.group(1)), int(m.group(2))
    try:
        return int(float(s)), None
    except (ValueError, TypeError):
        return None, None


def parse_perf_rating(raw) -> float | None:
    """Parse '~69.250%' or 5.9 → percentage float (0-100 scale)."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    m = PERF_RE.search(str(raw))
    if m:
        return float(m.group(1))
    return None


def is_arm_cpu(cpu: dict) -> bool:
    """Heuristic to detect ARM architecture."""
    # Check codename
    c = (cpu.get("codename") or "").lower()
    if c and any(k in c for k in ARM_CODENAMES):
        return True
    # Check series
    s = (cpu.get("series") or "").lower()
    if s and any(k in s for k in ARM_SERIES):
        return True
    # Check name patterns
    n = (cpu.get("name") or "").lower()
    if any(re.search(p, n) for p in ARM_NAME_PATTERNS):
        return True
    return False


def fix_graphics_card(cpu: dict) -> None:
    """Null out wrong 'UHD Graphics 750' defaults.
    
    UHD Graphics 750 is a Notebookcheck placeholder that appears on ~589 CPUs
    where actual iGPU data is missing. It shows up on AMD, Apple, Qualcomm,
    Samsung, and old Intel CPUs. Only keep it for 11th/12th gen Intel Core
    non-F CPUs that actually have it.
    """
    gc = cpu.get("graphics_card")
    if gc != "UHD Graphics 750":
        return

    name = (cpu.get("name") or "").lower()
    
    # Non-Intel Core: always wrong (placeholder)
    if "intel" not in name:
        cpu["graphics_card"] = None
        return
    if "core" not in name and "ultra" not in name:
        # Xeon, Celeron, Pentium, Atom — placeholder
        cpu["graphics_card"] = None
        return
    
    # Intel F-series: no iGPU
    if re.search(r"\d+f\b", name):
        cpu["graphics_card"] = None
        return
    
    # Extreme Edition (X-series): different iGPU or none
    if re.search(r"\d+x\b", name):
        cpu["graphics_card"] = None
        return
    
    # Extract model number to determine generation
    # i7-11700 → 11700, i5-12400 → 12400, i7-9700 → 9700, i7-750 → 750
    m = re.search(r"(\d{4,5})", name)
    if m:
        model = int(m.group(1))
        if len(m.group(1)) == 5:
            gen = model // 1000  # 11700 → 11, 12400 → 12
        else:
            gen = model // 1000  # 9700 → 9, 750 → 0
        # UHD 750 existed on 11th gen. Keep for 11th/12th gen only.
        if gen < 11:
            cpu["graphics_card"] = None
            return
    else:
        # No model number found — placeholder
        cpu["graphics_card"] = None
        return


def fix_architecture(cpu: dict) -> None:
    """Infer architecture when null."""
    if cpu.get("architecture"):
        return
    name = (cpu.get("name") or "").lower()
    # ARM detection
    if is_arm_cpu(cpu):
        cpu["architecture"] = "ARM"
        return
    # x86: Intel/AMD/Nvidia (Tegra Spark)/Qualcomm (old)
    if any(k in name for k in ("intel", "amd", "nvidia", "ryzen", "core", "xeon", "pentium", "celeron", "athlon", "turion", "opteron")):
        cpu["architecture"] = "x86"
        return
    # Very old 32-bit, likely x86
    if cpu.get("is_64bit") == 0:
        cpu["architecture"] = "x86"
        return
    # Leave as null if truly unknown (e.g. NXP embedded chips)


def clean_cpu(cpu: dict) -> dict:
    """Clean and normalize a single CPU record."""
    out = {}

    # --- Core identity ---
    out["cpu_type"] = cpu.get("cpu_type")
    out["rank"] = cpu.get("Pos")
    out["name"] = cpu.get("name")
    out["nb_id"] = cpu.get("notebookcheck_id")
    # Fix duplicate URL prefix
    url = cpu.get("notebookcheck_url") or ""
    url = url.replace("https://www.notebookcheck.net/https://www.notebookcheck.net/",
                      "https://www.notebookcheck.net/")
    out["nb_url"] = url

    # --- Specs ---
    out["codename"] = cpu.get("Codename")
    out["series"] = cpu.get("Series")

    # Cache
    l2, l3 = parse_cache(cpu.get("L2_Cache_L3_Cache"))
    out["l2_cache_mb"] = l2
    out["l3_cache_mb"] = l3

    out["tdp_watt"] = cpu.get("TDP_Watt")
    out["tdp_turbo_watt"] = cpu.get("TDP_Turbo")

    # MHz
    base, boost = parse_mhz(cpu.get("MHz_-_Turbo"))
    out["base_mhz"] = base
    out["boost_mhz"] = boost

    # Cores
    cores, threads = parse_cores(cpu.get("Cores_Threads"))
    out["cores"] = cores
    out["threads"] = threads

    out["process_nm"] = cpu.get("Process_nm")
    out["architecture"] = cpu.get("Architecture")
    out["is_64bit"] = bool(cpu.get("64_Bit", 0))

    # Drop Days_old (stale), AI_NPU, AI_Chip (all null)
    out["graphics_card"] = cpu.get("Graphics_Card")
    out["perf_rating"] = parse_perf_rating(cpu.get("Perf_Rating"))

    # --- Benchmarks (pass through with snake_case keys) ---
    bench_keys = [k for k in cpu if k not in (
        "cpu_type", "Pos", "name", "notebookcheck_id", "notebookcheck_url",
        "Codename", "Series", "L2_Cache_L3_Cache", "TDP_Watt", "TDP_Turbo",
        "MHz_-_Turbo", "Cores_Threads", "Process_nm", "Architecture", "64_Bit",
        "AI_NPU_TOPS_INT8", "AI_Chip_TOPS_INT8", "Days_old", "Graphics_Card",
        "Perf_Rating",
    )]
    for k in bench_keys:
        out[to_snake(k)] = cpu[k]

    # --- Post-processing fixes ---
    fix_graphics_card(out)
    fix_architecture(out)

    return out


def process_file(input_path: str, output_path: str) -> int:
    """Clean all CPUs in a file. Returns count cleaned."""
    with open(input_path) as f:
        data = json.load(f)

    cleaned = [clean_cpu(cpu) for cpu in data]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2, ensure_ascii=False)

    return len(cleaned)


def main():
    base = Path(__file__).parent
    files = {
        "desktop_cpus.json",
        "laptop_cpus.json",
        "smartphone_cpus.json",
        "all_cpus.json",
    }

    for fname in sorted(files):
        inp = base / fname
        if not inp.exists():
            print(f"[skip] {fname} not found")
            continue

        out = base / f"clean_{fname}"
        count = process_file(str(inp), str(out))
        print(f"[ok] {fname} → clean_{fname} ({count} CPUs)")

    # Summary
    print()
    with open(base / "clean_all_cpus.json") as f:
        all_data = json.load(f)

    # Count columns
    sample = all_data[0]
    spec_cols = [k for k in sample if k not in (
        "cpu_type", "rank", "name", "nb_id", "nb_url",
    ) and not any(
        prefix in k for prefix in (
            "cinebench", "geekbench", "x264", "x265", "truecrypt",
            "blender", "dm_", "zip", "superpi", "wprime", "webxprt",
            "crossmark", "octane", "jetstream", "speedometer",
            "passmark", "passmark_", "browser",
        )
    )]
    print(f"Spec columns: {len(spec_cols)}")
    print(f"  {', '.join(sorted(spec_cols))}")

    bench_cols = [k for k in sample if k not in spec_cols and k not in (
        "cpu_type", "rank", "name", "nb_id", "nb_url",
    )]
    print(f"Benchmark columns: {len(bench_cols)}")


if __name__ == "__main__":
    main()
