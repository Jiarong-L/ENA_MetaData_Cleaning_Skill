#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ena_taxid_type.py — 批量提取主表 tax_id 的 NCBI taxonomy 信息（scientific_name + type）。

输入（只读）:
  --csv   主表 .tmp/raw.metagenomic_wgs.csv（16 列，含 tax_id 列）
输出:
  --out   .reuse/taxid_type.tsv  (tax_id \t scientific_name \t type \t is_metagenome)
  --backfill  可选：把 type/scientific_name 回填进主表，写到该路径（新文件，不改原表）

批量策略:
  NCBI efetch (db=taxonomy, retmode=xml) 支持逗号分隔多 ID，单批上限 200。
  8,289 个 unique tax_id => ~42 次请求即可全部拿完（非逐条查询）。
  NCBI eutils 无 API key 时限速 3 req/s，本脚本每批 sleep 0.34s 遵守。

type 提取规则（对齐 Replan.md §1.2 lineage 模板）:
  Lineage = "unclassified entries; unclassified sequences; metagenomes; [type: xx metagenomes]; [scientific_name]"
  type = 位于 `metagenomes` 锚点之后、名字形如 "* metagenomes" 的最具体一层
        （如 "host-associated metagenomes" 比 "ecological metagenomes" 更具体 -> 取离 scientific_name 最近者）
  非 metagenome（lineage 不含 metagenomes）=> type = ""（空），scientific_name 仍填 NCBI 实际名。

注意: 本脚本在沙箱内运行需忽略 TLS 拦截（verify=False / curl -k）；生产环境去掉即可。
"""
import argparse
import csv
import gzip
import json
import os
import re
import sys
import time
from datetime import datetime
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

NCBI_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
BATCH = 200
SLEEP = 0.34  # 遵守 NCBI 3 req/s 限速

# 目录基准：本脚本位于 <replan>/.script/，父目录即 replan 根目录
REPLAN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR   = os.path.join(REPLAN_ROOT, ".tmp")
REUSE_DIR = os.path.join(REPLAN_ROOT, ".reuse")
LOG_DIR   = os.path.join(REPLAN_ROOT, ".log")

def _replan_log(msg):
    """追加一行运行日志到 .log/run_YYYY-MM-DD.log（失败静默，不影响主流程）。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        lp = os.path.join(LOG_DIR, "run_%s.log" % datetime.now().strftime("%Y-%m-%d"))
        with open(lp, "a", encoding="utf-8") as _f:
            _f.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def fetch_batch(ids, verify=False, retries=3):
    """逗号分隔批量查询 NCBI efetch，返回 list of dict(tax_id, scientific_name, lineage)."""
    q = urllib.parse.urlencode({
        "db": "taxonomy",
        "id": ",".join(ids),
        "retmode": "xml",
    })
    url = f"{NCBI_EFETCH}?{q}"
    last_err = None
    for attempt in range(retries):
        try:
            ctx = None
            if not verify:
                import ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={"User-Agent": "ena-taxid-type/1.0"})
            with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
                data = r.read()
            return parse_xml(data, ids)
        except Exception as e:  # noqa
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    sys.stderr.write(f"[WARN] batch {ids[0]}..{ids[-1]} failed: {last_err}\n")
    return []


def parse_xml(data, ids):
    out = {}
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        sys.stderr.write(f"[WARN] XML parse error: {e}\n")
        return out
    for taxon in root.iter("Taxon"):
        tid = (taxon.findtext("TaxId") or "").strip()
        if not tid:
            continue
        sci = (taxon.findtext("ScientificName") or "").strip()
        lineage = (taxon.findtext("Lineage") or "").strip()
        out[tid] = {"scientific_name": sci, "lineage": lineage}
    # 缺失的 ID 标记为空（避免后续 KeyError）
    for i in ids:
        out.setdefault(i, {"scientific_name": "", "lineage": ""})
    return out


