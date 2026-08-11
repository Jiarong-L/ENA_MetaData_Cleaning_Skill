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

# host 词表 —— VALUE 对齐 ENA metagenome scientific_name
# （命名来源：.reuse/taxid_type.tsv 中 is_metagenome=1 的 scientific_name，
#   例如 soil metagenome / human gut metagenome / pig gut metagenome / gut metagenome）
# 优先级：生境词 -> "X metagenome"；人+部位 -> "human X metagenome"；
#         动物+肠道 -> "X gut metagenome"；仅部位 -> "X metagenome"(generic)；
#         仅人/动物 -> 物种 scientific_name（Homo sapiens / Bos taurus ...）
# 此约定同时约束规则轮(§3.1)与后续 LLM 轮(§3.2)。

# 人源触发词（命中即认为宿主为人，VALUE 优先 Homo sapiens / human X metagenome）
# 注意：_find_words 对文本做小写匹配，故双词触发词须小写 "homo sapiens"，
#       其 s? 后缀兼容 "homo sapiens" / "homo sapiens gut" 等写法
HOST_HUMAN_TRIGGER = [
    "homo sapiens", "human", "infant", "neonatal", "newborn", "patient", "clinical",
    "clinic", "hospital", "mucosal", "carrier",
]
# 部位词 -> (generic ENA 名, 人源 ENA 名)；generic 为 None 表示仅有人源形式
HOST_SITE = {
    "gut": ("gut metagenome", "human gut metagenome"),
    "fecal": ("gut metagenome", "human gut metagenome"),
    "faecal": ("gut metagenome", "human gut metagenome"),
    "faeces": ("gut metagenome", "human gut metagenome"),
    "stool": ("gut metagenome", "human gut metagenome"),
    "feces": ("gut metagenome", "human gut metagenome"),
    "intestinal": ("gut metagenome", "human gut metagenome"),
    "intestine": ("gut metagenome", "human gut metagenome"),
    "colorectal": ("gut metagenome", "human gut metagenome"),
    "colon": ("gut metagenome", "human gut metagenome"),
    "oral": ("oral metagenome", "human oral metagenome"),
    "saliva": ("oral metagenome", "human oral metagenome"),
    "salivary": ("oral metagenome", "human oral metagenome"),
    "mouth": ("oral metagenome", "human oral metagenome"),
    "skin": ("skin metagenome", "human skin metagenome"),
    "dermal": ("skin metagenome", "human skin metagenome"),
    "vaginal": ("vaginal metagenome", "human vaginal metagenome"),
    "milk": (None, "human milk metagenome", True),
    "breast milk": (None, "human milk metagenome", True),
    "breastmilk": (None, "human milk metagenome", True),
    "lung": (None, "human lung metagenome", True),
    "respiratory": (None, "human lung metagenome", True),
    "sputum": (None, "human lung metagenome", True),
    "endotracheal": (None, "human lung metagenome", True),
    "nasopharyngeal": (None, "human nasopharyngeal metagenome", True),
    "nasal": (None, "human nasopharyngeal metagenome", True),
    "nose": (None, "human nasopharyngeal metagenome", True),
    "skeleton": (None, "human skeleton metagenome", True),
    "bone": (None, "human skeleton metagenome", True),
}
# 规则1 site 同义词表：canonical middle 词 -> 触发该部位的所有 HOST_SITE 键。
# 例如 "gut" -> {gut, fecal, faecal, faeces, stool, feces, intestinal, intestine, colorectal, colon}。
# 用于 is_high_evidence 规则1：evidence 中出现任一部位同义词即视为该部位在场。
_SITE_SYN = {}
for _k, _v in HOST_SITE.items():
    _generic, _human = _v[0], _v[1]
    _mw = None
    if _human and _human.startswith("human ") and _human.endswith(" metagenome"):
        _mw = _human[len("human "):-len(" metagenome")]
    elif _generic and _generic.endswith(" metagenome"):
        _mw = _generic[:-len(" metagenome")]
    if _mw:
        _SITE_SYN.setdefault(_mw, set()).add(_k)
