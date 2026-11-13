"""
mcp_server.py
=============
WebRuleBench MCP Server

Tools:
  detect_selectors   — run the HTML pipeline, generate CSS selectors
  validate_selector  — test a CSS selector against an HTML file
  evaluate_page      — compare the LLM output with the GT, give a score
  bulk_test          — test layout selectors on multiple pages
  get_ground_truth   — get the domain's GT data
  get_pages          — get the domain's page list

Auth: the tokens in <data folder>/users.json are used.
Config: mcp_config.json → backend / model / strategy (can be changed from the UI)

Setup:
  pip install mcp beautifulsoup4 python-dateutil requests
  python -m webrulebench.mcp_server
"""

import json
import sys
from pathlib import Path

# Add the project root directory to the path
_ROOT = Path(__file__).resolve().parents[1]   # src/ (for running as python src/webrulebench/mcp_server.py)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("WebRuleBench")

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------
from webrulebench.paths import DATA_DIR as _DATA   # noqa: E402
from webrulebench.rules.rule_utils import split_selector_list   # noqa: E402
DATASET_DIR  = _DATA / "dataset" / "raw"
APPROVED_DIR = _DATA / "ground_truth" / "approved"
ANNOTATIONS_DIR = _DATA / "annotations"
USERS_FILE   = _DATA / "users.json"
TEMPLATES_FILE = _DATA / "layout_templates.json"
MCP_CONFIG_FILE = _DATA / "mcp_config.json"


# ---------------------------------------------------------------------------
# CONFIG — read fresh on every call (a change in the UI takes effect immediately)
# ---------------------------------------------------------------------------
def load_mcp_config() -> dict:
    if MCP_CONFIG_FILE.exists():
        return json.loads(MCP_CONFIG_FILE.read_text(encoding="utf-8"))
    return {"backend": "ollama", "model": None, "strategy": "whitelist"}


# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------
def load_users() -> dict:
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return {}

def verify_token(token: str) -> str | None:
    """Verify the token → return the username, None if invalid (tokens are stored as digests; users_store.py)."""
    from webrulebench import users_store
    return users_store.verify_any(token)


# ---------------------------------------------------------------------------
# GT / ANNOTATION HELPERS
# ---------------------------------------------------------------------------
def load_ground_truth(domain: str) -> dict:
    path = APPROVED_DIR / f"{domain}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"domain": domain, "layouts": {}, "page_assignments": {}}

def load_templates() -> dict:
    if TEMPLATES_FILE.exists():
        return json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
    return {"templates": {}, "metrics": {}, "field_types": {}}

def get_template(template_id: str) -> dict | None:
    return load_templates()["templates"].get(template_id)

def _template_prompt(domain: str, filename: str):
    """Automatic prompt (prompt_builder) and field list from the template of the page's layout.
    If there is no template, the news defaults of llm_extractor are used."""
    gt        = load_ground_truth(domain)
    layout_id = gt.get("page_assignments", {}).get(filename, {}).get("layout_id")
    layout    = gt.get("layouts", {}).get(layout_id, {}) if layout_id else {}
    tmpl      = get_template(layout.get("template_id", "")) or {}
    if not tmpl.get("fields"):
        return None, None, None, "default"
    from webrulebench.pipeline.prompt_builder import build_prompt
    p = build_prompt(tmpl, "css")
    return p["system"], p["user"], list(tmpl["fields"]), f"auto:{layout.get('template_id')}"

def selectors_for_page(domain: str, filename: str) -> dict:
    gt = load_ground_truth(domain)
    assignment = gt.get("page_assignments", {}).get(filename, {})
    layout_id  = assignment.get("layout_id")
    if not layout_id:
        return {}
    raw = gt.get("layouts", {}).get(layout_id, {}).get("selectors", {})
    result = {}
    for field, val in raw.items():
        if val is None:
            continue
        if isinstance(val, list):
            val = val[0].get("image", "") if isinstance(val[0], dict) else (val[0] or "") if val else ""
        if val:
            result[field] = val
    return result

def field_metric(domain: str, filename: str, field: str) -> str:
    gt        = load_ground_truth(domain)
    pa        = gt.get("page_assignments", {}).get(filename, {})
    layout_id = pa.get("layout_id")
    layout    = gt.get("layouts", {}).get(layout_id, {}) if layout_id else {}
    overrides = layout.get("metric_overrides", {})
    if field in overrides:
        return overrides[field]
    tmpl   = get_template(layout.get("template_id", "")) or {}
    metric = tmpl.get("fields", {}).get(field, {}).get("metric")
    if metric:
        return metric
    return "jaccard" if field == "images" else "rouge"

