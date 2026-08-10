import csv, sys, os
from collections import Counter

csv.field_size_limit(10**9)
REPLAN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .replan
BASE = os.path.join(REPLAN_ROOT, ".tmp")
CSV = f"{BASE}/raw.metagenomic_wgs.csv"
TSV = f"{BASE}/taxid_scientific_name.tsv"
UTX = f"{BASE}/unique_taxids.txt"

# 1) 从主表提取 tax_id 频次
cnt = Counter()
empty = 0
total = 0
with open(CSV, newline="", encoding="utf-8") as f:
    r = csv.reader(f)
    hdr = next(r)
    ti = hdr.index("tax_id")
    si = hdr.index("scientific_name")
    for row in r:
        total += 1
        if len(row) > ti:
            v = row[ti].strip()
            if v == "":
                empty += 1
            else:
                cnt[v] += 1

print(f"=== 主表 tax_id 列 ===")
print(f"总行数 (run 级):      {total:,}")
print(f"非空 tax_id 行:       {total - empty:,}")
print(f"空 tax_id 行:         {empty:,}")
print(f"unique tax_id 数:     {len(cnt):,}")

# 2) 与 unique_taxids.txt 对比
utx = set()
with open(UTX, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            utx.add(line)
print(f"\n=== 与 unique_taxids.txt 对比 ===")
print(f"unique_taxids.txt 行数: {len(utx):,}")
print(f"主表 unique ⊆ txt?      {set(cnt) <= utx}")
print(f"主表有但 txt 无:        {len(set(cnt) - utx):,}")
print(f"txt 有但主表无:         {len(utx - set(cnt)):,}")

# 3) 频次 top 25（含 scientific_name）
sn = {}
with open(TSV, encoding="utf-8") as f:
    next(f)
    for line in f:
        p = line.rstrip("\n").split("\t")
        if len(p) >= 2:
            sn[p[0]] = p[1]
print(f"\n=== tax_id 频次 TOP 25（含已映射 scientific_name）===")
print(f"{'tax_id':<12}{'rows':>12}  scientific_name")
for tid, c in cnt.most_common(25):
    print(f"{tid:<12}{c:>12,}  {sn.get(tid, '?')}")

# 4) metagenome 占比（scientific_name 含 metagenome）
mg = sum(c for tid, c in cnt.items() if "metagenome" in (sn.get(tid, "")).lower())
mg_u = sum(1 for tid in cnt if "metagenome" in (sn.get(tid, "")).lower())
print(f"\n=== metagenome 类型覆盖（按 scientific_name 含 'metagenome'）===")
print(f"unique 中 metagenome 类: {mg_u:,} / {len(cnt):,}  ({100*mg_u/len(cnt):.1f}%)")
print(f"行级 metagenome 类:      {mg:,} / {total:,}  ({100*mg/total:.1f}%)")

# 5) 映射覆盖
mapped = sum(1 for tid in cnt if tid in sn)
print(f"\n=== scientific_name 映射覆盖 ===")
print(f"主表 unique 中已映射:    {mapped:,} / {len(cnt):,}")
