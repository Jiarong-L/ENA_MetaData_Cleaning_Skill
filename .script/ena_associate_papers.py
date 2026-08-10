#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ENA 项目 → 关联论文 采集 + PaperSource 标注 + 全文下载  (Replan.md §2.1 + §2.2 + §2.3)
=====================================================================================
通用脚本, 实现 Replan.md 步骤 2 的三小节:
  §2.1  爬取 ENA study 自述 (study_title / center_name / study_description) —— 强源
  §2.2  搜索关联论文 + 标注 PaperSource (high / low / missing)
         · 先用项目编号查 Europe PMC (指名道姓, 命中即 high)
         · 查不到才用 study_title/description 做 free-text 搜 EPMC
         · free-text 候选过"作者单位过滤": 对上=high / 有单位但不对=missing(丢弃) / 无单位=low(人工)
         · 每篇论文同时捕获 fullTextUrlList -> full_text_urls / full_text_available (供 §2.3)
  §2.3  全文下载 (可选, **默认关**)
         · 从 project_literature.jsonl 取 high 论文, 下载 EPMC free 全文 (优先 JATS XML)
         · 落 --out/fulltext/<pmid>.<xml|html>

用法
----
  # 1) 按日期切一小批 (first_public == 该日期的唯一 project_accession)
  python ena_associate_papers.py --phase all  --batch-date 2026-07-31
  # 2) 只跑某一阶段
  python ena_associate_papers.py --phase study --batch-date 2026-07-31
  python ena_associate_papers.py --phase lit   --batch-date 2026-07-31
  # 3) §2.3 全文下载 (默认仅 high 论文, 上限 5 篇)
  python ena_associate_papers.py --phase fulltext --batch-date 2026-07-31
  #   测试/演示: 把范围放宽到任何有 free 全文的候选 (含 low/missing)
  python ena_associate_papers.py --phase fulltext --fulltext-scope any --fulltext-limit 3
  # 4) 直接给项目清单 (每行一个 project_accession, 优先级高于 --batch-date)
  python ena_associate_papers.py --phase lit --acc-file my_accs.txt
  # 5) 生产模式: 输出指向 .tmp/ (仍只读 --src)
  python ena_associate_papers.py --phase all --out .tmp --src <canonical.csv>

输入
----
  --src       合并表 CSV (默认 .tmp/metagenomic_wgs.typed.csv, **只读**)
              需要列: project_accession, first_public

输出 (全部落在 --out 内, 默认 .tmp/)
------------------------------------------------
  batch_<date>.tsv          项目清单            (仅 --batch-date 模式)
  project_study_meta.json   §2.1 ENA study 自述
  project_literature.jsonl  §2.2 关联论文 + PaperSource + full_text_urls  (每行一个项目记录)
  associate_stats.json      汇总统计
  fulltext/                 §2.3 下载的全文 (仅 --phase fulltext)
  fulltext_stats.json       §2.3 下载统计

约束
----
  · 本脚本**只读取 --src**, 绝不修改源文件或 .replan 之外的任何文件。
  · 默认 --out 在 .replan/.tmp 内; 生产时如需指向外部主表, 用 --src 指定, --out 仍落 .replan/.tmp。
  · 断点续跑: study 阶段只补缺失 accession; lit 阶段按 project_accession 去重 (jsonl 已存在则跳过)。
  · 小批测试时建议 --limit N 限制项目数, 避免长时联网。
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

# ---------------------------------------------------------------- 路径默认
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../.replan
DEF_SRC  = os.path.join(ROOT, ".tmp/metagenomic_wgs.typed.csv")
DEF_OUT  = os.path.join(ROOT, ".tmp")
LOG_DIR  = os.path.join(ROOT, ".log")

