#!/usr/bin/env python3
"""Load cleaned Notebookcheck + V-Ray data into SQLite.

Usage:
    python3 load_sqlite.py                    # load everything
    python3 load_sqlite.py --source notebookcheck  # only NB
    python3 load_sqlite.py --source vray      # only V-Ray
    python3 load_sqlite.py --source geekbench # only Geekbench
    python3 load_sqlite.py --db mydb.sqlite   # custom DB path
"""

import argparse
import csv
import json
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "benchmarks.sqlite")

NB_TSV = os.path.join(BASE_DIR, "clean_all_cpus.tsv")
VRAY_JSON = os.path.join(BASE_DIR, "vray_leaderboard.json")
GB_JSON = os.path.join(BASE_DIR, "geekbench_leaderboard.json")
SCHEMA_SQL = os.path.join(BASE_DIR, "schema.sql")


def init_db(db_path):
    """Create tables from schema.sql + apply migrations for existing DBs."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA_SQL) as f:
        conn.executescript(f.read())

    # Migration: add geekbench_id to cpus if not present
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(cpus)")
    columns = [row[1] for row in cursor.fetchall()]
    if "geekbench_id" not in columns:
        print("  Migrating: adding geekbench_id to cpus...")
        cursor.execute("ALTER TABLE cpus ADD COLUMN geekbench_id INTEGER")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_cpus_geekbench_id ON cpus(geekbench_id)")

    conn.commit()
    return conn


def si(val):
    """Safe int."""
    if not val:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def sf(val):
    """Safe float."""
    if not val:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def sb(val):
    """Safe bool."""
    if not val:
        return None
    return str(val).lower() in ("1", "true", "yes", "y")


def load_notebookcheck(conn):
    """Load cleaned Notebookcheck TSV into cpus + notebookcheck tables."""
    if not os.path.exists(NB_TSV):
        print(f"  Skipping: {NB_TSV} not found")
        return 0

    print(f"  Loading {NB_TSV}...")
    cursor = conn.cursor()
    count = 0

    with open(NB_TSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)

    for row in rows:
        nb_id = si(row.get("nb_id"))
        name = (row.get("name") or "").strip()

        # Find or create CPU
        if nb_id:
            cursor.execute("SELECT id FROM cpus WHERE nb_id=?", (nb_id,))
            existing = cursor.fetchone()
        else:
            cursor.execute("SELECT id FROM cpus WHERE name=?", (name,))
            existing = cursor.fetchone()

        if existing:
            cpu_id = existing[0]
        else:
            cursor.execute("""
                INSERT INTO cpus (nb_id, name, cpu_type, nb_url, codename, series,
                                  cores, threads, base_mhz, boost_mhz,
                                  l2_cache_mb, l3_cache_mb, process_nm, is_64bit,
                                  tdp_watt, tdp_turbo_watt, graphics_card, architecture,
                                  rank, perf_rating)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                nb_id, name,
                (row.get("cpu_type") or "laptop").strip(),
                (row.get("nb_url") or "").strip() or None,
                (row.get("codename") or "").strip() or None,
                (row.get("series") or "").strip() or None,
                si(row.get("cores")),
                si(row.get("threads")),
                si(row.get("base_mhz")),
                si(row.get("boost_mhz")),
                sf(row.get("l2_cache_mb")),
                sf(row.get("l3_cache_mb")),
                si(row.get("process_nm")),
                sb(row.get("is_64bit")),
                si(row.get("tdp_watt")),
                si(row.get("tdp_turbo_watt")),
                (row.get("graphics_card") or "").strip() or None,
                (row.get("architecture") or "").strip() or None,
                si(row.get("rank")),
                sf(row.get("perf_rating")),
            ))
            cpu_id = cursor.lastrowid

        # Insert Notebookcheck benchmarks
        nb_map = [
            "cinebench_r10_s", "cinebench_r10_m",
            "cinebench_r15_s", "cinebench_r15_m",
            "cinebench_r20_s", "cinebench_r20_m",
            "cinebench_r23_s", "cinebench_r23_m",
            "cinebench_2024_s", "cinebench_2024_m",
            "cinebench_2026_s", "cinebench_2026_m",
            "geekbench_2",
            "geekbench_3_s", "geekbench_3_m",
            "geekbench_4_s", "geekbench_4_m",
            "geekbench_5_s", "geekbench_5_m",
            "geekbench_6_s", "geekbench_6_m",
            "dm_3dmark06",
            "x264_p1", "x264_p2",
            "x265",
            "truecrypt_aes", "truecrypt_twofish", "truecrypt_serpent",
            "blender_old", "blender_v33",
            "zip7_s", "zip7_m",
            "superpi_1m", "superpi_32m",
            "wprime_32", "wprime_1024",
            "sunspider", "octane_v2",
            "jetstream_2", "jetstream_2_2",
            "speedometer", "webxprt_3", "webxprt_4", "crossmark",
            "passmark_mobile",
        ]
        tsv_map = [
            "cinebench_r10_32bit_single", "cinebench_r10_32bit_multi",
            "cinebench_r15_cpu_single_64bit", "cinebench_r15_cpu_multi_64bit",
            "cinebench_r20_single", "cinebench_r20",
            "cinebench_r23_single_core", "cinebench_r23_multi_core",
            "cinebench_2024_cpu_single_core", "cinebench_2024_cpu_multi_core",
            "cinebench_2026_cpu_single_thread", "cinebench_2026_cpu_multi",
            "geekbench_2",
            "geekbench_3_32_bit_single_core_score", "geekbench_3_32_bit_multi_core_score",
            "geekbench_4_4_64_bit_single_core_score", "geekbench_4_4_64_bit_multi_core_score",
            "geekbench_5_5_single_core", "geekbench_5_5_multi_core",
            "geekbench_6_7_single_core", "geekbench_6_7_multi_core",
            "3dmark06_cpu",
            "x264_pass_1", "x264_pass_2",
            "x265",
            "truecrypt_aes", "truecrypt_twofish", "truecrypt_serpent",
            "blender", "blender_v3_3_classroom_cpu",
            "7_zip_single", "7_zip",
            "superpi_1m", "superpi_32m",
            "wprime_32", "wprime_1024",
            "sunspider_1_0_total_score", "octane_v2_total_score",
            "jetstream_2", "jetstream_2_2_2_total",
            "speedometer_2_0", "webxprt_3", "webxprt_4_overall", "crossmark_overall",
            "passmark_performancetest_mobile_v1_cpu_tests",
        ]

        values = [cpu_id] + [sf(row.get(t)) for t in tsv_map]
        cols = "cpu_id," + ",".join(nb_map)
        phs = ",".join(["?"] * len(values))
        updates = ",".join(f"{c}=excluded.{c}" for c in nb_map)

        cursor.execute(f"""
            INSERT INTO notebookcheck ({cols}) VALUES ({phs})
            ON CONFLICT(cpu_id) DO UPDATE SET {updates}, updated_at=datetime('now')
        """, values)

        count += 1
        if count % 500 == 0:
            print(f"    {count}/{len(rows)}...")

    conn.commit()
    cursor.execute("INSERT INTO scrape_log (source, cpus_count, status) VALUES ('notebookcheck', ?, 'success')", (count,))
    conn.commit()
    print(f"  Loaded {count} CPUs from Notebookcheck")
    return count


