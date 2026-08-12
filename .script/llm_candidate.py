#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
§3.2 候选信号预提取：对 agent_residual_<field>.jsonl 的每条残差，
复用 ena_infer_31 的同一套词表（PLACE/DEMONYM/OPEN_OCEAN/HOST_*），
在 evidence_text 中找出国家名 / 宿主词候选并带 ±70 字上下文片段，
把每条记录压缩成几行候选，供代理(LLM)快速判值。
不判值、不改任何源文件；产物仅供阅读。
"""
import os, re, json, argparse, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
REPLAN_ROOT = os.path.dirname(HERE)
BASE = os.path.join(REPLAN_ROOT, ".tmp")

# ---- 复用 ena_infer_31 的词表 ----
spec = importlib.util.spec_from_file_location(
    "ena_infer_31", os.path.join(HERE, "ena_infer_31.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
PLACE = m.PLACE
DEMONYM = m.DEMONYM
OPEN_OCEAN = m.OPEN_OCEAN
HOST_HUMAN_TRIGGER = m.HOST_HUMAN_TRIGGER
HOST_SITE = m.HOST_SITE
HOST_ANIMAL = m.HOST_ANIMAL
ANIMAL_GUT_NAME = m.ANIMAL_GUT_NAME
HOST_ANIMAL_SOFT = m.HOST_ANIMAL_SOFT
HOST_ENV = m.HOST_ENV

def _wb(t):
    """词边界（前后非字母），兼容多词 key。"""
    return r"(?<![a-z])" + re.escape(t) + r"(?![a-z])"

COUNTRY_PATS = []
for k, v in PLACE.items():
    COUNTRY_PATS.append((re.compile(_wb(k), re.I), v, "place"))
for k, v in DEMONYM.items():
    COUNTRY_PATS.append((re.compile(_wb(k), re.I), v, "demonym"))
OCEAN_PATS = [(re.compile(_wb(o), re.I), o) for o in OPEN_OCEAN]

HOST_KW = {}
for k in HOST_HUMAN_TRIGGER:
    HOST_KW[k] = "human_trigger"
for k in HOST_SITE:
    HOST_KW[k] = "site"
for k, v in HOST_ANIMAL.items():
    HOST_KW[k] = "animal:%s" % v
for k, v in ANIMAL_GUT_NAME.items():
    HOST_KW[k] = "animal_gut:%s" % v
for k, v in HOST_ANIMAL_SOFT.items():
    HOST_KW[k] = "soft:%s" % v
for k, v in HOST_ENV.items():
    HOST_KW[k] = "env:%s" % v
HOST_PATS = [(re.compile(_wb(k), re.I), k, tag) for k, tag in HOST_KW.items()]

def snip(text, s, e, span=70):
    s = max(0, s - span); e = min(len(text), e + span)
    return text[s:e].replace("\n", " ")

def find_countries(text):
    out = []
    seen = set()
    for pat, val, kind in COUNTRY_PATS:
        for mm in pat.finditer(text):
            key = (val, mm.group(0).lower())
            if key in seen:
                continue
            seen.add(key)
            out.append((val, mm.group(0), snip(text, mm.start(), mm.end())))
    return out

def find_ocean(text):
    out = []
    for pat, o in OCEAN_PATS:
        for mm in pat.finditer(text):
            out.append((o, snip(text, mm.start(), mm.end())))
    return out

def find_hosts(text):
    out = []
    for pat, kw, tag in HOST_PATS:
        for mm in pat.finditer(text):
            out.append((kw, tag, snip(text, mm.start(), mm.end())))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--field", required=True, choices=["country", "date", "host"])
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=None)
    args = ap.parse_args()
    rows = [json.loads(l) for l in open(
        os.path.join(BASE, f"agent_residual_{args.field}.jsonl"), encoding="utf-8")]
    end = args.end if args.end is not None else len(rows)
    for i in range(args.start, min(end, len(rows))):
        r = rows[i]
        rp = r.get("rule_partial", {})
        body = r["evidence_text"].split("[rule_partial]")[0]
        # 解析 section 便于打印标题/描述预览
        title = ""
        desc = ""
        for line in body.split("\n"):
            if line.startswith("[study_title]"):
                title = line[len("[study_title]"):].strip()
            elif line.startswith("[study_description]"):
                desc = line[len("[study_description]"):].strip()
        print(f"\n===== [{i}] {r['project_accession']} | {r['field']} "
              f"| rule_value={rp.get('value')} conf={rp.get('confidence')} "
              f"method={rp.get('method')} matched={rp.get('matched_tokens')} =====")
        print(f"  TITLE: {title[:300]}")
        print(f"  DESC : {desc[:160]}")
        if args.field == "country":
            ch = find_countries(body)
            oc = find_ocean(body)
            if ch:
                print("  COUNTRY CANDIDATES:")
                for val, mtxt, s in ch:
                    print(f"    - {val!r} <= '{mtxt}' :: ...{s}...")
            else:
                print("  COUNTRY: <none found>")
            if oc:
                print("  OCEAN/NotCountry:")
                for o, s in oc:
                    print(f"    - {o!r} :: ...{s}...")
        else:  # host
            hs = find_hosts(body)
            if hs:
                print("  HOST CANDIDATES:")
                for kw, tag, s in hs:
                    print(f"    - {kw!r} [{tag}] :: ...{s}...")
            else:
                print("  HOST: <none found>")

if __name__ == "__main__":
    main()