def merge_flag(domain: str, filename: str, field: str) -> bool:
    gt        = load_ground_truth(domain)
    pa        = gt.get("page_assignments", {}).get(filename, {})
    layout_id = pa.get("layout_id")
    layout    = gt.get("layouts", {}).get(layout_id, {}) if layout_id else {}
    tmpl      = get_template(layout.get("template_id", "")) or {}
    base_field = field.split("[")[0]
    return bool(tmpl.get("fields", {}).get(base_field, {}).get("merge", False))

def extract_with_selector(soup, selector: str, field: str, merge: bool = False):
    if not selector:
        return "" if field != "images" else []
    parts = split_selector_list(selector)
    if merge:
        seen, els = set(), []
        for part in parts:
            try:
                for el in soup.select(part):
                    if id(el) not in seen:
                        seen.add(id(el))
                        els.append(el)
            except Exception:
                continue
    else:
        els = []
        for part in parts:
            try:
                found = soup.select(part)
            except Exception:
                continue
            if found:
                els = found
                break
    if field == "images":
        srcs = []
        for el in els:
            for img in ([el] if el.name == "img" else []) + el.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if src:
                    srcs.append(src.strip())
        return srcs
    return " ".join(el.get_text(strip=True) for el in els).strip()


# ---------------------------------------------------------------------------
# TOOL: detect_selectors
# ---------------------------------------------------------------------------
@mcp.tool()
def detect_selectors(
    domain: str,
    filename: str,
    token: str,
    use_admin_prompt: bool = False,   # deprecated; the prompt is always generated from the template
) -> dict:
    """
    Run the HTML pipeline: clean → skeleton → LLM → return CSS selectors.
    Backend/model/strategy are read from mcp_config.json.
    """
    username = verify_token(token)
    if not username:
        return {"error": "Invalid token"}

    html_path = DATASET_DIR / domain / filename
    if not html_path.exists():
        return {"error": f"File not found: {domain}/{filename}"}

    cfg      = load_mcp_config()
    backend  = cfg.get("backend", "ollama")
    model    = cfg.get("model") or None
    strategy = cfg.get("strategy", "whitelist")

    # Prompt selection
    system_prompt, user_prompt, fields, prompt_source = _template_prompt(domain, filename)

    try:
        from webrulebench.pipeline.html_cleaner import HTMLCleaner
        from webrulebench.pipeline.skeleton import Skeleton
        from webrulebench.pipeline.llm_extractor import LLMExtractor

        html      = html_path.read_text(encoding="utf-8", errors="ignore")
        cleaned   = HTMLCleaner().clean(html, strategy=strategy)
        sk        = Skeleton(strategy="enriched")
        skel      = sk.extract(cleaned.cleaned_html)
        extractor = LLMExtractor(
            backend       = backend,
            model         = model,
            system_prompt = system_prompt,
            user_prompt   = user_prompt,
            fields        = fields,
        )
        result = extractor.extract(skel.skeleton_html, domain=domain)
        return {
            "success":      result.success,
            "selectors":    result.selectors,
            "backend":      backend,
            "model":        result.model,
            "strategy":     strategy,
            "prompt_source": prompt_source,
            "elapsed_ms":   round(result.elapsed_ms, 1),
            "prompt_tokens": result.prompt_tokens,
            "gen_tokens":   result.gen_tokens,
            "error":        result.error or None,
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}


# ---------------------------------------------------------------------------
# TOOL: validate_selector
# ---------------------------------------------------------------------------
@mcp.tool()
def validate_selector(
    domain: str,
    filename: str,
    selector: str,
    token: str,
    field: str = "",
) -> dict:
    """Test a CSS selector against an HTML file, return the number of matching elements and a preview."""
    username = verify_token(token)
    if not username:
        return {"error": "Invalid token"}

    html_path = DATASET_DIR / domain / filename
    if not html_path.exists():
        return {"error": "File not found"}
    if not selector.strip():
        return {"valid": False, "message": "Selector must not be empty"}

    try:
        from bs4 import BeautifulSoup
        html = html_path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")
        merge = merge_flag(domain, filename, field) if field else False
        parts = split_selector_list(selector)

        if merge:
            seen, els = set(), []
            for part in parts:
                try:
                    for el in soup.select(part):
                        if id(el) not in seen:
                            seen.add(id(el))
                            els.append(el)
                except Exception:
                    continue
        else:
            els = []
            for part in parts:
                try:
                    found = soup.select(part)
                except Exception:
                    continue
                if found:
                    els = found
                    break

        previews = [el.get_text(strip=True)[:100] for el in els[:3] if el.get_text(strip=True)]
        if not els:
            return {"valid": False, "message": "No element found", "count": 0, "previews": []}
        return {"valid": True, "message": f"{len(els)} eleman bulundu", "count": len(els), "previews": previews}
    except Exception as e:
        return {"valid": False, "message": f"Error: {str(e)}"}


