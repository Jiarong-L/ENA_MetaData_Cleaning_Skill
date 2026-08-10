#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ena_infer_31.py — §3.1 规则 + 字典基线（确定性，优先跑）

从可信文本源（study_meta: study_title/study_description/center_name；
papersource=high 的 literature: title/abstract）用规则 + 字典推断
country / date / host。

输出每条推断带两个互相独立的质控标签 + evidence（对齐 Replan §3.0）：
  - content_reliability (标签 A): 匹配内容本身的可信度 high/medium/low
  - source             (标签 B): study_meta / literature
  - confidence: high / medium / low / NotCountry / unknown  （字段推断等级）
  - method: 命中规则 (rule_demonym / rule_place / rule_open_ocean /
            rule_region / rule_multi_country / rule_host_* / rule_date_* / none)
  - evidence: 命中片段 + 上下文

用法：
  python ena_infer_31.py                         # 默认读 .tmp/ 下两个输入
  python ena_infer_31.py --fields country,host  # 只跑部分字段
  python ena_infer_31.py --limit 3              # 测试前 N 个项目
  python ena_infer_31.py --only PRJEB11419      # 单项目

输入（只读，不改动）：
  --study-meta  .tmp/project_study_meta.json
  --literature  .tmp/project_literature.jsonl
输出（写 --out，默认 .tmp/）：
  country_infer.jsonl / date_infer.jsonl / host_infer.jsonl
  infer_stats.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

# 目录基准：本脚本位于 <replan>/.script/，父目录即 replan 根目录
REPLAN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .replan
TMP_DIR = os.path.join(REPLAN_ROOT, ".tmp")
LOG_DIR = os.path.join(REPLAN_ROOT, ".log")