def load_vray(conn):
    """Load V-Ray leaderboard JSON into cpus + vray tables."""
    if not os.path.exists(VRAY_JSON):
        print(f"  Skipping: {VRAY_JSON} not found")
        return 0

    print(f"  Loading {VRAY_JSON}...")
    with open(VRAY_JSON) as f:
        configs = json.load(f)

    cursor = conn.cursor()
    count = 0

    for cfg in configs:
        cpu_name = cfg["cpu"]["name"]
        vray_id = cfg["id"]
        details = cfg["cpu"].get("details", {})

        # Find or create CPU
        cursor.execute("SELECT id, nb_id FROM cpus WHERE name=?", (cpu_name,))
        existing = cursor.fetchone()

        if existing:
            cpu_id = existing[0]
            # Link vray_id to existing CPU
            cursor.execute("UPDATE cpus SET vray_id=? WHERE id=?", (vray_id, cpu_id))
        else:
            cursor.execute("""
                INSERT INTO cpus (vray_id, name, cpu_type, cores, threads)
                VALUES (?, ?, 'desktop', ?, ?)
            """, (vray_id, cpu_name, cfg["cpu"]["cores"], details.get("logicalCores")))
            cpu_id = cursor.lastrowid

        # Upsert V-Ray scores
        cursor.execute("""
            INSERT INTO vray (cpu_id, vray_id, mean_score, median_score, max_score,
                              normalised_mean, normalised_median, normalised_max, scores_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(vray_id) DO UPDATE SET
                cpu_id=excluded.cpu_id,
                mean_score=excluded.mean_score, median_score=excluded.median_score,
                max_score=excluded.max_score,
                normalised_mean=excluded.normalised_mean,
                normalised_median=excluded.normalised_median,
                normalised_max=excluded.normalised_max,
                scores_count=excluded.scores_count,
                updated_at=datetime('now')
        """, (cpu_id, vray_id, cfg["meanScore"], cfg["medianScore"], cfg["maxScore"],
              cfg["normalisedMeanScore"], cfg["normalisedMedianScore"], cfg["normalisedMaxScore"],
              cfg["scoresCount"]))

        count += 1
        if count % 200 == 0:
            print(f"    {count}/{len(configs)}...")

    conn.commit()
    cursor.execute("INSERT INTO scrape_log (source, cpus_count, status) VALUES ('vray', ?, 'success')", (count,))
    conn.commit()
    print(f"  Loaded {count} CPUs from V-Ray")
    return count