def _replan_log(msg):
    """追加一行运行日志到 .log/run_YYYY-MM-DD.log（失败静默，不影响主流程）。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        lp = os.path.join(LOG_DIR, "run_%s.log" % datetime.now().strftime("%Y-%m-%d"))
        with open(lp, "a", encoding="utf-8") as _f:
            _f.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))
    except Exception:
        pass

ENA_API = "https://www.ebi.ac.uk/ena/portal/api/search"
EPMC    = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
UA = {"User-Agent": "ena-associate-papers/1.0"}

# ---------------------------------------------------------------- 词典
STOP = {"study","studies","metagenome","metagenomic","metagenomes","genome",
        "genomic","genomes","sequence","sequences","sequencing","raw","reads",
        "read","samples","sample","project","projects","analysis","analyses",
        "data","using","based","from","with","human","mouse","soil","water",
        "microbiome","microbial","community","communities","diversity","profile",
        "profiling","characterization","characterisation","comparative","survey",
        "isolate","isolates","bacterial","bacteria","viral","virus","fungal",
        "identification","reveals","revealed","associated","different","effects",
        "effect","across","between","within","against","resistance","gene","genes",
        "wgs","illumina","sequencing","dna","rna","analysis"}

GEN = {"institute","university","center","centre","college","school","hospital",
       "laboratory","national","research","science","sciences","health","medical",
       "department","division","institut","univ","of","the","and","for",
       "initiative","project","consortium","foundation","program","microbiome"}

# 国家 / 州级 token 过弱, 不计入"强匹配"; 独特城市 (diego 等) 放行
GEO_STATE = {"california","san","texas","florida","new","york","china","japan",
             "united","states","germany","france","uk","britain","canada","australia",
             "spain","italy","india","brazil","korea","russia"}

# 仅保留"硬机构类型"关键词; 去掉 initiative/consortium/foundation/project 等过泛词
# (否则 DESCRIPTION 里的 "XX Initiative" 会与海量论文单位中的同词误匹配 -> 假 high)
INST_KW = ("university","institute","college","hospital","center","centre",
           "laboratory","academy","school","department")


def log(*a):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), " ".join(str(x) for x in a)), flush=True)


# ================================================================ 批次抽取
def extract_batch(src, batch_date):
    """first_public == batch_date 的唯一 project_accession。"""
    accs = {}
    with open(src, encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            fp = (row.get("first_public") or "").strip()
            if fp == batch_date:
                pa = (row.get("project_accession") or "").strip()
                if pa:
                    accs.setdefault(pa, fp)
    return accs


def load_acc_file(path):
    accs = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            a = line.strip()
            if a:
                accs[a] = "(from-file)"
    return accs


# ================================================================ §2.1 ENA study
def fetch_study_batch(accessions):
    """ENA portal result=study, 一次最多 ~100 accession。多则分批。"""
    all_recs = {}
    B = 80
    for i in range(0, len(accessions), B):
        chunk = accessions[i:i+B]
        q = " OR ".join('accession="%s"' % a for a in chunk)
        params = urllib.parse.urlencode({
            "result": "study", "query": q, "format": "json",
            "fields": "study_title,center_name,description,accession"})
        url = ENA_API + "?" + params
        for att in range(4):
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.loads(r.read().decode())
                for rr in (data if isinstance(data, list) else []):
                    acc = rr.get("accession")
                    if acc:
                        all_recs[acc] = {
                            "study_title": (rr.get("study_title") or "").replace("_", " ").strip(),
                            "center_name": (rr.get("center_name") or "").strip(),
                            "study_description": (rr.get("description") or "").replace("_", " ").strip(),
                        }
                break
            except Exception as e:
                log("  study err att%d: %s" % (att+1, e)); time.sleep(1.0)
    return all_recs


def phase_study(accs, out_dir, force=False):
    log("=== §2.1 ENA study 自述 ===")
    meta_path = os.path.join(out_dir, "project_study_meta.json")
    recs = {}
    if os.path.exists(meta_path) and not force:
        with open(meta_path, encoding="utf-8") as f:
            recs = json.load(f)
    todo = [a for a in accs if a not in recs]
    if todo:
        log("  待拉取 %d / 已有 %d" % (len(todo), len(recs)))
        got = fetch_study_batch(todo)
        recs.update(got)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(recs, f, ensure_ascii=False, indent=1)
    missing = [a for a in accs if a not in recs]
    log("  有记录 %d / 无记录 %d" % (len(recs), len(missing)))
    if missing:
        log("  缺:", missing)
    return recs


# ================================================================ §2.2 EPMC + 单位过滤
def epmc_search(q, n=10):
    params = urllib.parse.urlencode({"query": q, "format": "json",
                                     "resultType": "core", "pageSize": str(n)})
    for _ in range(3):
        try:
            req = urllib.request.Request(EPMC + "?" + params, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                d = json.loads(r.read().decode())
            return d.get("hitCount", 0), d.get("resultList", {}).get("result", [])
        except Exception as e:
            log("    epmc err: %s" % e); time.sleep(1.0)
    return -1, []


def get_affils(paper):
    out = []
    for a in paper.get("authorList", {}).get("author", []):
        for af in a.get("authorAffiliationDetailsList", {}).get("authorAffiliation", []):
            v = af.get("affiliation") if isinstance(af, dict) else str(af)
            if v:
                out.append(v)
    return out


def center_tokens(center):
    toks = re.findall(r"[A-Za-z]{4,}", (center or "").replace(";", " ").replace(",", " "))
    return [t for t in toks if t.lower() not in GEN and t.lower() not in STOP]


def strong_center_tokens(center):
    """center_name 中的独特机构/城市 token (排除通用学术词 + 国家/州级)。"""
    return {t for t in center_tokens(center) if t.lower() not in GEO_STATE and len(t) >= 4}


def desc_inst_entities(desc):
    """DESCRIPTION 中的实体机构名 (Capitalized … + 机构关键词)。"""
    phrases = re.findall(r"[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*\s+(?:" +
                         "|".join(INST_KW) + r")", desc or "")
    return [p.strip() for p in phrases if len(p) >= 8]


def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).strip()


def match_affil(affils, strong_tokens, desc_phrases):
    """强匹配: 单位含项目独特机构/城市 token, 或含 DESCRIPTION 实体机构名。"""
    for af in affils:
        afl = norm(af)
        for tok in strong_tokens:
            if len(tok) >= 4 and tok.lower() in afl:
                return True, tok
        for ph in desc_phrases:
            pn = norm(ph)
            if len(pn) >= 6 and pn in afl:
                return True, ph
    return False, None


def paper_record(p, papersource, matched=None, aff=None):
    ft = p.get("fullTextUrlList", {})
    urls = []
    for u in ft.get("fullTextUrl", []):
        urls.append({"url": u.get("url"), "style": u.get("documentStyle"),
                     "avail": u.get("availability"), "source": u.get("source")})
    abstract = re.sub(r"<[^>]+>", " ", p.get("abstractText") or "").strip()
    return {
        "pmid": p.get("pmid"), "pmcid": p.get("pmcid"), "doi": p.get("doi"),
        "title": (p.get("title") or "")[:200],
        "journal": (p.get("journalInfo") or {}).get("journal", {}).get("title"),
        "year": p.get("pubYear"),
        "authors": (p.get("authorString") or "")[:400],
        "abstract": abstract[:4000],
        "paper_affiliations": aff or [],
        "matched_token": matched,
        "papersource": papersource,
        "full_text_urls": urls,            # EPMC fullTextUrlList (供 §2.3 全文下载判定)
        "full_text_available": bool(urls),
    }


def process_one(acc, meta, freetext_n):
    rec = {"project_accession": acc, "strategy": "", "accession_hit": False,
           "query": "", "hitCount": 0, "papers": []}
    # ---- 1) accession-first (最准, 指名道姓) ----
    for fld in ("PROJECT_ID", "BIOPROJECT", "ACCESSION"):
        h, res = epmc_search("%s:%s" % (fld, acc), 5)
        if h and h > 0:
            rec["accession_hit"] = True
            rec["strategy"] = "accession"
            rec["query"] = "%s:%s" % (fld, acc)
            rec["hitCount"] = len(res)
            for p in res[:5]:
                rec["papers"].append(paper_record(p, "high", matched="(accession-linked)"))
            return rec
    # ---- 2) free-text (描述搜索, 需单位过滤) ----
    title = meta.get("study_title", "")
    desc  = meta.get("study_description", "")
    center= meta.get("center_name", "")
    if len(title) >= 12:
        q = '"' + title + '"'
    elif desc:
        q = desc[:140]
    elif center:
        q = center
    else:
        q = title
    rec["query"] = q
    rec["strategy"] = "freetext"
    h, res = epmc_search(q, freetext_n)
    rec["hitCount"] = h if h > 0 else 0
    strong = strong_center_tokens(center)
    desc_ph = desc_inst_entities(desc)
    high = low = missing = 0
    for p in res:
        affils = get_affils(p)
        ok, tok = match_affil(affils, strong, desc_ph)
        if ok:
            ps = "high"; high += 1
        elif affils:
            ps = "missing"; missing += 1      # 有单位但完全对不上 → 噪声, 丢弃
        else:
            ps = "low"; low += 1              # 无单位信息 → 无法验证, 交人工
        rec["papers"].append(paper_record(p, ps, matched=(tok if ok else None), aff=affils))
    rec["_counts"] = {"high": high, "low": low, "missing": missing}
    return rec


def phase_lit(meta, out_dir, limit=None, freetext_n=20):
    log("=== §2.2 EPMC + 作者单位过滤 ===")
    lit_path = os.path.join(out_dir, "project_literature.jsonl")
    # 断点续跑: 已存在的 project_accession 跳过
    done = set()
    if os.path.exists(lit_path):
        with open(lit_path, encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line).get("project_accession"))
                except Exception:
                    pass
    accs = [a for a in meta if a not in done]
    if limit:
        accs = accs[:limit]
    stats = {"projects": 0, "accession_hit": 0, "freetext": 0, "with_hits": 0,
             "high_total": 0, "low_total": 0, "missing_total": 0, "errs": 0}
    if not accs:
        log("  全部已处理, 无需重跑")
        return stats
    with open(lit_path, "a", encoding="utf-8") as fo:
        for acc in accs:
            try:
                rec = process_one(acc, meta.get(acc, {}), freetext_n)
            except Exception as e:
                rec = {"project_accession": acc, "strategy": "ERR",
                       "error": str(e)[:200], "papers": []}
            stats["projects"] += 1
            if rec.get("accession_hit"):
                stats["accession_hit"] += 1
            elif rec.get("strategy") == "freetext":
                stats["freetext"] += 1
            if rec.get("hitCount", 0) > 0:
                stats["with_hits"] += 1
            c = rec.get("_counts")
            if c:
                stats["high_total"] += c["high"]
                stats["low_total"] += c["low"]
                stats["missing_total"] += c["missing"]
            if rec.get("strategy") == "ERR":
                stats["errs"] += 1
            cc = c or {}
            log("  %s strat=%s hit=%s papers=%d high=%s low=%s missing=%s" % (
                acc, rec.get("strategy"), rec.get("hitCount"),
                len(rec.get("papers", [])), cc.get("high", "-"),
                cc.get("low", "-"), cc.get("missing", "-")))
            rec.pop("_counts", None)   # 内部计数, 不写入交付 schema
            fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
            time.sleep(0.3)
    stats_path = os.path.join(out_dir, "associate_stats.json")
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=1)
    log("DONE §2.2 stats=%s", stats)
    return stats


# ================================================================ §2.3 全文下载 (可选, 默认关)
def fetch_url(url):
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except Exception as e:
            log("    dl err: %s" % e); time.sleep(1.0)
    return None


def _is_spa_shell(data):
    """EPMC 文章页现在是 JS 单页应用: 返回 <title>Europe PMC</title> 的空壳, 无正文。
    这种 HTML 无提取价值, 须跳过。"""
    head = data[:3000].lower()
    return b"<title>europe pmc" in head and b"<article" not in head and b"<?xml" not in head


def fulltext_content(p, free):
    """返回 (bytes, ext)。优先级: EPMC REST JATS XML > 出版商 PDF(真实全文) > HTML(若为SPA则弃)。
    注: EPMC 现已不再暴露 JATS XML (REST 404 / ?report=xml 返回SPA壳), 实际可得的只有出版商 PDF。"""
    # 1) EPMC REST JATS XML (若文章在全文子集内)
    pmcid = p.get("pmcid")
    if pmcid and pmcid.upper().startswith("PMC"):
        num = pmcid[3:]
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/%s/fullTextXML" % num
        data = fetch_url(url)
        if data and len(data) > 500 and not _is_spa_shell(data):
            return data, "xml"
    # 2) fullTextUrlList: 优先 pdf (真实全文, 二制), 其次 html(但若SPA则弃)
    pdf = next((u for u in free if u.get("style") == "pdf"), None)
    if pdf:
        data = fetch_url(pdf.get("url"))
        if data and len(data) > 500 and not _is_spa_shell(data):
            return data, "pdf"
    html = next((u for u in free if u.get("style") == "html"), None)
    if html:
        data = fetch_url(html.get("url"))
        if data and len(data) > 500 and not _is_spa_shell(data):
            return data, "html"
    return None, None


def phase_fulltext(out_dir, scope="high", limit=5):
    """§2.3 全文下载: 从 project_literature.jsonl 取候选, 下载 free 全文到 fulltext/。
    scope=high 仅 high 论文 (符合 §2.3 口径); scope=any 用于测试/演示 (含 low/missing 中可用的)。"""
    lit_path = os.path.join(out_dir, "project_literature.jsonl")
    if not os.path.exists(lit_path):
        sys.exit("缺少 project_literature.jsonl, 先跑 --phase lit")
    ft_dir = os.path.join(out_dir, "fulltext")
    os.makedirs(ft_dir, exist_ok=True)
    # EPMC fullTextUrlList 的 availability 可能是 "free" / "Open access" (都可下载)
    FREE_AVAIL = {"free", "open access"}
    stats = {"scanned_projects": 0, "candidates": 0, "attempted": 0,
             "ok": 0, "no_free": 0, "failed": 0, "skipped_scope": 0, "skipped_limit": 0}
    downloaded = 0
    with open(lit_path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            stats["scanned_projects"] += 1
            for p in rec.get("papers", []):
                ps = p.get("papersource")
                if scope == "high" and ps != "high":
                    stats["skipped_scope"] += 1
                    continue
                free = [u for u in (p.get("full_text_urls") or [])
                        if (u.get("avail") or "").strip().lower() in FREE_AVAIL]
                if not free:
                    stats["no_free"] += 1
                    continue
                stats["candidates"] += 1
                if downloaded >= limit:
                    stats["skipped_limit"] += 1
                    continue
                stats["attempted"] += 1
                content, ext = fulltext_content(p, free)
                if not content:
                    stats["failed"] += 1
                    continue
                name = (p.get("pmid") or p.get("pmcid") or "art").replace("/", "_")
                fp = os.path.join(ft_dir, "%s.%s" % (name, ext))
                with open(fp, "wb") as o:
                    o.write(content)
                stats["ok"] += 1
                downloaded += 1
                log("    dl %s -> %s (%d bytes)" % (name, ext, len(content)))
                time.sleep(0.2)
    sp = os.path.join(out_dir, "fulltext_stats.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=1)
    log("DONE §2.3 fulltext stats=%s" % stats)
    return stats


# ================================================================ main
def main():
    ap = argparse.ArgumentParser(description="ENA project → associated papers (Replan §2.1+§2.2)")
    ap.add_argument("--src", default=DEF_SRC, help="合并表 CSV (只读)")
    ap.add_argument("--out", default=DEF_OUT, help="输出目录 (默认 .tmp)")
    ap.add_argument("--batch-date", help="first_public == 该日期的唯一 project_accession 作为批次")
    ap.add_argument("--acc-file", help="直接给 project_accession 清单 (每行一个)")
    ap.add_argument("--phase", choices=["study", "lit", "all", "fulltext"], default="all")
    ap.add_argument("--limit", type=int, default=None, help="限制处理项目数 (测试用)")
    ap.add_argument("--force-study", action="store_true", help="强制重拉 study (忽略缓存)")
    ap.add_argument("--freetext-n", type=int, default=20, help="free-text 候选池大小")
    ap.add_argument("--fulltext-scope", choices=["high", "any"], default="high",
                    help="§2.3 全文下载范围: high=仅 high 论文(默认); any=含 low/missing 中可用的(测试用)")
    ap.add_argument("--fulltext-limit", type=int, default=5, help="§2.3 全文下载上限 (测试用)")
    args = ap.parse_args()
    _replan_log("ena_associate_papers --phase %s --src %s --out %s"
                % (args.phase, args.src, args.out))

    os.makedirs(args.out, exist_ok=True)

    if args.phase == "fulltext":
        phase_fulltext(args.out, scope=args.fulltext_scope, limit=args.fulltext_limit)
        return

    # ---- 解析批次 ----
    if args.acc_file:
        accs = load_acc_file(args.acc_file)
        log("项目清单(文件): %d" % len(accs))
    elif args.batch_date:
        accs = extract_batch(args.src, args.batch_date)
        # 写清单
        bp = os.path.join(args.out, "batch_%s.tsv" % args.batch_date)
        with open(bp, "w", encoding="utf-8") as o:
            for a, fp in sorted(accs.items()):
                o.write("%s\t%s\n" % (a, fp))
        log("批次(日期 %s): %d 项目 -> %s" % (args.batch_date, len(accs), bp))
    else:
        sys.exit("必须给 --batch-date 或 --acc-file")

    if args.limit:
        accs_items = dict(list(accs.items())[:args.limit])
    else:
        accs_items = accs

    if args.phase in ("study", "all"):
        meta = phase_study(accs_items, args.out, force=args.force_study)
    else:
        # lit 阶段需要 meta; 从缓存读
        mp = os.path.join(args.out, "project_study_meta.json")
        meta = json.load(open(mp, encoding="utf-8")) if os.path.exists(mp) else {}

    if args.phase in ("lit", "all"):
        phase_lit(meta, args.out, limit=args.limit, freetext_n=args.freetext_n)


if __name__ == "__main__":
    main()
