#!/usr/bin/env python3
"""
从 ENA Portal API 按年份拉取 metagenomic + WGS 的 run 元数据, 并合并去重。

选取条件:
  - first_public 落在指定年份区间 (默认 2020-01-01 .. 2026-08-01)
  - library_source = "METAGENOMIC"
  - library_strategy = "WGS"

提取字段 (read_run 可直接返回, 共 14 列):
  run_accession, sample_accession, study_accession(project),
  country, location, collection_date, first_public(发布日期,也用于筛选), tax_id,
  host, host_tax_id, instrument_platform, instrument_model,
  library_layout, read_count(raw_reads)

分页策略 (重要):
  ENA 的 search 接口不支持深度 offset 分页, 取第 2 页 (offset>=100000) 会返回
  HTTP 400。因此本脚本不用 offset, 而是对日期区间做二分切分: 每片结果 <LIMIT
  就一次取完; 若触顶 (返回 LIMIT 条, 说明还有更多), 则把日期区间对半拆成两片
  递归继续。这样每片都是单次请求, 既不触发 400, 也不会漏数据。

存储:
  - 逐年中间结果写 .tmp/ena_runs_YYYY.jsonl (JSON Lines, 流式写入, 内存恒定)
  - 合并结果写 .tmp/raw.metagenomic_wgs.csv
  - 运行日志写 .log/ena_fetch.log
  - 断点续跑: 某年 .jsonl 已存在则跳过; 写入用 .tmp 临时文件, 完成后 rename,
    避免中途崩溃留下半截文件被误当作完整结果。

说明:
  - continent 不在 read_run 字段中, 需后续由 country 推导 (本脚本不处理)
  - location 为经纬度坐标 (latlon), 非地名文本
  - 年份末段 2026 只到 2026-08-01
  - 各年 first_public 区间互不重叠, 二分切分边界也严格不重叠, 故合并无需去重

用法:
  python ena_fetch_runs.py                  # 全量 2020..2026
  python ena_fetch_runs.py 2020             # 只跑 2020
  python ena_fetch_runs.py 2020,2021        # 指定年份
  python ena_fetch_runs.py --force 2020     # 强制重抓已存在的年份
"""
import urllib.request
import urllib.parse
import urllib.error
import json
import csv
import time
import sys
import os
import re
from datetime import datetime, timedelta

BASE = "https://www.ebi.ac.uk/ena/portal/api/search"
DATE_FIELD = "first_public"   # 用于筛选时间区间的字段
FIELDS = [
    "run_accession", "sample_accession", "study_accession",
    "country", "location", "collection_date", "first_public", "tax_id",
    "host", "host_tax_id", "instrument_platform", "instrument_model",
    "library_layout", "read_count",
]
LIMIT = 100000          # 单请求最大返回数 (ENA 上限)
SLEEP = 0.05            # 请求间小停顿, 礼貌一点
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(ROOT, ".tmp")
LOG_DIR = os.path.join(ROOT, ".log")
MERGED_CSV = os.path.join(TMP_DIR, "raw.metagenomic_wgs.csv")
DATE_FMT = "%Y-%m-%d"


def year_ranges(start_year, end_year, final_end="2026-08-01"):
    """返回 [(year, start, end), ...]; 仅 2026 截断到 final_end, 其余为完整年。"""
    ranges = []
    for y in range(start_year, end_year + 1):
        end = final_end if y == 2026 else f"{y}-12-31"
        ranges.append((y, f"{y}-01-01", end))
    return ranges


def make_query(start, end):
    return (f'({DATE_FIELD}>={start} AND {DATE_FIELD}<={end}) '
            f'AND library_source="METAGENOMIC" AND library_strategy="WGS"')


def fetch_page(query):
    """单次请求 (offset 恒为 0), 带重试。返回记录列表。"""
    params = {
        "result": "read_run",
        "query": query,
        "fields": ",".join(FIELDS),
        "format": "JSON",
        "limit": str(LIMIT),
        "offset": "0",
    }
    url = BASE + "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ena-fetch/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"page fetch failed after retries: {last_err}")


