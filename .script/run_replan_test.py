#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Replan 流程小批测试 (贴合 Replan.md §2.1 + §2.2 新文档)
======================================================
输入 : .tmp/raw.metagenomic_wgs.csv (canonical, 16 列, project_accession)
批次 : first_public == 2026-07-31  (真实最新一天, 10 个唯一 project_accession)
输出 : 全部落在 .replan/.tmp/
  batch_2026-07-31.tsv        项目清单
  project_study_meta.json      §2.1 ENA study 自述
  project_literature.jsonl     §2.2 关联论文 + PaperSource
  test_stats.json             汇总

§2.2 新逻辑:
  1) 先用项目编号查 EPMC (PROJECT_ID / BIOPROJECT / ACCESSION) -> 命中即 PaperSource=high(accession)
  2) 查不到才用 study_title/description free-text 搜 EPMC
  3) free-text 候选抽作者单位(authorAffiliationDetailsList), 与项目期望单位
     (center_name token + description 实体 token) 匹配:
       对上 -> high(采纳) ; 单位存在但无重叠 -> low ; 无单位 -> low(unknown)
注: 本脚本是"测试用独立实现", 不复用 .script/ena_enrich_projects.py (其实现的是旧版 2.2)。
"""
import csv, json, os, re, sys, time, urllib.parse, urllib.request

REPLAN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .replan
SRC  = os.path.join(REPLAN_ROOT, ".tmp/raw.metagenomic_wgs.csv")
OUT  = os.path.join(REPLAN_ROOT, ".tmp")
BATCH_DATE = "2026-07-31"

os.makedirs(OUT, exist_ok=True)
BATCH_TSV   = os.path.join(OUT, "batch_2026-07-31.tsv")
STUDY_JSON  = os.path.join(OUT, "project_study_meta.json")
LIT_JSONL   = os.path.join(OUT, "project_literature.jsonl")
STATS_JSON  = os.path.join(OUT, "test_stats.json")

ENA_API = "https://www.ebi.ac.uk/ena/portal/api/search"
EPMC    = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

STOP = {"study","studies","metagenome","metagenomic","metagenomes","genome",
        "genomic","genomes","sequence","sequences","sequencing","raw","reads",
        "read","samples","sample","project","projects","analysis","analyses",
        "data","using","based","from","with","human","mouse","soil","water",
        "microbiome","microbial","community","communities","diversity","profile",
        "profiling","characterization","characterisation","comparative","survey",
        "isolate","isolates","bacterial","bacteria","viral","virus","fungal",
        "identification","reveals","revealed","associated","different","effects",
        "effect","across","between","within","against","resistance","gene","genes",
        "metagenomes","wgs","illumina","sequencing","dna","rna","analysis"}

GEN = {"institute","university","center","centre","college","school","hospital",
       "laboratory","national","research","science","sciences","health","medical",
       "department","division","institut","univ","of","the","and","for"}

UA = {"User-Agent": "replan-test/1.0"}

def log(*a):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), " ".join(str(x) for x in a)), flush=True)

# ---------- 批次抽取 ----------
def extract_batch():
    accs = {}
    with open(SRC, encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            fp = (row.get("first_public") or "").strip()
            if fp == BATCH_DATE:
                pa = (row.get("project_accession") or "").strip()
                if pa:
                    accs.setdefault(pa, fp)
    with open(BATCH_TSV, "w", encoding="utf-8") as o:
        for pa, fp in sorted(accs.items()):
            o.write("%s\t%s\n" % (pa, fp))
    log("批次项目数 =", len(accs), "->", BATCH_TSV)
    return list(accs.keys())

# ---------- §2.1 ENA study ----------
def fetch_study_batch(accessions):
    q = " OR ".join('accession="%s"' % a for a in accessions)
    params = urllib.parse.urlencode({
        "result": "study", "query": q, "format": "json",
        "fields": "study_title,center_name,description,accession"})
    url = ENA_API + "?" + params
    for att in range(4):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read().decode())
            return data if isinstance(data, list) else []
        except Exception as e:
            log("  study err att%d: %s" % (att+1, e)); time.sleep(1.0)
    return None

def phase_study(accs):
    log("=== §2.1 ENA study 自述 ===")
    res = fetch_study_batch(accs)
    recs = {}
    if res is None:
        log("  !! study 批次失败"); return recs
    for r in res:
        acc = r.get("accession")
        if acc:
            recs[acc] = {
                "study_title": (r.get("study_title") or "").replace("_"," ").strip(),
                "center_name": (r.get("center_name") or "").strip(),
                "study_description": (r.get("description") or "").replace("_"," ").strip(),
            }
    with open(STUDY_JSON, "w", encoding="utf-8") as f:
        json.dump(recs, f, ensure_ascii=False, indent=1)
    missing = [a for a in accs if a not in recs]
    log("  有记录 %d / 无记录 %d" % (len(recs), len(missing)))
    if missing: log("  缺:", missing)
    return recs

# ---------- §2.2 EPMC + 单位过滤 ----------
def epmc_search(q, n=10):
    params = urllib.parse.urlencode({"query": q, "format": "json",
                                     "resultType": "core", "pageSize": str(n)})
    for _ in range(3):
        try:
            req = urllib.request.Request(EPMC + "?" + params, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                d = json.loads(r.read().decode())
            return d.get("hitCount",0), d.get("resultList",{}).get("result",[])
        except Exception:
            time.sleep(1.0)
    return -1, []

def get_affils(paper):
    out = []
    for a in paper.get("authorList",{}).get("author",[]):
        for af in a.get("authorAffiliationDetailsList",{}).get("authorAffiliation",[]):
            v = af.get("affiliation") if isinstance(af, dict) else str(af)
            if v: out.append(v)
    return out

def center_tokens(center):
    toks = re.findall(r"[A-Za-z]{4,}", (center or "").replace(";"," ").replace(","," "))
    return [t for t in toks if t.lower() not in GEN and t.lower() not in STOP]

def desc_tokens(desc):
    return [w for w in re.findall(r"[A-Za-z]{5,}", (desc or "").lower()) if w not in STOP]

def build_expected(meta):
    return set(center_tokens(meta.get("center_name",""))) | set(desc_tokens(meta.get("study_description","")))

GEO_STATE = {"california","san","texas","florida","new","york","china","japan",
             "united","states","germany","france","uk","britain","canada","australia",
             "spain","italy","india","brazil","korea","russia"}  # 国家/州级过弱, 不计入强匹配; 城市(diego等)放行

def strong_center_tokens(center):
    # center_name 中的独特机构/城市 token (排除通用学术词 + 国家/州级)
    return {t for t in center_tokens(center) if t.lower() not in GEO_STATE and len(t) >= 4}

INST_KW = ("university","institute","college","hospital","center","centre",
           "laboratory","academy","school","foundation","consortium","department",
           "initiative","microbiome")

def desc_inst_entities(desc):
    # DESCRIPTION 中的实体机构名 (Capitalized ... + 机构关键词)
    phrases = re.findall(r"[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*\s+(?:" +
                         "|".join(INST_KW) + r")", desc or "")
    return [p.strip() for p in phrases if len(p) >= 8]

def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).strip()

def match_affil(affils, strong_tokens, desc_phrases):
    # 强匹配: 单位含项目独特机构/城市 token, 或含 DESCRIPTION 实体机构名
    for af in affils:
        afl = norm(af)
        for tok in strong_tokens:
            if len(tok) >= 4 and tok.lower() in afl:
                return True, tok, True, af[:120]
        for ph in desc_phrases:
            pn = norm(ph)
            if len(pn) >= 6 and pn in afl:
                return True, ph, True, af[:120]
    return False, None, False, None

def paper_record(p, papersource, matched=None, aff=None):
    return {
        "pmid": p.get("pmid"), "pmcid": p.get("pmcid"), "doi": p.get("doi"),
        "title": (p.get("title") or "")[:160],
        "journal": (p.get("journalInfo") or {}).get("journal",{}).get("title"),
        "year": p.get("pubYear"),
        "paper_affiliations": aff or [],
        "matched_token": matched,
        "papersource": papersource,
    }

def process_one(acc, meta):
    rec = {"project_accession": acc, "strategy": "", "accession_hit": False,
           "query": "", "hitCount": 0, "papers": []}
    # 1) accession-first
    acc_hit_papers = []
    for fld in ("PROJECT_ID", "BIOPROJECT", "ACCESSION"):
        h, res = epmc_search("%s:%s" % (fld, acc), 5)
        if h and h > 0:
            acc_hit_papers = res; rec["accession_hit"] = True; rec["strategy"]="accession"; rec["query"]="%s:%s"%(fld,acc)
            break
    if acc_hit_papers:
        rec["hitCount"] = len(acc_hit_papers)
        for p in acc_hit_papers[:5]:
            rec["papers"].append(paper_record(p, "high", matched="(accession-linked)"))
        return rec
    # 2) free-text
    title = meta.get("study_title","")
    desc  = meta.get("study_description","")
    center= meta.get("center_name","")
    if len(title) >= 12:
        q = '"' + title + '"'
    elif desc:
        q = desc[:140]
    elif center:
        q = center
    else:
        q = title
    rec["query"] = q
    h, res = epmc_search(q, 10)
    rec["hitCount"] = h if h > 0 else 0
    rec["strategy"] = "freetext"
    strong = strong_center_tokens(center)
    desc_ph = desc_inst_entities(desc)
    high=low=0; adopted=0
    for p in res:
        affils = get_affils(p)
        ok, tok, _, _ = match_affil(affils, strong, desc_ph)
        if ok:
            ps = "high"; high += 1; adopted += 1
        elif affils:
            ps = "low"; low += 1
        else:
            ps = "low"  # 无单位 -> 弱(待人工), 不强行丢弃
            low += 1
        rec["papers"].append(paper_record(p, ps, matched=(tok if ok else None), aff=affils))
    rec["_counts"] = {"high":high,"low":low,"adopted":adopted}
    return rec

def phase_lit(meta):
    log("=== §2.2 EPMC + 单位过滤 ===")
    stats = {"projects":0,"accession_hit":0,"freetext":0,"with_hits":0,
             "high_total":0,"low_total":0,"errs":0}
    with open(LIT_JSONL, "w", encoding="utf-8") as fo:
        for acc in meta:
            try:
                rec = process_one(acc, meta.get(acc,{}))
            except Exception as e:
                rec = {"project_accession":acc,"strategy":"ERR","error":str(e)[:200],"papers":[]}
            fo.write(json.dumps(rec, ensure_ascii=False)+"\n")
            stats["projects"]+=1
            if rec.get("accession_hit"): stats["accession_hit"]+=1
            elif rec.get("strategy")=="freetext": stats["freetext"]+=1
            if rec.get("hitCount",0)>0: stats["with_hits"]+=1
            c=rec.get("_counts")
            if c: stats["high_total"]+=c["high"]; stats["low_total"]+=c["low"]
            if rec.get("strategy")=="ERR": stats["errs"]+=1
            log("  %s strat=%s hit=%s papers=%d high=%s low=%s" % (
                acc, rec.get("strategy"), rec.get("hitCount"),
                len(rec.get("papers",[])), c["high"] if c else "-", c["low"] if c else "-"))
            time.sleep(0.3)
    with open(STATS_JSON,"w",encoding="utf-8") as f:
        json.dump(stats, f, indent=1)
    log("DONE §2.2 stats=%s" % stats)
    return stats

def main():
    accs = extract_batch()
    meta = phase_study(accs)
    phase_lit(meta)

if __name__ == "__main__":
    main()