def load_geekbench(conn):
    """Load Geekbench 6 leaderboard JSON into cpus + geekbench tables."""
    if not os.path.exists(GB_JSON):
        print(f"  Skipping: {GB_JSON} not found")
        return 0

    print(f"  Loading {GB_JSON}...")
    with open(GB_JSON) as f:
        data = json.load(f)

    devices = data.get("devices", [])
    cursor = conn.cursor()
    count = 0

    for dev in devices:
        gb_id = dev["id"]
        cpu_name = dev["name"]
        single_core = dev["score"]
        multi_core = dev["multicore_score"]
        samples = dev["samples"]
        family = dev.get("family", "")
        icon = dev.get("icon", "")

        # Parse description for clock speed and core count
        # e.g. "2.8 GHz (2 cores)" or "3.1 GHz (2 cores / 4 threads)"
        cores = None
        threads = None
        import re
        desc = dev.get("description", "")
        m_cores = re.search(r"(\d+)\s*cores", desc)
        m_threads = re.search(r"(\d+)\s*threads", desc)
        if m_cores:
            cores = int(m_cores.group(1))
        if m_threads:
            threads = int(m_threads.group(1))
        # If no explicit threads, assume cores == threads for simplicity
        if cores and not threads:
            threads = cores

        # Infer brand from icon
        brand = icon if icon else None

        # Find or create CPU
        cursor.execute("SELECT id, nb_id FROM cpus WHERE geekbench_id=?", (gb_id,))
        existing = cursor.fetchone()

        if existing:
            cpu_id = existing[0]
        else:
            # Try to match by name with existing NB/V-Ray CPUs
            # Strip common suffixes for better matching
            clean_name = re.sub(r"\s*\d+-Cores?\s*$", "", cpu_name).strip()
            clean_name = re.sub(r"\s*\(.*\)\s*$", "", clean_name).strip()

            cursor.execute("SELECT id FROM cpus WHERE name=?", (cpu_name,))
            exact_match = cursor.fetchone()

            if exact_match:
                cpu_id = exact_match[0]
                cursor.execute("UPDATE cpus SET geekbench_id=? WHERE id=?", (gb_id, cpu_id))
            elif clean_name != cpu_name:
                # Try fuzzy match
                cursor.execute("SELECT id FROM cpus WHERE name LIKE ?", (f"%{clean_name}%",))
                fuzzy_match = cursor.fetchone()
                if fuzzy_match:
                    cpu_id = fuzzy_match[0]
                    cursor.execute("UPDATE cpus SET geekbench_id=? WHERE id=?", (gb_id, cpu_id))
                else:
                    cursor.execute("""
                        INSERT INTO cpus (geekbench_id, name, cpu_type, cores, threads)
                        VALUES (?, ?, 'desktop', ?, ?)
                    """, (gb_id, cpu_name, cores, threads))
                    cpu_id = cursor.lastrowid
            else:
                cursor.execute("""
                    INSERT INTO cpus (geekbench_id, name, cpu_type, cores, threads)
                    VALUES (?, ?, 'desktop', ?, ?)
                """, (gb_id, cpu_name, cores, threads))
                cpu_id = cursor.lastrowid

        # Upsert Geekbench scores
        cursor.execute("""
            INSERT INTO geekbench (cpu_id, geekbench_id, single_core, multi_core, samples, family, icon)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(geekbench_id) DO UPDATE SET
                cpu_id=excluded.cpu_id,
                single_core=excluded.single_core,
                multi_core=excluded.multi_core,
                samples=excluded.samples,
                family=excluded.family,
                icon=excluded.icon,
                updated_at=datetime('now')
        """, (cpu_id, gb_id, single_core, multi_core, samples, family or None, icon or None))

        count += 1
        if count % 500 == 0:
            print(f"    {count}/{len(devices)}...")

    conn.commit()
    cursor.execute("INSERT INTO scrape_log (source, cpus_count, status) VALUES ('geekbench', ?, 'success')", (count,))
    conn.commit()
    print(f"  Loaded {count} CPUs from Geekbench")
    return count