def collect_range(start, end, f, log):
    """对 [start,end] 区间查询; 触顶则二分日期递归。记录逐条写入文件句柄 f。"""
    q = make_query(start, end)
    data = fetch_page(q)
    if len(data) < LIMIT:
        for r in data:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return len(data)
    # 触顶: 本片还有更多数据, 二分日期区间继续 (不使用 offset)
    d0 = datetime.strptime(start, DATE_FMT)
    d1 = datetime.strptime(end, DATE_FMT)
    if (d1 - d0).days <= 0:
        # 已拆到单日仍触顶, 接受截断并告警 (实际日均量远小于 LIMIT, 一般不会到这)
        for r in data:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        log(f"  [WARN] 区间 {start}..{end} 触顶 {LIMIT} 且无法再拆分, 可能截断")
        return len(data)
    mid = d0 + (d1 - d0) // 2
    mid_next = (mid + timedelta(days=1)).strftime(DATE_FMT)
    del data  # 释放内存再递归
    n1 = collect_range(start, mid.strftime(DATE_FMT), f, log)
    n2 = collect_range(mid_next, end, f, log)
    return n1 + n2


def fetch_year(year, start, end, log, force=False):
    final = os.path.join(TMP_DIR, f"ena_runs_{year}.jsonl")
    tmp = final + ".tmp"
    if not force and os.path.exists(final) and os.path.getsize(final) > 2:
        log(f"  year {year}: 已存在 {final}, 跳过 (--force 可重抓)")
        return
    t0 = time.time()
    with open(tmp, "w", encoding="utf-8") as f:
        total = collect_range(start, end, f, log)
    os.replace(tmp, final)  # 原子替换, 避免半截文件
    log(f"  year {year}: 共 {total} runs, 用时 {time.time()-t0:.1f}s -> {final}")


def merge_all(log):
    """读取所有 .jsonl 中间文件, 流式写出合并 CSV (各区间不重叠, 无需去重)。"""
    n = 0
    with open(MERGED_CSV, "w", newline="", encoding="utf-8") as cf:
        w = csv.DictWriter(cf, fieldnames=FIELDS)
        w.writeheader()
        for fn in sorted(os.listdir(TMP_DIR)):
            if not re.match(r"ena_runs_\d{4}\.jsonl$", fn):
                continue
            with open(os.path.join(TMP_DIR, fn), encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    r = json.loads(line)
                    w.writerow({k: r.get(k, "") for k in FIELDS})
                    n += 1
    log(f"合并后总行数 (run 数): {n}")
    log(f"已写出合并文件: {MERGED_CSV}")


def main():
    args = sys.argv[1:]
    force = "--force" in args
    years_arg = [a for a in args if a != "--force"]
    year_list = [int(x) for x in years_arg[0].split(",")] if years_arg else list(range(2020, 2027))
    start_year, end_year = min(year_list), max(year_list)

    os.makedirs(TMP_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    # 清理旧版 .json 中间文件 (扩展名已改为 .jsonl)
    for fn in os.listdir(TMP_DIR):
        if re.match(r"ena_runs_\d{4}\.json$", fn):
            try:
                os.remove(os.path.join(TMP_DIR, fn))
            except OSError:
                pass

    log_path = os.path.join(LOG_DIR, "ena_fetch.log")
    logf = open(log_path, "a", encoding="utf-8")

    def log(msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        logf.write(line + "\n")
        logf.flush()

    log(f"=== START (years={year_list}, date_field={DATE_FIELD}, force={force}) ===")
    t0 = time.time()
    for (y, s, e) in year_ranges(start_year, end_year):
        if y not in year_list:
            continue
        log(f"--- year {y}: {s} .. {e} ---")
        t1 = time.time()
        fetch_year(y, s, e, log, force=force)
        log(f"--- year {y} 完成, 用时 {time.time()-t1:.1f}s ---")
    merge_all(log)
    log(f"=== DONE 总用时 {time.time()-t0:.1f}s ===")
    logf.close()


if __name__ == "__main__":
    main()