# 动物 -> 物种 scientific_name（兜底用）。
# 俗名与学名均触发（cattle / Bos taurus 都命中 -> Bos taurus），
# 二者映射到同一物种，与 taxid_type.tsv 中 is_metagenome=0 的物种名对齐。
# 注意：_find_words 对文本做小写匹配，双词学名须全小写（如 "bos taurus"）。
HOST_ANIMAL = {
    # 羊
    "lamb": "Ovis aries", "sheep": "Ovis aries", "ovine": "Ovis aries", "ewe": "Ovis aries",
    "ovis aries": "Ovis aries",
    # 牛
    "cattle": "Bos taurus", "cow": "Bos taurus", "bovine": "Bos taurus", "calf": "Bos taurus",
    "bos taurus": "Bos taurus",
    # 猪
    "pig": "Sus scrofa", "porcine": "Sus scrofa",
    "sus scrofa": "Sus scrofa",
    # 鸡 / 禽
    "poultry": "Gallus gallus", "chicken": "Gallus gallus",
    "gallus gallus": "Gallus gallus",
    # 山羊
    "goat": "Capra hircus", "caprine": "Capra hircus",
    "capra hircus": "Capra hircus",
    # 犬
    "dog": "Canis lupus familiaris",
    "canis lupus familiaris": "Canis lupus familiaris",
    # 猫
    "cat": "Felis catus",
    "felis catus": "Felis catus",
    # 鼠
    "mouse": "Mus musculus", "mice": "Mus musculus",
    "rat": "Rattus norvegicus", "rats": "Rattus norvegicus",
    "mus musculus": "Mus musculus", "rattus norvegicus": "Rattus norvegicus",
    # 鱼
    "fish": "Actinopterygii", "actinopterygii": "Actinopterygii",
    # 马
    "horse": "Equus caballus", "equus caballus": "Equus caballus",
    # 兔
    "rabbit": "Oryctolagus cuniculus", "oryctolagus cuniculus": "Oryctolagus cuniculus",
    # 骆驼
    "camel": "Camelus dromedarius", "camelus dromedarius": "Camelus dromedarius",
}
# 动物+肠道 -> ENA 名（仅 taxid_type.tsv 中有对应 "X gut metagenome" 者）。
# 学名键与俗名键映射同一 ENA 名（如 sus scrofa / pig 均 -> pig gut metagenome）。
ANIMAL_GUT_NAME = {
    "pig": "pig gut metagenome", "porcine": "pig gut metagenome",
    "sus scrofa": "pig gut metagenome",
    "cattle": "bovine gut metagenome", "cow": "bovine gut metagenome",
    "bovine": "bovine gut metagenome", "calf": "bovine gut metagenome",
    "bos taurus": "bovine gut metagenome",
    "chicken": "chicken gut metagenome",
    "gallus gallus": "chicken gut metagenome",
    "sheep": "sheep gut metagenome", "ovine": "sheep gut metagenome",
    "lamb": "sheep gut metagenome", "ewe": "sheep gut metagenome",
    "ovis aries": "sheep gut metagenome",
    "mouse": "mouse gut metagenome", "mus musculus": "mouse gut metagenome",
    "rat": "rat gut metagenome", "rattus norvegicus": "rat gut metagenome",
}