# ---------------------------------------------------------------------------
# TOOL: evaluate_page
# ---------------------------------------------------------------------------
@mcp.tool()
def evaluate_page(
    domain: str,
    filename: str,
    token: str,
    use_admin_prompt: bool = False,   # deprecated; the prompt is always generated from the template
) -> dict:
    """
    Compare the selectors generated by the LLM with the GT, return per-field scores.
    Backend/model are read from mcp_config.json.
    """
    username = verify_token(token)
    if not username:
        return {"error": "Invalid token"}

    gt_selectors = selectors_for_page(domain, filename)
    if not gt_selectors:
        return {"error": "No GT selector for this page"}

    html_path = DATASET_DIR / domain / filename
    if not html_path.exists():
        return {"error": "HTML file not found"}

    cfg      = load_mcp_config()
    backend  = cfg.get("backend", "ollama")
    model    = cfg.get("model") or None
    strategy = cfg.get("strategy", "whitelist")

    system_prompt, user_prompt, fields, prompt_source = _template_prompt(domain, filename)

    try:
        from bs4 import BeautifulSoup
        from webrulebench.pipeline.html_cleaner import HTMLCleaner
        from webrulebench.pipeline.skeleton import Skeleton
        from webrulebench.pipeline.llm_extractor import LLMExtractor
        from webrulebench.evaluation.metrics import word_f1_similarity, jaccard

        html    = html_path.read_text(encoding="utf-8", errors="ignore")
        gt_soup = BeautifulSoup(html, "lxml")
        gt_vals = {
            field: extract_with_selector(gt_soup, sel, field, merge_flag(domain, filename, field))
            for field, sel in gt_selectors.items()
        }

        cleaned    = HTMLCleaner().clean(html, strategy=strategy)
        sk         = Skeleton(strategy="enriched")
        skel       = sk.extract(cleaned.cleaned_html)
        extractor  = LLMExtractor(backend=backend, model=model, fields=fields,
                                  system_prompt=system_prompt, user_prompt=user_prompt)
        llm_result = extractor.extract(skel.skeleton_html, domain=domain)
        sels       = llm_result.selectors or {}

        soup         = BeautifulSoup(html, "lxml")
        field_scores = {}
        for field in gt_selectors:
            sel      = sels.get(field, "")
            gt_val   = gt_vals.get(field, "")
            pred_val = extract_with_selector(soup, sel, field, merge_flag(domain, filename, field)) if sel else ("" if field != "images" else [])
            metric   = field_metric(domain, filename, field)

            if metric == "jaccard":
                score = jaccard(
                    set(gt_val) if isinstance(gt_val, list) else {str(gt_val)},
                    set(pred_val) if isinstance(pred_val, list) else {str(pred_val)},
                )
            elif metric == "exact_match":
                score = 1.0 if str(gt_val).strip() == str(pred_val).strip() else 0.0
            else:
                score = word_f1_similarity(str(gt_val), str(pred_val))

            field_scores[field] = {
                "score":        round(score, 4),
                "metric":       metric,
                "selector":     sel,
                "predicted":    pred_val[:200] if isinstance(pred_val, str) else pred_val[:5],
                "ground_truth": gt_val[:200]   if isinstance(gt_val,   str) else gt_val[:5],
            }

        total_fields = len(field_scores)
        mean_score   = round(sum(v["score"] for v in field_scores.values()) / total_fields, 4) if total_fields else 0.0

        return {
            "success":      True,
            "domain":       domain,
            "filename":     filename,
            "backend":      backend,
            "model":        llm_result.model,
            "prompt_source": prompt_source,
            "mean_score":   mean_score,
            "field_scores": field_scores,
            "elapsed_ms":   round(llm_result.elapsed_ms, 1),
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}