def main():
    parser = argparse.ArgumentParser(description="Load benchmark data into SQLite")
    parser.add_argument("--source", choices=["notebookcheck", "vray", "geekbench"], help="Load only this source")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    args = parser.parse_args()

    print(f"Database: {args.db}")
    conn = init_db(args.db)

    if args.source == "notebookcheck" or args.source is None:
        load_notebookcheck(conn)
    if args.source == "vray" or args.source is None:
        load_vray(conn)
    if args.source == "geekbench" or args.source is None:
        load_geekbench(conn)

    # Summary
    cursor = conn.cursor()
    cpus_count = cursor.execute("SELECT COUNT(*) FROM cpus").fetchone()[0]
    nb_count = cursor.execute("SELECT COUNT(*) FROM notebookcheck").fetchone()[0]
    vray_count = cursor.execute("SELECT COUNT(*) FROM vray").fetchone()[0]
    gb_count = cursor.execute("SELECT COUNT(*) FROM geekbench").fetchone()[0]
    overlap = cursor.execute("SELECT COUNT(*) FROM cpus WHERE nb_id IS NOT NULL AND vray_id IS NOT NULL").fetchone()[0]

    print(f"\n{'='*50}")
    print(f"Database summary:")
    print(f"  CPUs (total unique):    {cpus_count}")
    print(f"  Notebookcheck scores:   {nb_count}")
    print(f"  V-Ray scores:           {vray_count}")
    print(f"  Geekbench scores:       {gb_count}")
    print(f"  CPUs in both sources:   {overlap}")
    print(f"{'='*50}")

    conn.close()


if __name__ == "__main__":
    main()
