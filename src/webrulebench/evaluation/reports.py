"""
reports.py
==========
Aggregation for the Reports & Export section (WebRuleBench section 6).

- llm_results(): all experiments, as plain rows per layout (scores, tokens, time).
  Filtering, the common layout set and breakdowns (field / country / language / template)
  are done in the browser — the data is small, so interaction is instant.
- manifest(): the reproducibility appendix of the paper — experiment configurations, prompt texts
  used, model digests, GT compilation times, digests of the code files.
- audit_entries(): parses the lines of dataset/deletion_audit.log.

Scores have the same definition as in the experiment summary (experiments.summarize): the mean of the
layout means (macro). Page × field scores are kept in experiments/<id>.json.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from webrulebench.evaluation import experiments as EX

from webrulebench.paths import CODE_DIR as ROOT, DATA_DIR
AUDIT_LOG = DATA_DIR / "dataset" / "deletion_audit.log"
# code files digested in the manifest: pins down the code the experiment was produced with
CODE_FILES = ("evaluation/experiments.py", "evaluation/metrics.py", "pipeline/llm_extractor.py", "pipeline/llm_models.py",
              "pipeline/prompt_builder.py", "pipeline/html_cleaner.py", "pipeline/skeleton.py",
              "rules/regex_generator.py", "rules/rule_utils.py")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tool_version() -> str:
    try:
        from webrulebench import __version__
        return __version__
    except ImportError:
        return "unknown"


def _sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def _match_rate(rows: list) -> float | None:
    """Share of exact matches (MATCH) among the scored cells."""
    labs = [c["label"] for r in rows for c in r.values() if c.get("label") != "NO_GT"]
    return round(sum(1 for x in labs if x == "MATCH") / len(labs), 4) if labs else None


def _prompt_names(e: dict) -> dict:
    """template → name of the prompt used (automatic / variant)."""
    out = {}
    for key, p in (e.get("prompts_used") or {}).items():
        tid = key.split("|", 1)[0]
        out[tid] = p.get("name") or p.get("source") or "?"
    return out


def _slim_layout(l: dict) -> dict:
    llm = l.get("llm") or {}
    if l.get("error"):
        return {"d": l.get("domain"), "l": l.get("layout_id"), "t": l.get("template_id"), "err": str(l["error"])[:200]}
    s = l.get("summary") or {}
    pages = l.get("pages") or {}
    pf_match = {}
    for row in pages.values():
        for f, c in row.items():
            if c.get("label") != "NO_GT":
                pf_match.setdefault(f, []).append(1 if c.get("label") == "MATCH" else 0)
    return {
        "d": l.get("domain"), "l": l.get("layout_id"), "t": l.get("template_id"), "name": l.get("name"),
        "n": l.get("n_pages"), "mean": s.get("mean"), "sm": s.get("sample_mean"), "om": s.get("others_mean"),
        "pf": s.get("per_field") or {}, "pfm": {f: round(sum(v) / len(v), 4) for f, v in pf_match.items()},
        "match": _match_rate(list(pages.values())),
        "pt": llm.get("prompt_tokens") or 0, "gt": llm.get("gen_tokens") or 0, "ms": llm.get("elapsed_ms") or 0,
        "ok": bool(llm.get("success")),
    }


def _slim_experiment(e: dict) -> dict:
    c = e.get("config") or {}
    snap = c.get("backend_snapshot") or {}
    info = snap.get("model_info") or {}
    return {
        "id": e["id"], "name": e.get("name"), "kind": e.get("kind") or "experiment",
        "group": e.get("group"), "status": e.get("status"),
        "created_at": e.get("created_at"), "finished_at": e.get("finished_at"), "created_by": e.get("created_by"),
        "backend": c.get("backend"), "api": snap.get("api"), "model": snap.get("model") or c.get("model"),
        "rule_type": c.get("rule_type"), "rule_source": c.get("rule_source", "llm"),
        # if the key is missing (record from before 1.0.4), the LLM CSS had been processed with repair
        "css_repair": c.get("css_repair", c.get("rule_type") == "css" or c.get("rule_source") == "llm_css_regexn"),
        "strategy": c.get("strategy"), "skeleton": c.get("skeleton", "enriched"), "sample": c.get("sample"),
        "params": snap.get("params") or {},
        "model_info": {k: info.get(k) for k in ("parameter_size", "quantization", "family", "context_length")},
        "digest": (info.get("digest") or "")[:12] or None,
        "prompts": _prompt_names(e),
        "scope": len(e.get("scope") or []),
        "layouts": [_slim_layout(l) for l in e.get("layouts") or []],
    }


def llm_results() -> dict:
    exps = []
    for p in sorted(EX.EXP_DIR.glob("*.json")) if EX.EXP_DIR.exists() else []:
        e = EX.load(p.stem)
        if e and e.get("layouts"):
            exps.append(_slim_experiment(e))
    exps.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    groups = {}
    for x in exps:
        g = x.get("group")
        if g:
            groups.setdefault(g["id"], {"id": g["id"], "name": g.get("name"), "members": 0})["members"] += 1
    return {"experiments": exps, "groups": sorted(groups.values(), key=lambda g: g["id"], reverse=True),
            "match_at": EX.MATCH_AT}


# ---------------------------------------------------------------------------
# reproducibility manifest
# ---------------------------------------------------------------------------
def manifest(ids: list | None, gt_compiled: dict, dataset: dict) -> dict:
    """All completed experiments if ids is empty. gt_compiled: {domain: {layout: {lang: {at, by}}}}."""
    out_exps = []
    for p in sorted(EX.EXP_DIR.glob("*.json")) if EX.EXP_DIR.exists() else []:
        e = EX.load(p.stem)
        if not e or (ids and e["id"] not in ids) or (not ids and e.get("status") != "done"):
            continue
        c = dict(e.get("config") or {})
        out_exps.append({
            "id": e["id"], "name": e.get("name"), "kind": e.get("kind") or "experiment", "group": e.get("group"),
            "created_at": e.get("created_at"), "finished_at": e.get("finished_at"), "created_by": e.get("created_by"),
            "status": e.get("status"), "config": c,
            "scope": e.get("scope"),
            "prompts_used": e.get("prompts_used"),
            "summary": e.get("summary"),
            "generated_rules": {f"{l.get('domain')}|{l.get('layout_id')}": {"sample_page": l.get("sample_page"),
                                                                           "rules": l.get("rules")}
                                for l in e.get("layouts") or [] if not l.get("error")},
        })
    return {
        "generated_at": _now(),
        "tool": "WebRuleBench",
        "version": _tool_version(),
        "scoring": {"aggregation": "macro: mean of the per-layout means",
                    "match_threshold": EX.MATCH_AT,
                    "content_reference": "the value the GT CSS rule extracts from the page",
                    "generalization": "others_mean = mean over the GT pages other than the sample page"},
        "code": {f: _sha(ROOT / f) for f in CODE_FILES},
        "templates_sha": _sha(DATA_DIR / "layout_templates.json"),
        "dataset": dataset,
        "ground_truth_compiled": gt_compiled,
        "experiments": out_exps,
    }


# ---------------------------------------------------------------------------
# audit log
# ---------------------------------------------------------------------------
_KV = re.compile(r"(\w+)=(\S*)")


def audit_entries() -> list:
    """'YYYY-MM-DD HH:MM:SS  ACTION  k=v  k=v' lines → dicts (newest first)."""
    if not AUDIT_LOG.exists():
        return []
    out = []
    for line in AUDIT_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 2:
            continue
        kv = dict(_KV.findall("  ".join(parts[2:])))
        out.append({"at": parts[0], "action": parts[1],
                    "user": kv.get("user") or kv.get("by") or "",
                    "domain": kv.get("domain", ""), "details": "  ".join(parts[2:])})
    out.reverse()
    return out