# ---------------------------------------------------------------------------
# TOOL: bulk_test
# ---------------------------------------------------------------------------
@mcp.tool()
def bulk_test(
    domain: str,
    layout_id: str,
    filenames: list[str],
    token: str,
) -> dict:
    """Test layout selectors on more than one page."""
    username = verify_token(token)
    if not username:
        return {"error": "Invalid token"}

    gt      = load_ground_truth(domain)
    layout  = gt.get("layouts", {}).get(layout_id)
    if not layout:
        return {"error": "Layout not found"}

    selectors   = layout.get("selectors", {})
    opt_fields  = set(layout.get("optional_fields", []))
    tmpl        = get_template(layout.get("template_id", "")) or {}
    tmpl_fields = tmpl.get("fields", {})

    try:
        from bs4 import BeautifulSoup
        results = []
        for filename in filenames:
            path = DATASET_DIR / domain / filename
            if not path.exists():
                results.append({"filename": filename, "error": "File not found", "fields": {}})
                continue

            html = path.read_text(encoding="utf-8")
            soup = BeautifulSoup(html, "html.parser")
            field_results    = {}
            all_required_pass = True

            for field, sel in selectors.items():
                if not sel or not isinstance(sel, str):
                    continue
                base  = field.split("[")[0]
                merge = bool(tmpl_fields.get(base, {}).get("merge", False))
                parts = split_selector_list(sel)

                if merge:
                    seen, els = set(), []
                    for part in parts:
                        try:
                            for el in soup.select(part):
                                if id(el) not in seen:
                                    seen.add(id(el))
                                    els.append(el)
                        except Exception:
                            continue
                else:
                    els = []
                    for part in parts:
                        try:
                            found = soup.select(part)
                        except Exception:
                            continue
                        if found:
                            els = found
                            break

                valid   = bool(els)
                preview = els[0].get_text(strip=True)[:100] if els else ""
                optional = field in opt_fields
                field_results[field] = {"valid": valid, "preview": preview, "optional": optional}
                if not valid and not optional:
                    all_required_pass = False

            results.append({
                "filename":          filename,
                "fields":            field_results,
                "all_required_pass": all_required_pass,
            })

        pass_count = sum(1 for r in results if r.get("all_required_pass"))
        return {
            "domain":     domain,
            "layout_id":  layout_id,
            "total":      len(results),
            "pass_count": pass_count,
            "results":    results,
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "detail": traceback.format_exc()}


# ---------------------------------------------------------------------------
# TOOL: get_ground_truth
# ---------------------------------------------------------------------------
@mcp.tool()
def get_ground_truth(domain: str, token: str) -> dict:
    """Return the approved GT layouts and page assignments for the domain."""
    username = verify_token(token)
    if not username:
        return {"error": "Invalid token"}

    gt = load_ground_truth(domain)
    pa = gt.get("page_assignments", {})

    layout_pages: dict[str, list] = {}
    for fname, info in pa.items():
        if info.get("skipped") or not info.get("layout_id"):
            continue
        layout_pages.setdefault(info["layout_id"], []).append(fname)

    return {
        "domain":        domain,
        "layouts":       gt.get("layouts", {}),
        "layout_pages":  layout_pages,
        "total_assigned": sum(len(v) for v in layout_pages.values()),
    }


# ---------------------------------------------------------------------------
# TOOL: get_pages
# ---------------------------------------------------------------------------
@mcp.tool()
def get_pages(domain: str, token: str) -> dict:
    """Return the domain's list of HTML pages (homepage, listing, article)."""
    username = verify_token(token)
    if not username:
        return {"error": "Invalid token"}

    site_dir = DATASET_DIR / domain
    if not site_dir.exists():
        return {"error": f"Site not found: {domain}"}

    files = sorted(site_dir.glob("*.html"))
    return {
        "domain":   domain,
        "homepage": [f.name for f in files if f.name == "homepage.html"],
        "listing":  [f.name for f in files if f.name.startswith("listing_")],
        "article":  [f.name for f in files if f.name.startswith("article_")],
    }


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 50)
    print("  WebRuleBench — MCP Server")
    print("=" * 50)
    cfg = load_mcp_config()
    print(f"  Backend  : {cfg.get('backend')}")
    print(f"  Model    : {cfg.get('model') or '(default)'}")
    print(f"  Strategy : {cfg.get('strategy')}")
    print("=" * 50)
    mcp.run()
