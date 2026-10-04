"""
webrulebench/webapp/routes/data.py — Veri Toplama: siteler, sayfalar (ekleme, silme, yeniden indirme, toplu ekleme), ülkeler, istatistik.
"""
from flask import Blueprint

from webrulebench.webapp.core import *  # noqa: F401,F403 — paylaşılan yardımcılar, yollar, kimlik doğrulama

bp = Blueprint("data", __name__)


@bp.route("/api/sites")
def api_sites():
    username = current_user()
    sites    = load_sites()
    progress = get_progress(username)
    result   = []
    for site in sites:
        domain    = site["domain"]
        gt        = load_ground_truth(domain)
        pages     = get_site_pages(domain)
        all_pages = pages["article"] + pages["listing"]
        if username:
            assigned = user_assigned_count(domain, username)
        else:
            pa       = gt.get("page_assignments", {})
            assigned = sum(1 for v in pa.values() if not v.get("skipped") and v.get("layout_id"))

        layouts = len(gt.get("layouts", {}))
        # giriş yapan kullanıcının kendi ilerlemesi: kural yazdığı layout'lar ve son kaydı
        # (yalnızca kendi annotation dosyası okunur — başkalarının kuralları gösterilmez)
        my_done, my_last = 0, None
        if username:
            mine = load_user_annotation(domain, username).get("layouts", {})
            for lid in gt.get("layouts", {}):
                ml = mine.get(lid) or {}
                if any(_rule_of(v, "css") or _rule_of(v, "xpath") or _rule_of(v, "regex")
                       for v in (ml.get("selectors") or {}).values()):
                    my_done += 1
            ts = [l.get("updated_at") for l in mine.values() if l.get("updated_at")]
            my_last = max(ts) if ts else None
        gt_pages = sum(1 for v in gt.get("page_assignments", {}).values()
                       if v.get("layout_id") and not v.get("skipped"))
        result.append({
            **site,
            "gt_pages":   gt_pages,
            "my_layouts": my_done,
            "my_last":    my_last,
            "my_status":  ("none" if not my_done else "done" if my_done >= layouts else "partial") if layouts else "na",
            "total_pages": len(all_pages),
            "annotated":   assigned,
            "layouts":     layouts,
            "complete":    assigned >= min(5, len(all_pages)) if all_pages else False,
            "gt_exported": layouts > 0,
            "ready":       assigned >= 5,
        })
    total_assigned = sum(s["annotated"] for s in result)
    total_layouts  = sum(s["layouts"] for s in result)
    return jsonify({
        "sites":           result,
        "progress":        progress,
        "annotated_pages": total_assigned,
        "total_layouts":   total_layouts,
    })


@bp.route("/api/site/<domain>")
def api_site(domain):
    pages    = get_site_pages(domain)
    gt       = load_ground_truth(domain)
    username = current_user()
    if username:
        ann      = load_user_annotation(domain, username)
        user_pa  = ann.get("page_assignments", {})
        merged   = dict(gt.get("page_assignments", {}))
        merged.update(user_pa)   # kullanıcı atamaları öncelikli
        gt = dict(gt)
        gt["page_assignments"] = merged
    return jsonify({
        "domain":      domain,
        "pages":       pages,
        "ground_truth": gt,
    })


@bp.route("/api/page/<domain>/<filename>")
def api_page(domain, filename):
    """Serve raw HTML file content."""
    path = DATASET_DIR / domain / filename
    if not path.exists():
        return jsonify({"error": _t("File not found")}), 404
    return send_file(path, mimetype="text/html")


