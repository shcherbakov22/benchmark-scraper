-- ============================================================
-- CPU Benchmarks — SQLite Schema (Normalized)
-- cpus → identity + specs
-- notebookcheck → NB benchmark scores
-- vray → V-Ray benchmark scores
-- geekbench → Geekbench 6 (browser.geekbench.com) scores
-- ============================================================

-- -----------------------------------------------------------
-- CPUs — one row per unique CPU (identity + specs only)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS cpus (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- external IDs
    nb_id           INTEGER UNIQUE,
    vray_id         INTEGER,
    geekbench_id    INTEGER UNIQUE,

    -- identity
    name            TEXT NOT NULL,
    cpu_type        TEXT NOT NULL DEFAULT 'laptop',  -- desktop, laptop, smartphone
    nb_url          TEXT,

    -- specs
    codename        TEXT,
    series          TEXT,
    cores           INTEGER,
    threads         INTEGER,
    base_mhz        INTEGER,
    boost_mhz       INTEGER,
    l2_cache_mb     REAL,
    l3_cache_mb     REAL,
    process_nm      INTEGER,
    is_64bit        BOOLEAN,
    tdp_watt        INTEGER,
    tdp_turbo_watt  INTEGER,
    graphics_card   TEXT,
    architecture    TEXT,

    -- ranking (from Notebookcheck)
    rank            INTEGER,
    perf_rating     REAL,

    -- metadata
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cpus_name ON cpus (name);
CREATE INDEX IF NOT EXISTS idx_cpus_type ON cpus (cpu_type);
CREATE INDEX IF NOT EXISTS idx_cpus_cores ON cpus (cores);
CREATE INDEX IF NOT EXISTS idx_cpus_rank ON cpus (rank);
CREATE INDEX IF NOT EXISTS idx_cpus_perf_rating ON cpus (perf_rating);
CREATE INDEX IF NOT EXISTS idx_cpus_nb_id ON cpus (nb_id);

-- -----------------------------------------------------------
-- Notebookcheck benchmarks — one row per CPU
-- All 20+ benchmark groups from Notebookcheck
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS notebookcheck (
    cpu_id          INTEGER PRIMARY KEY REFERENCES cpus(id) ON DELETE CASCADE,

    -- Cinebench R10
    cinebench_r10_s REAL,
    cinebench_r10_m REAL,

    -- Cinebench R15
    cinebench_r15_s REAL,
    cinebench_r15_m REAL,

    -- Cinebench R20
    cinebench_r20_s REAL,
    cinebench_r20_m REAL,

    -- Cinebench R23
    cinebench_r23_s REAL,
    cinebench_r23_m REAL,

    -- Cinebench 2024
    cinebench_2024_s REAL,
    cinebench_2024_m REAL,

    -- Cinebench 2026
    cinebench_2026_s REAL,
    cinebench_2026_m REAL,

    -- Geekbench 2
    geekbench_2 REAL,

    -- Geekbench 3
    geekbench_3_s REAL,
    geekbench_3_m REAL,

    -- Geekbench 4
    geekbench_4_s REAL,
    geekbench_4_m REAL,

    -- Geekbench 5
    geekbench_5_s REAL,
    geekbench_5_m REAL,

    -- Geekbench 6
    geekbench_6_s REAL,
    geekbench_6_m REAL,

    -- 3DMark
    dm_3dmark06 REAL,

    -- x264
    x264_p1 REAL,
    x264_p2 REAL,

    -- x265
    x265 REAL,

    -- TrueCrypt
    truecrypt_aes REAL,
    truecrypt_twofish REAL,
    truecrypt_serpent REAL,

    -- Blender
    blender_old REAL,
    blender_v33 REAL,

    -- 7-Zip
    zip7_s REAL,
    zip7_m REAL,

    -- SuperPI
    superpi_1m REAL,
    superpi_32m REAL,

    -- wPrime
    wprime_32 REAL,
    wprime_1024 REAL,

    -- Browser tests
    sunspider REAL,
    octane_v2 REAL,
    jetstream_2 REAL,
    jetstream_2_2 REAL,
    speedometer REAL,
    webxprt_3 REAL,
    webxprt_4 REAL,
    crossmark REAL,

    -- PassMark (from Notebookcheck)
    passmark_mobile REAL,

    -- metadata
    scraped_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------
-- V-Ray Benchmark — one row per CPU
-- From: benchmark.chaos.com/api/vray/v6/configs/vray
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS vray (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cpu_id          INTEGER NOT NULL REFERENCES cpus(id) ON DELETE CASCADE,
    vray_id         INTEGER UNIQUE,

    mean_score      INTEGER,
    median_score    INTEGER,
    max_score       INTEGER,
    normalised_mean INTEGER,
    normalised_median INTEGER,
    normalised_max  INTEGER,
    scores_count    INTEGER,

    -- metadata
    scraped_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_vray_cpu_id ON vray (cpu_id);

-- -----------------------------------------------------------
-- Geekbench 6 Benchmark — one row per CPU
-- From: browser.geekbench.com/processor-benchmarks.json
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS geekbench (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cpu_id          INTEGER NOT NULL REFERENCES cpus(id) ON DELETE CASCADE,
    geekbench_id    INTEGER UNIQUE,

    single_core     REAL,
    multi_core      REAL,
    samples         INTEGER,
    family          TEXT,
    icon            TEXT,

    -- metadata
    scraped_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_geekbench_cpu_id ON geekbench (cpu_id);

-- -----------------------------------------------------------
-- Scrape log
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS scrape_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,           -- notebookcheck, vray, geekbench
    scraped_at      TEXT NOT NULL DEFAULT (datetime('now')),
    cpus_count      INTEGER,
    status          TEXT NOT NULL DEFAULT 'success',
    notes           TEXT
);

-- ============================================================
-- Column mapping: TSV column → notebookcheck table column
-- ============================================================
-- cinebench_r10_32bit_single              → cinebench_r10_s
-- cinebench_r10_32bit_multi               → cinebench_r10_m
-- cinebench_r15_cpu_single_64bit          → cinebench_r15_s
-- cinebench_r15_cpu_multi_64bit           → cinebench_r15_m
-- cinebench_r20_single                    → cinebench_r20_s
-- cinebench_r20                           → cinebench_r20_m
-- cinebench_r23_single_core               → cinebench_r23_s
-- cinebench_r23_multi_core                → cinebench_r23_m
-- cinebench_2024_cpu_single_core          → cinebench_2024_s
-- cinebench_2024_cpu_multi_core           → cinebench_2024_m
-- cinebench_2026_cpu_single_thread        → cinebench_2026_s
-- cinebench_2026_cpu_multi                → cinebench_2026_m
-- geekbench_2                             → geekbench_2
-- geekbench_3_32_bit_single_core_score    → geekbench_3_s
-- geekbench_3_32_bit_multi_core_score     → geekbench_3_m
-- geekbench_4_4_64_bit_single_core_score  → geekbench_4_s
-- geekbench_4_4_64_bit_multi_core_score   → geekbench_4_m
-- geekbench_5_5_single_core               → geekbench_5_s
-- geekbench_5_5_multi_core                → geekbench_5_m
-- geekbench_6_7_single_core               → geekbench_6_s
-- geekbench_6_7_multi_core                → geekbench_6_m
-- 3dmark06_cpu                            → dm_3dmark06
-- x264_pass_1                             → x264_p1
-- x264_pass_2                             → x264_p2
-- x265                                    → x265
-- truecrypt_aes                           → truecrypt_aes
-- truecrypt_twofish                       → truecrypt_twofish
-- truecrypt_serpent                       → truecrypt_serpent
-- blender                                 → blender_old
-- blender_v3_3_classroom_cpu              → blender_v33
-- 7_zip_single                            → zip7_s
-- 7_zip                                   → zip7_m
-- superpi_1m                              → superpi_1m
-- superpi_32m                             → superpi_32m
-- wprime_32                               → wprime_32
-- wprime_1024                             → wprime_1024
-- sunspider_1_0_total_score               → sunspider
-- octane_v2_total_score                   → octane_v2
-- jetstream_2                             → jetstream_2
-- jetstream_2_2_2_total                   → jetstream_2_2
-- speedometer_2_0                         → speedometer
-- webxprt_3                               → webxprt_3
-- webxprt_4_overall                       → webxprt_4
-- crossmark_overall                       → crossmark
-- passmark_performancetest_mobile_v1_cpu_tests → passmark_mobile

-- ============================================================
-- Common queries
-- ============================================================
-- Full CPU view with all benchmarks:
-- SELECT c.*, n.*, v.*, g.* FROM cpus c
--   LEFT JOIN notebookcheck n ON n.cpu_id = c.id
--   LEFT JOIN vray v ON v.cpu_id = c.id
--   LEFT JOIN geekbench g ON g.cpu_id = c.id
-- WHERE c.cpu_type = 'desktop' ORDER BY c.rank;
--
-- Top 10 by V-Ray score:
-- SELECT c.name, v.mean_score, v.normalised_mean
-- FROM cpus c JOIN vray v ON v.cpu_id = c.id
-- ORDER BY v.mean_score DESC LIMIT 10;