def extract_type(lineage):
    """从 lineage 字符串提取 * metagenomes 最具体子层。"""
    if not lineage:
        return ""
    parts = [p.strip() for p in lineage.split(";") if p.strip()]
    # 找 metagenomes 锚点
    try:
        anchor = parts.index("metagenomes")
    except ValueError:
        return ""
    # 锚点之后、形如 "* metagenomes" 的层，取最具体（最后一个）
    cand = []
    for p in parts[anchor + 1:]:
        if re.match(r"^.+\s+metagenomes$", p):
            cand.append(p)
    return cand[-1] if cand else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(REPLAN_ROOT, ".tmp/raw.metagenomic_wgs.csv"))
    ap.add_argument("--out", default=os.path.join(REUSE_DIR, "taxid_type.tsv"))
    ap.add_argument("--backfill", default=os.path.join(TMP_DIR, "metagenomic_wgs.typed.csv"),
                    help="回填主表 type/scientific_name 的新文件路径（不改原表）")
    ap.add_argument("--verify", action="store_true", help="启用 TLS 校验（沙箱外使用）")
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 个 unique tax_id（调试）")
    args = ap.parse_args()
    _replan_log("ena_taxid_type --csv %s --out %s" % (args.csv, args.out))

    # 1) 读主表，提取 unique tax_id
    taxids = []
    seen = set()
    with open(args.csv, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        tid_col = "tax_id" if "tax_id" in rd.fieldnames else None
        if tid_col is None:
            sys.stderr.write(f"[ERR] 主表无 tax_id 列; 表头={rd.fieldnames}\n")
            sys.exit(1)
        for row in rd:
            t = (row.get("tax_id") or "").strip()
            if t and t not in seen:
                seen.add(t)
                taxids.append(t)
    sys.stderr.write(f"[info] unique tax_id = {len(taxids)}\n")
    if args.limit:
        taxids = taxids[:args.limit]

    # 2) 批量查询 NCBI
    mapping = {}  # tax_id -> {scientific_name, type, is_metagenome}
    n_batch = 0
    for i in range(0, len(taxids), BATCH):
        chunk = taxids[i:i + BATCH]
        res = fetch_batch(chunk, verify=args.verify)
        for tid in chunk:
            info = res.get(tid, {"scientific_name": "", "lineage": ""})
            lineage = info["lineage"]
            typ = extract_type(lineage)
            is_meta = ("metagenomes" in lineage) and bool(typ)
            mapping[tid] = {
                "scientific_name": info["scientific_name"],
                "type": typ,
                "is_metagenome": is_meta,
            }
        n_batch += 1
        if n_batch % 10 == 0:
            sys.stderr.write(f"[info] 已处理 {min(i+BATCH, len(taxids))}/{len(taxids)} ({n_batch} 批)\n")
        time.sleep(SLEEP)

    # 3) 写 taxid_type.tsv
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    n_meta = sum(1 for v in mapping.values() if v["is_metagenome"])
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["tax_id", "scientific_name", "type", "is_metagenome"])
        for tid in taxids:
            v = mapping[tid]
            w.writerow([tid, v["scientific_name"], v["type"], int(v["is_metagenome"])])
    sys.stderr.write(f"[done] 写出 {len(mapping)} 行 -> {args.out}\n")
    sys.stderr.write(f"[stat] 其中 metagenome 类型 = {n_meta} ({n_meta*100.0/max(1,len(mapping)):.1f}%)\n")

    # 4) 可选回填主表
    if args.backfill:
        backfill_table(args.csv, mapping, args.backfill)
    return mapping


def backfill_table(src_csv, mapping, dst_csv):
    os.makedirs(os.path.dirname(os.path.abspath(dst_csv)), exist_ok=True)
    with open(src_csv, newline="", encoding="utf-8") as fi, \
         open(dst_csv, "w", newline="", encoding="utf-8") as fo:
        rd = csv.DictReader(fi)
        fnames = list(rd.fieldnames)
        # 确保有 type / scientific_name 列（无则插入 tax_id 前）
        if "type" not in fnames:
            idx = fnames.index("tax_id")
            fnames.insert(idx, "type")
        if "scientific_name" not in fnames:
            idx = fnames.index("tax_id")
            fnames.insert(idx, "scientific_name")
        w = csv.DictWriter(fo, fieldnames=fnames)
        w.writeheader()
        n_fill = 0
        for row in rd:
            t = (row.get("tax_id") or "").strip()
            if t in mapping:
                row["scientific_name"] = mapping[t]["scientific_name"]
                row["type"] = mapping[t]["type"]
                n_fill += 1
            w.writerow(row)
    sys.stderr.write(f"[done] 回填主表 {n_fill} 行 -> {dst_csv}\n")


if __name__ == "__main__":
    main()