@bp.route("/api/page/delete", methods=["POST"])
def api_delete_page():
    """Delete an HTML file from disk and remove its assignment."""
    _, err = require_admin()
    if err: return err
    data     = request.json
    domain   = data.get("domain")
    filename = data.get("filename")

    # Remove from ground truth assignments
    gt = load_ground_truth(domain)
    gt["page_assignments"].pop(filename, None)
    save_ground_truth(domain, gt)

    # Delete the HTML file from disk
    html_path = DATASET_DIR / domain / filename
    deleted_from_disk = False
    if html_path.exists():
        _audit(f"PAGE_DELETE  domain={domain}  file={filename}  path={html_path}")
        html_path.unlink()
        deleted_from_disk = True

    return jsonify({"success": True, "deleted_from_disk": deleted_from_disk})


@bp.route("/api/page/redownload", methods=["POST"])
def api_redownload_page():
    """Re-download a page from a new URL and replace the existing HTML file."""
    _, err = require_admin()
    if err: return err
    data     = request.json
    domain   = data.get("domain")
    filename = data.get("filename")
    new_url  = data.get("url", "").strip()

    if not new_url:
        return jsonify({"success": False, "error": _t("URL cannot be empty")})

    html_path = DATASET_DIR / domain / filename
    if not html_path.exists():
        return jsonify({"success": False, "error": _t("File not found")})

    try:
        html, method, error = _fetch_html(new_url)
        if not html:
            return jsonify({"success": False, "error": _t(error or "Could not download the page")})

        # Save new HTML
        html_path.write_text(html, encoding="utf-8")

        # Update index.json
        if INDEX_FILE.exists():
            idx = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
            key = f"raw/{domain}/{filename}"
            if key in idx:
                idx[key]["url"] = new_url
                idx[key]["size_bytes"] = len(html)
                idx[key]["fetch_method"] = method
                idx[key]["downloaded_at"] = datetime.now(timezone.utc).isoformat()
            else:
                idx[key] = {"url": new_url, "page_type": "article", "domain": domain,
                            "fetch_method": method, "size_bytes": len(html),
                            "downloaded_at": datetime.now(timezone.utc).isoformat()}
            INDEX_FILE.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")

        # Append to download_log.json
        if DL_LOG_FILE.exists():
            dl_log = json.loads(DL_LOG_FILE.read_text(encoding="utf-8"))
        else:
            dl_log = []
        dl_log.append({
            "url": new_url, "domain": domain, "page_type": "article",
            "success": True, "method": method, "status_code": None,
            "error": None, "elapsed_s": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        DL_LOG_FILE.write_text(json.dumps(dl_log, ensure_ascii=False, indent=2), encoding="utf-8")

        # Clear page assignment from ground_truth (content changed)
        gt = load_ground_truth(domain)
        if filename in gt.get("page_assignments", {}):
            del gt["page_assignments"][filename]
            save_ground_truth(domain, gt)

        return jsonify({"success": True, "size": len(html)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@bp.route("/api/page/add", methods=["POST"])
def api_add_page():
    """Download a new page from a URL and add it to the site's dataset."""
    _, err = require_admin()
    if err: return err
    data      = request.json
    domain    = data.get("domain")
    page_type = data.get("page_type", "article")  # "article" | "listing"
    new_url   = data.get("url", "").strip()

    if not new_url:
        return jsonify({"success": False, "error": _t("URL cannot be empty")})
    if page_type not in ("article", "listing"):
        return jsonify({"success": False, "error": _t("page_type must be article or listing")})

    site_dir = DATASET_DIR / domain
    if not site_dir.exists():
        return jsonify({"success": False, "error": _t("Site folder not found")})

    # Next available file number — önce boşlukları doldur, sonra sona ekle
    import re
    pattern  = re.compile(rf"^{page_type}_(\d+)\.html$")
    existing = sorted([int(m.group(1)) for f in site_dir.iterdir()
                       if (m := pattern.match(f.name))])
    if existing:
        full_range = set(range(1, max(existing) + 1))
        gaps = sorted(full_range - set(existing))
        next_num = gaps[0] if gaps else max(existing) + 1
    else:
        next_num = 1
    filename  = f"{page_type}_{next_num:03d}.html"
    html_path = site_dir / filename

    try:
        html, method, error = _fetch_html(new_url)
        if not html:
            return jsonify({"success": False, "error": _t(error or "Could not download the page")})

        html_path.write_text(html, encoding="utf-8")

        # Update index.json
        if INDEX_FILE.exists():
            idx = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        else:
            idx = {}
        key = f"raw/{domain}/{filename}"
        idx[key] = {
            "url": new_url, "page_type": page_type, "domain": domain,
            "fetch_method": method, "size_bytes": len(html),
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        INDEX_FILE.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")

        # Append to download_log.json
        if DL_LOG_FILE.exists():
            dl_log = json.loads(DL_LOG_FILE.read_text(encoding="utf-8"))
        else:
            dl_log = []
        dl_log.append({
            "url": new_url, "domain": domain, "page_type": page_type,
            "success": True, "method": method, "status_code": None,
            "error": None, "elapsed_s": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        DL_LOG_FILE.write_text(json.dumps(dl_log, ensure_ascii=False, indent=2), encoding="utf-8")

        _audit(f"PAGE_ADD  domain={domain}  file={filename}  url={new_url}")
        return jsonify({"success": True, "filename": filename, "size": len(html)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@bp.route("/api/page/extract-links", methods=["POST"])
def api_extract_links():
    """Extract href links from a local HTML file using a CSS selector."""
    _, err = require_admin()
    if err: return err
    data     = request.json
    domain   = data.get("domain")
    filename = data.get("filename")
    selector = data.get("selector", "a[href]").strip()

    if not domain or not filename:
        return jsonify({"success": False, "error": _t("domain and filename are required")})

    html_path = DATASET_DIR / domain / filename
    if not html_path.exists():
        return jsonify({"success": False, "error": _t("File not found")})

    html = html_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")

    try:
        elems = soup.select(selector)
    except Exception as e:
        return jsonify({"success": False, "error": _t("Invalid selector: {error}", error=e)})

    links = []
    seen  = set()
    for el in elems:
        href = el.get("href", "").strip()
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append({"href": href, "text": el.get_text(strip=True)[:80]})

    return jsonify({"success": True, "links": links, "count": len(links)})


@bp.route("/api/page/add-bulk", methods=["POST"])
def api_add_page_bulk():
    """Download multiple URLs and add them to the site's dataset."""
    _, err = require_admin()
    if err: return err
    data      = request.json
    domain    = data.get("domain")
    page_type = data.get("page_type", "article")
    urls      = data.get("urls", [])

    if not urls:
        return jsonify({"success": False, "error": _t("The URL list is empty")})
    if page_type not in ("article", "listing"):
        return jsonify({"success": False, "error": _t("page_type must be article or listing")})

    site_dir = DATASET_DIR / domain
    if not site_dir.exists():
        return jsonify({"success": False, "error": _t("Site folder not found")})

    import re
    pattern = re.compile(rf"^{page_type}_(\d+)\.html$")

    results = []
    for url in urls:
        url = url.strip()
        if not url:
            continue

        # Find next available filename
        existing = sorted([int(m.group(1)) for f in site_dir.iterdir()
                           if (m := pattern.match(f.name))])
        if existing:
            full_range = set(range(1, max(existing) + 1))
            gaps = sorted(full_range - set(existing))
            next_num = gaps[0] if gaps else max(existing) + 1
        else:
            next_num = 1
        filename  = f"{page_type}_{next_num:03d}.html"
        html_path = site_dir / filename

        try:
            html, method, error = _fetch_html(url)
            if not html:
                results.append({"url": url, "success": False, "error": _t(error or "Download failed")})
                continue

            html_path.write_text(html, encoding="utf-8")

            if INDEX_FILE.exists():
                idx = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
            else:
                idx = {}
            key = f"raw/{domain}/{filename}"
            idx[key] = {
                "url": url, "page_type": page_type, "domain": domain,
                "fetch_method": method, "size_bytes": len(html),
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
            }
            INDEX_FILE.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")

            _audit(f"PAGE_ADD  domain={domain}  file={filename}  url={url}")
            results.append({"url": url, "success": True, "filename": filename, "size": len(html)})
        except Exception as e:
            results.append({"url": url, "success": False, "error": str(e)})

    ok  = sum(1 for r in results if r["success"])
    return jsonify({"success": True, "results": results, "ok": ok, "total": len(results)})


@bp.route("/api/page/url", methods=["GET"])
def api_page_url():
    """Return the stored URL for a page from index.json."""
    domain   = request.args.get("domain")
    filename = request.args.get("filename")
    if not domain or not filename:
        return jsonify({"url": None})
    if INDEX_FILE.exists():
        idx = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        key = f"raw/{domain}/{filename}"
        entry = idx.get(key, {})
        return jsonify({"url": entry.get("url")})
    return jsonify({"url": None})


@bp.route("/api/site/add", methods=["POST"])
def api_add_site():
    """Create a new site directory and optionally download an initial page."""
    _, err = require_admin()
    if err: return err
    data = request.json
    name = data.get("name", "").strip()
    url  = data.get("url", "").strip()

    if not name:
        return jsonify({"success": False, "error": _t("Site name cannot be empty")})
    if not (data.get("country") or "").strip():
        return jsonify({"success": False, "error": _t("Select a country")})
    if not url:
        return jsonify({"success": False, "error": _t("URL cannot be empty")})

    from urllib.parse import urlparse as _up
    parsed = _up(url)
    domain = parsed.netloc.replace("www.", "")
    if not domain:
        return jsonify({"success": False, "error": _t("Enter a valid URL")})

    site_dir = DATASET_DIR / domain
    if site_dir.exists():
        return jsonify({"success": False, "error": _t("'{name}' already exists", name=domain)})

    # Register in sites.json (klasörden önce: ülke hatası varsa hiçbir şey oluşturulmasın)
    meta_err = _upsert_site_meta(domain, name, data.get("country", ""), (data.get("notes") or "").strip(),
                                 url=f"https://{domain}", new_country=data.get("new_country"))
    if meta_err:
        return jsonify({"success": False, "error": meta_err})

    site_dir.mkdir(parents=True, exist_ok=True)
    _audit(f"SITE_ADD  domain={domain}  name={name}  url={url}  country={data.get('country')}")

    # Download homepage
    homepage_path = site_dir / "homepage.html"
    homepage_ok = False
    fetch_method = None
    try:
        html, fetch_method, fetch_err = _fetch_html(url)
        if html:
            homepage_path.write_text(html, encoding="utf-8")
            homepage_ok = True
            key = f"raw/{domain}/homepage.html"
            idx = json.loads(INDEX_FILE.read_text(encoding="utf-8")) if INDEX_FILE.exists() else {}
            idx[key] = {
                "url": url, "page_type": "homepage", "domain": domain,
                "fetch_method": fetch_method, "size_bytes": len(html),
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
            }
            INDEX_FILE.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return jsonify({"success": True, "domain": domain, "homepage_ok": homepage_ok})


@bp.route("/api/countries")
def api_countries():
    """sites.json'daki ülkeler (kod/kıta/dil) + site sayısı; 'Other' hariç."""
    groups = _load_sites_file()["countries"]
    return jsonify({"countries": [
        {k: g.get(k, "") for k in ("country", "code", "continent", "language")} | {"sites": len(g.get("sites", []))}
        for g in sorted(groups, key=lambda g: g.get("country", "")) if g.get("country") != "Other"
    ]})


@bp.route("/api/site/update", methods=["POST"])
def api_update_site():
    """Site bilgilerini (ad, ülke, not) düzenle. Domain değişmez — klasör ve GT dosyaları ona bağlı."""
    _, err = require_admin()
    if err: return err
    data   = request.json or {}
    domain = (data.get("domain") or "").strip()
    name   = (data.get("name") or "").strip()
    if not domain or not (DATASET_DIR / domain).is_dir():
        return jsonify({"success": False, "error": _t("Site not found")}), 404
    if not name:
        return jsonify({"success": False, "error": _t("Site name cannot be empty")})
    if not (data.get("country") or "").strip():
        return jsonify({"success": False, "error": _t("Select a country")})
    meta_err = _upsert_site_meta(domain, name, data["country"], (data.get("notes") or "").strip(),
                                 new_country=data.get("new_country"))
    if meta_err:
        return jsonify({"success": False, "error": meta_err})
    _audit(f"SITE_UPDATE  domain={domain}  name={name}  country={data['country']}")
    return jsonify({"success": True})


@bp.route("/api/site/delete", methods=["POST"])
def api_delete_site():
    """Delete a site completely: raw HTML dir, ground truth JSON, index & log entries."""
    _, err = require_admin()
    if err: return err
    data   = request.json
    domain = data.get("domain")
    if not domain:
        return jsonify({"success": False, "error": _t("No domain specified")})

    deleted = {}

    # 1. Raw HTML directory
    site_dir = DATASET_DIR / domain
    if site_dir.exists():
        html_files = list(site_dir.glob("*.html"))
        _audit(f"SITE_DELETE  domain={domain}  html_files={len(html_files)}  path={site_dir}")
        shutil.rmtree(site_dir)
        deleted["raw_dir"] = str(site_dir)

    # 2. Ground truth JSON
    gt_path = GROUND_TRUTH / f"{domain}.json"
    if gt_path.exists():
        _audit(f"SITE_DELETE_GT  domain={domain}  path={gt_path}")
        gt_path.unlink()
        deleted["ground_truth"] = str(gt_path)

    # 3. index.json — remove entries for this domain
    if INDEX_FILE.exists():
        idx = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        before = len(idx)
        idx = {k: v for k, v in idx.items() if v.get("domain") != domain}
        INDEX_FILE.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
        deleted["index_entries_removed"] = before - len(idx)

    # 4. download_log.json — remove entries for this domain
    if DL_LOG_FILE.exists():
        log = json.loads(DL_LOG_FILE.read_text(encoding="utf-8"))
        before = len(log)
        log = [e for e in log if e.get("domain") != domain]
        DL_LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        deleted["log_entries_removed"] = before - len(log)

    # 5. excluded_domains.json — prevent gap_filler from re-downloading
    excluded = json.loads(EXCLUDED_FILE.read_text(encoding="utf-8")) if EXCLUDED_FILE.exists() else []
    if domain not in excluded:
        excluded.append(domain)
        EXCLUDED_FILE.write_text(json.dumps(excluded, ensure_ascii=False, indent=2), encoding="utf-8")
        _audit(f"SITE_EXCLUDED  domain={domain}")

    return jsonify({"success": True, "deleted": deleted})


@bp.route("/api/stats")
def api_stats():
    """Overall annotation statistics — layout bazlı."""
    sites = load_sites()
    stats = {
        "total_sites":    len(sites),
        "complete_sites": 0,
        "total_pages":    0,
        "annotated_pages": 0,
        "total_layouts":  0,
        "skipped_pages":  0,
    }
    for site in sites:
        gt    = load_ground_truth(site["domain"])
        pages = get_site_pages(site["domain"])
        all_p = pages["article"] + pages["listing"]
        pa    = gt.get("page_assignments", {})
        assigned = sum(1 for v in pa.values() if not v.get("skipped") and v.get("layout_id"))
        skipped  = sum(1 for v in pa.values() if v.get("skipped"))
        stats["total_pages"]     += len(all_p)
        stats["annotated_pages"] += assigned
        stats["total_layouts"]   += len(gt.get("layouts", {}))
        stats["skipped_pages"]   += skipped
        if assigned >= min(5, len(all_p)) and all_p:
            stats["complete_sites"] += 1
    return jsonify(stats)