def _replan_log(msg):
    """追加一行运行日志到 .log/run_YYYY-MM-DD.log（失败静默，不影响主流程）。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        lp = os.path.join(LOG_DIR, "run_%s.log" % datetime.now().strftime("%Y-%m-%d"))
        with open(lp, "a", encoding="utf-8") as _f:
            _f.write("[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), msg))
    except Exception:
        pass

# ----------------------------------------------------------------------------
# 字典基线（从第一天就内建，不做补救轮）—— 核心集，可继续扩充
# ----------------------------------------------------------------------------

# demonym adjective -> canonical country name (sovereignty: TW/MO -> China,
# Korea=Korea, Turkey independent real country; HK/TW/MO use ", China" suffix)
DEMONYM = {
    "american": "United States", "british": "United Kingdom", "english": "United Kingdom", "scottish": "United Kingdom",
    "australian": "Australia", "canadian": "Canada", "chinese": "China",
    "danish": "Denmark", "dutch": "Netherlands", "finnish": "Finland", "french": "France",
    "german": "Germany", "greek": "Greece", "hungarian": "Hungary", "indian": "India",
    "indonesian": "Indonesia", "iranian": "Iran", "iraqi": "Iraq",
    "irish": "Ireland", "israeli": "Israel", "italian": "Italy",
    "japanese": "Japan", "korean": "Korea", "malaysian": "Malaysia",
    "mexican": "Mexico", "new zealander": "New Zealand", "norwegian": "Norway",
    "pakistani": "Pakistan", "polish": "Poland", "portuguese": "Portugal",
    "russian": "Russia", "saudi": "Saudi Arabia", "singaporean": "Singapore",
    "south african": "South Africa", "spanish": "Spain", "swedish": "Sweden",
    "swiss": "Switzerland", "taiwanese": "Taiwan, China", "thai": "Thailand",
    "turkish": "Turkey", "ukrainian": "Ukraine", "vietnamese": "Vietnam",
    "brazilian": "Brazil", "argentine": "Argentina", "austrian": "Austria",
    "belgian": "Belgium", "czech": "Czechia", "slovenian": "Slovenia",
    "slovak": "Slovakia", "croatian": "Croatia", "romanian": "Romania",
    "bulgarian": "Bulgaria", "egyptian": "Egypt", "nigerian": "Nigeria",
    "kenyan": "Kenya", "ethiopian": "Ethiopia", "moroccan": "Morocco",
    "ghanaian": "Ghana", "tunisian": "Tunisia", "filipino": "Philippines",
    "icelandic": "Iceland", "danish": "Denmark",
}

# place name -> canonical country name (sovereignty normalization; HK/TW/MO -> ", China")
PLACE = {
    "beijing": "China", "shanghai": "China", "shenzhen": "China",
    "guangzhou": "China", "hong kong": "Hong Kong, China", "macau": "Macao, China",
    "macao": "Macao, China", "taipei": "Taiwan, China", "taiwan": "Taiwan, China",
    "tokyo": "Japan", "osaka": "Japan", "kyoto": "Japan", "seoul": "Korea",
    "busan": "Korea", "london": "United Kingdom", "manchester": "United Kingdom",
    "edinburgh": "United Kingdom", "paris": "France", "lyon": "France",
    "marseille": "France", "berlin": "Germany", "munich": "Germany",
    "hamburg": "Germany", "madrid": "Spain", "barcelona": "Spain",
    "rome": "Italy", "milan": "Italy", "amsterdam": "Netherlands",
    "rotterdam": "Netherlands", "utrecht": "Netherlands", "brussels": "Belgium",
    "antwerp": "Belgium", "gent": "Belgium", "copenhagen": "Denmark",
    "aarhus": "Denmark", "stockholm": "Sweden", "oslo": "Norway",
    "helsinki": "Finland", "vienna": "Austria", "zurich": "Switzerland",
    "geneva": "Switzerland", "moscow": "Russia", "st petersburg": "Russia",
    "warsaw": "Poland", "prague": "Czechia", "lisbon": "Portugal",
    "dublin": "Ireland", "vancouver": "Canada", "toronto": "Canada",
    "montreal": "Canada", "new york": "United States", "california": "United States",
    "san diego": "United States", "boston": "United States", "chicago": "United States",
    "washington": "United States", "texas": "United States", "sydney": "Australia",
    "melbourne": "Australia", "brisbane": "Australia", "auckland": "New Zealand",
    "singapore": "Singapore", "mumbai": "India", "delhi": "India",
    "bangalore": "India", "bangkok": "Thailand", "jakarta": "Indonesia",
    "kuala lumpur": "Malaysia", "manila": "Philippines",
    "ho chi minh": "Vietnam", "hanoi": "Vietnam", "dubai": "United Arab Emirates",
    "riyadh": "Saudi Arabia", "tehran": "Iran", "baghdad": "Iraq",
    "jerusalem": "Israel", "tel aviv": "Israel", "cairo": "Egypt",
    "lagos": "Nigeria", "nairobi": "Kenya", "johannesburg": "South Africa",
    "capetown": "South Africa", "buenos aires": "Argentina", "sao paulo": "Brazil",
    "rio de janeiro": "Brazil", "mexico city": "Mexico", "istanbul": "Turkey",
    "ankara": "Turkey", "athens": "Greece", "evian": "France",
}

# 公海/深海 -> NotCountry（明确无主权国）
OPEN_OCEAN = [
    "open ocean", "open-ocean", "high seas", "deep sea", "deep-sea",
    "abyssal", "abyssopelagic", "pelagic", "mid-ocean", "midwaters",
    "bathypelagic", "hadal", "epipelagic",
]

# 区域（洲/洋/南极/北海/地中海等）-> medium（非单一国）
REGION = [
    "europe", "european", "asia", "asian", "africa", "african",
    "north america", "north american", "south america", "south american",
    "central america", "latin america", "oceania", "antarctica",
    "antarctic", "arctic", "north sea", "baltic sea", "mediterranean",
    "pacific", "atlantic", "indian ocean", "southern ocean",
    "global", "worldwide", "world-wide", "multinational", "multi-country",
    "cross-country", "internationally",
]

# host 词表（ENV 生境词本身就是合法 host 信号，勿当"无宿主"砍）
HOST_HUMAN = [
    "human", "gut", "fecal", "faeces", "stool", "feces", "oral", "saliva",
    "salivary", "skin", "blood", "blood culture", "urine", "urinary",
    "endotracheal", "sputum", "breast milk", "breastmilk", "vaginal",
    "infant", "neonatal", "newborn", "patient", "clinic", "clinical",
    "hospital", "mucosal", "intestine", "intestinal", "colorectal",
    "carrier", "fecal microbiota", "gut microbiome", "gut microbiota",
]
HOST_ANIMAL = {
    "lamb": "sheep (Ovis aries)", "sheep": "sheep (Ovis aries)",
    "ovine": "sheep (Ovis aries)", "ewe": "sheep (Ovis aries)",
    "cattle": "cattle (Bos taurus)", "cow": "cattle (Bos taurus)",
    "bovine": "cattle (Bos taurus)", "pig": "pig (Sus scrofa)",
    "porcine": "pig (Sus scrofa)", "poultry": "poultry",
    "chicken": "chicken (Gallus)", "goat": "goat (Capra)",
    "caprine": "goat (Capra)", "dog": "dog (Canis)", "cat": "cat (Felis)",
    "mouse": "mouse (Mus)", "rat": "rat (Rattus)", "fish": "fish",
    "horse": "horse (Equus)", "rabbit": "rabbit (Oryctolagus)",
    "camel": "camel", "calf": "cattle (Bos taurus)",
}
HOST_ENV = [
    "soil", "sediment", "freshwater", "river", "lake", "stream", "marine",
    "seawater", "ocean", "water", "wastewater", "sludge", "compost",
    "manure", "plant", "rhizosphere", "phyllosphere", "air", "dust",
    "biofilm", "glacier", "permafrost", "hot spring", "mangrove",
    "wetland", "forest", "terrestrial", "aquatic", "groundwater",
]

# 采样/地点上下文词（命中附近出现 -> content_reliability 提为 high）
CTX_SAMPLE = [
    "collected", "sample", "sampled", "sampling", "from", "in", "recruited",
    "cohort", "located", "site", "origin", "originat", "obtained",
    "isolated", "harvest", "resident", "population", "city", "country",
    "region", "hospital", "clinic",
]

YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


# ----------------------------------------------------------------------------
# 工具
# ----------------------------------------------------------------------------

def _norm(t):
    return (t or "").lower()


def _word_boundary_find(text, keys):
    """返回 {(matched_key, normalized_value_or_None): [snippet, ...]}。
    keys: dict key->value；若 value 为 None 表示该 dict 仅记命中词（如 region）。"""
    low = _norm(text)
    hits = {}
    for k in sorted(keys, key=len, reverse=True):
        v = keys[k]
        pat = r"\b" + re.escape(k) + r"\b"
        for m in re.finditer(pat, low):
            snippet = text[max(0, m.start() - 35): m.end() + 35].strip()
            hits.setdefault((k, v), []).append(snippet)
    return hits


def _ctx_reliable(snippet, token):
    """标签 A 基础：命中片段是否处于采样/地点上下文。"""
    s = _norm(snippet)
    return any(w in s for w in CTX_SAMPLE)


def _reliability(sub_source, snippet):
    """标签 A：结合 sub_source 与上下文给出 high/medium/low。"""
    base = "medium"
    if sub_source in ("study_description", "study_title", "literature_abstract"):
        base = "high"
    elif sub_source == "center_name":
        base = "medium"          # 中心未必等于采样国
    elif sub_source == "literature_title":
        base = "medium"
    if _ctx_reliable(snippet, None):
        base = "high"
    return base


def source_of(sub_source):
    """标签 B：sub_source -> study_meta / literature（center_name 属 study_meta）。"""
    return "study_meta" if sub_source in (
        "study_title", "study_description", "center_name") else "literature"


# ----------------------------------------------------------------------------
# 字段推断
# ----------------------------------------------------------------------------

def infer_country(sources):
    """sources: list of (sub_source, text)。返回 best record 或 None。"""
    countries = {}      # norm_country -> list of (sub_source, snippet, method)
    regions = {}        # region_word -> snippet
    ocean = []          # snippets
    for sub, text in sources:
        if not text:
            continue
        # demonym
        for (k, v), snips in _word_boundary_find(text, DEMONYM).items():
            for s in snips:
                countries.setdefault(v, []).append((sub, s, "rule_demonym"))
        # place
        for (k, v), snips in _word_boundary_find(text, PLACE).items():
            for s in snips:
                countries.setdefault(v, []).append((sub, s, "rule_place"))
        # region
        for (k, _v), snips in _word_boundary_find(text, {r: None for r in REGION}).items():
            for s in snips:
                regions.setdefault(k, (sub, s))
        # open ocean
        low = _norm(text)
        for kw in OPEN_OCEAN:
            for m in re.finditer(r"\b" + re.escape(kw) + r"\b", low):
                ocean.append((sub, text[max(0, m.start() - 30): m.end() + 30].strip()))

    if countries:
        vals = sorted(countries.keys())
        # 取代表性 source/reliability/method
        rep_sub, rep_snip, rep_method = countries[vals[0]][0]
        reli = _reliability(rep_sub, rep_snip)
        method = "rule_multi_country" if len(vals) > 1 else rep_method
        # 拼接 evidence（每国一个片段）
        ev_bits = []
        for c in vals:
            sub, s, _m = countries[c][0]
            ev_bits.append(f"[{c}|{sub}] …{s}…")
        return {
            "value": vals,
            "confidence": "high",
            "content_reliability": reli,
            "source": source_of(rep_sub),
            "method": method,
            "evidence": " ; ".join(ev_bits)[:400],
            "matched_tokens": vals,
        }
    if ocean and not regions:
        sub0, s0 = ocean[0]
        return {
            "value": "NotCountry",
            "confidence": "NotCountry",
            "content_reliability": "high",
            "source": source_of(sub0),
            "method": "rule_open_ocean",
            "evidence": " ; ".join(f"[{sub}] …{s}…" for sub, s in ocean)[:300],
            "matched_tokens": ["open_ocean"],
        }
    if regions:
        rep_sub = next(iter(regions.values()))[0]
        return {
            "value": sorted(regions.keys()),
            "confidence": "medium",
            "content_reliability": "medium",
            "source": source_of(rep_sub),
            "method": "rule_region",
            "evidence": " ; ".join(f"[{k}|{sub}] …{s}…" for k, (sub, s) in regions.items())[:300],
            "matched_tokens": sorted(regions.keys()),
        }
    return None


def _find_words(text, words):
    """匹配词表（允许可选复数 s）。返回 list of (word_matched, snippet)。"""
    low = _norm(text)
    out = []
    for w in sorted(words, key=len, reverse=True):
        pat = r"\b" + re.escape(w) + r"s?\b"
        for m in re.finditer(pat, low):
            out.append((w, text[max(0, m.start() - 30): m.end() + 30].strip()))
    return out


def infer_host(sources):
    found = {"human": [], "animal": [], "env": []}
    for sub, text in sources:
        if not text:
            continue
        for w, snip in _find_words(text, HOST_HUMAN):
            found["human"].append((sub, snip, w))
        for w, snip in _find_words(text, list(HOST_ANIMAL.keys())):
            found["animal"].append((sub, snip, HOST_ANIMAL[w]))
        for w, snip in _find_words(text, HOST_ENV):
            found["env"].append((sub, snip, w))

    if found["human"]:
        sub, s, w = found["human"][0]
        return _host_rec("human (Homo sapiens)", "high", sub, s, "rule_host_human", w)
    if found["animal"]:
        sub, s, v = found["animal"][0]
        return _host_rec(v, "high", sub, s, "rule_host_animal", v)
    if found["env"]:
        sub, s, w = found["env"][0]
        return _host_rec(w, "high", sub, s, "rule_host_env", w)
    return None


def _host_rec(value, conf, sub, snip, method, token):
    return {
        "value": value,
        "confidence": conf,
        "content_reliability": _reliability(sub, snip),
        "source": source_of(sub),
        "method": method,
        "evidence": f"[{sub}] …{snip}…",
        "matched_tokens": [token],
    }


def infer_date(sources):
    years = []
    for sub, text in sources:
        if not text:
            continue
        for m in YEAR_RE.finditer(_norm(text)):
            y = int(m.group(0))
            if 1900 <= y <= 2100:
                years.append((y, sub, text[max(0, m.start() - 30): m.end() + 30].strip()))
    if not years:
        return None
    ys = sorted(set(y for y, _, _ in years))
    # 区间判定
    rep_sub, rep_snip = years[0][1], years[0][2]
    if len(ys) >= 2 and max(ys) - min(ys) >= 2:
        val = f"{min(ys)}-{max(ys)}"
        conf, method = "medium", "rule_date_range"
    else:
        val = str(ys[0])
        conf, method = "high", "rule_date_year"
    return {
        "value": val,
        "confidence": conf,
        "content_reliability": _reliability(rep_sub, rep_snip),
        "source": source_of(rep_sub),
        "method": method,
        "evidence": f"[{rep_sub}] …{rep_snip}…",
        "matched_tokens": [str(y) for y in ys],
    }


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------

def load_inputs(study_meta_path, literature_path):
    meta = {}
    if os.path.exists(study_meta_path):
        with open(study_meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    lit = {}
    if os.path.exists(literature_path):
        with open(literature_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                lit[d["project_accession"]] = d
    return meta, lit


def build_sources(acc, meta, lit):
    """返回 list of (sub_source, text)，含 study_meta 三字段 + literature high 论文。"""
    sources = []
    m = meta.get(acc, {})
    sources.append(("study_title", m.get("study_title", "")))
    sources.append(("study_description", m.get("study_description", "")))
    sources.append(("center_name", m.get("center_name", "")))
    d = lit.get(acc, {})
    for p in d.get("papers", []):
        if p.get("papersource") == "high":
            sources.append(("literature_title", p.get("title", "")))
            sources.append(("literature_abstract", p.get("abstract", "")))
    return sources


def blank_record(acc, field):
    return {
        "project_accession": acc,
        "field": field,
        "value": None,
        "confidence": "unknown",
        "content_reliability": None,
        "source": None,
        "method": "none",
        "evidence": "",
        "matched_tokens": [],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--study-meta", default=os.path.join(TMP_DIR, "project_study_meta.json"))
    ap.add_argument("--literature", default=os.path.join(TMP_DIR, "project_literature.jsonl"))
    ap.add_argument("--out", default=TMP_DIR)
    ap.add_argument("--fields", default="country,date,host")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    _replan_log("ena_infer_31 --fields %s --out %s" % (args.fields, args.out))

    fields = [x.strip() for x in args.fields.split(",") if x.strip()]
    meta, lit = load_inputs(args.study_meta, args.literature)
    accs = sorted(set(meta.keys()) | set(lit.keys()))
    if args.only:
        accs = [a for a in accs if a == args.only]
    if args.limit:
        accs = accs[: args.limit]

    os.makedirs(args.out, exist_ok=True)
    out_files = {f: open(os.path.join(args.out, f"{f}_infer.jsonl"), "w", encoding="utf-8") for f in fields}
    stats = {f: {} for f in fields}

    for acc in accs:
        sources = build_sources(acc, meta, lit)
        for f in fields:
            rec = blank_record(acc, f)
            if f == "country":
                r = infer_country(sources)
            elif f == "host":
                r = infer_host(sources)
            elif f == "date":
                r = infer_date(sources)
            else:
                r = None
            if r:
                rec.update(r)
            out_files[f].write(json.dumps(rec, ensure_ascii=False) + "\n")
            stats[f][rec["confidence"]] = stats[f].get(rec["confidence"], 0) + 1

    for f in fields:
        out_files[f].close()
    with open(os.path.join(args.out, "infer_stats.json"), "w", encoding="utf-8") as f:
        json.dump({"n_projects": len(accs), "fields": stats}, f, ensure_ascii=False, indent=2)

    print(f"[ena_infer_31] projects={len(accs)} fields={fields}")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