# 轻量补充：昆虫/灵长/爬行/两栖/甲壳/软体/其它哺乳/鸟/植物/真菌等常见俗名。
# 这些词多为常见英文词，误匹配风险高，故：
#   (1) 必须整段含 HOST_CTX 共存词（metagenome/genome/宿主部位等）才触发；
#   (2) 命中一律 medium + needs_review，VALUE 暂用俗名（非 ENA 名），
#       交 §3.2 LLM 精炼为规范 scientific_name / 判断是否真宿主。
# 仅作"软信号"，不妄下结论，交 §3.2 LLM 精炼。
HOST_ANIMAL_SOFT = {
    # 昆虫 / 节肢动物
    "honeybee": "honeybee", "termite": "termite", "mosquito": "mosquito",
    "beetle": "beetle", "wasp": "wasp", "butterfly": "butterfly",
    "moth": "moth", "caterpillar": "caterpillar", "cicada": "cicada",
    "locust": "locust", "grasshopper": "grasshopper", "ant": "ant",
    # 灵长
    "monkey": "monkey", "ape": "ape", "gorilla": "gorilla",
    "chimpanzee": "chimpanzee", "bonobo": "bonobo", "orangutan": "orangutan",
    "gibbon": "gibbon", "baboon": "baboon", "macaque": "macaque",
    "lemur": "lemur",
    # 爬行 / 两栖
    "lizard": "lizard", "snake": "snake", "turtle": "turtle",
    "tortoise": "tortoise", "frog": "frog", "toad": "toad",
    "crocodile": "crocodile", "salamander": "salamander", "gecko": "gecko",
    # 甲壳 / 软体
    "shrimp": "shrimp", "crab": "crab", "lobster": "lobster",
    "oyster": "oyster", "mussel": "mussel", "squid": "squid",
    "octopus": "octopus", "snail": "snail", "slug": "slug", "clam": "clam",
    # 其它哺乳
    "whale": "whale", "dolphin": "dolphin", "seal": "seal",
    "elephant": "elephant", "zebra": "zebra", "giraffe": "giraffe",
    "hippo": "hippo", "rhino": "rhino", "deer": "deer", "bison": "bison",
    "buffalo": "buffalo", "yak": "yak", "wolf": "wolf", "fox": "fox",
    "panda": "panda", "lion": "lion", "tiger": "tiger",
    "leopard": "leopard", "hyena": "hyena",
    # 鸟
    "penguin": "penguin", "duck": "duck", "goose": "goose",
    "pigeon": "pigeon",
    # 植物 / 真菌
    "wheat": "wheat", "maize": "maize", "soybean": "soybean",
    "tomato": "tomato", "barley": "barley", "oat": "oat", "sorghum": "sorghum",
    "pea": "pea", "carrot": "carrot", "lettuce": "lettuce", "grape": "grape",
    "apple": "apple", "banana": "banana", "sugarcane": "sugarcane",
    "sunflower": "sunflower", "rapeseed": "rapeseed", "cabbage": "cabbage",
    "onion": "onion", "garlic": "garlic", "yeast": "yeast",
    "mushroom": "mushroom", "fern": "fern",
    # 其它无脊椎
    "worm": "worm", "nematode": "nematode", "mite": "mite", "tick": "tick",
    "coral": "coral", "sponge": "sponge", "jellyfish": "jellyfish",
}
# 生境词 -> ENA ecological metagenome 名（仅保留有官方命名的词；
# 去掉 forest/terrestrial/dust：易误判且无对应 ENA 名）
HOST_ENV = {
    "soil": "soil metagenome", "sediment": "sediment metagenome",
    "freshwater": "freshwater metagenome", "river": "riverine metagenome",
    "lake": "lake water metagenome", "stream": "riverine metagenome",
    "marine": "marine metagenome", "seawater": "seawater metagenome",
    "ocean": "marine metagenome", "water": "aquatic metagenome",
    "wastewater": "wastewater metagenome", "sludge": "sludge metagenome",
    "compost": "compost metagenome", "manure": "manure metagenome",
    "plant": "plant metagenome", "rhizosphere": "rhizosphere metagenome",
    "phyllosphere": "phyllosphere metagenome", "air": "air metagenome",
    "biofilm": "biofilm metagenome", "glacier": "glacier metagenome",
    "permafrost": "permafrost metagenome", "hot spring": "hot springs metagenome",
    "mangrove": "mangrove metagenome", "wetland": "wetland metagenome",
    "aquatic": "aquatic metagenome", "groundwater": "groundwater metagenome",
}

HOST_CTX = set("""
metagenome metagenomic microbiome microbial host gut fecal feces stool faeces oral skin soil
water plant animal tissue commensal symbiont isolate strain genome sequencing sequenced dna rna
biofilm rhizosphere sediment marine freshwater aquatic terrestrial invertebrate vertebrate
mammal bird fish insect pathogen parasite fungus bacterial viral eukaryotic sample specimen
taxonomic phylogenetic diversity abundance community communities amplicon illumina pacbio
shotgun nanopore reads
""".split())

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


def is_high_evidence(value, method, evidence):
    """用户设定（证据窗口内强共现 -> 标 High、跳过 §3.2 LLM）：只看 evidence 单条 ±30 字片段。

    规则1：三字科学名「<host> <site> metagenome」——host 指示词与中间词(site)同时出现在 evidence：
      · host 指示词 = human / homo sapiens（或 HOST_ANIMAL 对应俗名，取 value 首词）
      · site 词     = 三字科学名的中间词（如 gut / lung / oral …），
                      允许 HOST_SITE 同义词（feces/faecal/stool/intestinal… 均视作 gut 在场）
    规则2：仅限「二字生境科学名」（即 `<env_word> metagenome`，如 soil metagenome、
            sludge metagenome、marine metagenome）——两词都出现在 evidence 中。
            说明：Bos taurus / Homo sapiens / Mus musculus 等拉丁二名法（物种学名，
            不以 metagenome 收尾）**不适用**规则2，也不适用规则1（无 site 中间词），
            故永不经由证据窗口标 High，保持 medium 交 §3.2。
    soft 永远不标 High（恒交 §3.2 LLM）。不回看全文。
    """
    if method == "rule_host_soft":
        return False
    ev = _norm(evidence)
    toks = _norm(value).split()
    if len(toks) == 3 and toks[-1] == "metagenome":
        host_word, site_word = toks[0], toks[1]
        host_ok = (host_word in ev) or (host_word == "human" and "homo sapiens" in ev)
        if not host_ok:
            return False
        if site_word in ev:
            return True
        for syn in _SITE_SYN.get(site_word, ()):
            if syn in ev:
                return True
        return False
    # 规则2：仅「<env_word> metagenome」二字生境名适用；拉丁二名法（Bos taurus 等）不标 High
    if len(toks) == 2 and toks[-1] == "metagenome":
        return (toks[0] in ev) and (toks[1] in ev)
    return False


def infer_host(sources):
    """返回 host 记录。基线 confidence 恒为 medium（仅关键字命中，无上下文精判）。

    VALUE 对齐 ENA metagenome scientific_name（参照 .reuse/taxid_type.tsv 中
    is_metagenome=1 的命名）：
      - 生境词           -> "X metagenome"        (soil/marine/...)
      - 人 + 部位        -> "human X metagenome"
      - 动物 + 肠道      -> "X gut metagenome"
      - 仅部位（无归属） -> "X metagenome"         (generic: gut/oral/skin/vaginal)
      - 仅人 / 仅动物    -> 物种 scientific_name   (Homo sapiens / Bos taurus ...)
    软信号（HOST_ANIMAL_SOFT：昆虫/灵长/爬行等俗名，无 ENA 专属名）仅作 needs_review
    候选：须整段含 HOST_CTX 共存词才触发，VALUE 暂用俗名，交 §3.2 LLM 精炼。
    sputum/lung/milk/naso/skeleton 等仅有人源形式的部位：无人源触发时不妄判，
    留空交由 §3.2。
    """
    hit_human, hit_animal, hit_env, hit_site, hit_soft = [], [], [], [], []
    for sub, text in sources:
        if not text:
            continue
        for w, snip in _find_words(text, HOST_HUMAN_TRIGGER):
            hit_human.append((sub, snip, w))
        for w, snip in _find_words(text, list(HOST_ANIMAL.keys())):
            hit_animal.append((sub, snip, HOST_ANIMAL[w], w))
        for w, snip in _find_words(text, list(HOST_ENV.keys())):
            hit_env.append((sub, snip, w))
        for w, snip in _find_words(text, list(HOST_SITE.keys())):
            hit_site.append((sub, snip, w))
        for w, snip in _find_words(text, list(HOST_ANIMAL_SOFT.keys())):
            hit_soft.append((sub, snip, w))

    human_present = bool(hit_human)
    animal_word = hit_animal[0][3] if hit_animal else None
    animal_species = hit_animal[0][2] if hit_animal else None
    site_word = hit_site[0][2] if hit_site else None
    env_word = hit_env[0][2] if hit_env else None
    soft_word = hit_soft[0][2] if hit_soft else None

    matched = []
    for _, _, w in hit_human:
        matched.append(w)
    for _, _, _, w in hit_animal:
        matched.append(w)
    for _, _, w in hit_site:
        matched.append(w)
    for _, _, w in hit_env:
        matched.append(w)
    if soft_word:
        matched.append(soft_word)

    GUT_SITE = ("gut", "fecal", "faeces", "stool", "feces", "intestinal",
                "intestine", "colorectal", "colon")
    ctx_present = any(any(w in _norm(t) for w in HOST_CTX) for _, t in sources)

    value, method = None, None
    if site_word:
        entry = HOST_SITE[site_word]
        generic, human_name = entry[0], entry[1]
        require_human = entry[2] if len(entry) > 2 else False
        if human_present and human_name:
            value, method = human_name, "rule_host_human"
        elif (animal_word and site_word in GUT_SITE
              and animal_word in ANIMAL_GUT_NAME):
            value, method = ANIMAL_GUT_NAME[animal_word], "rule_host_animal"
        elif generic and not require_human:
            method = "rule_host_human" if human_present else "rule_host_env"
            value, method = generic, method
        # require_human 且无人源触发 -> 不妄判，留空
    if value is None:
        if human_present:
            value, method = "Homo sapiens", "rule_host_human"
        elif animal_species:
            value, method = animal_species, "rule_host_animal"
        elif env_word:
            value, method = HOST_ENV[env_word], "rule_host_env"
        elif soft_word and ctx_present:
            value, method = HOST_ANIMAL_SOFT[soft_word], "rule_host_soft"

    if value is None:
        return None

    rep = next((x[0] for x in (hit_site, hit_human, hit_animal, hit_env, hit_soft) if x), None)
    if rep is None:
        return None
    sub, snip = rep[0], rep[1]
    rec = _host_rec(value, "medium", sub, snip, method, matched)
    if is_high_evidence(value, method, rec["evidence"]):
        rec["confidence"] = "high"
    if method == "rule_host_soft":
        rec["needs_review"] = True
    return rec


def _host_rec(value, conf, sub, snip, method, tokens):
    return {
        "value": value,
        "confidence": conf,
        "content_reliability": _reliability(sub, snip),
        "source": source_of(sub),
        "method": method,
        "evidence": f"[{sub}] …{snip}…",
        "matched_tokens": tokens,
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
