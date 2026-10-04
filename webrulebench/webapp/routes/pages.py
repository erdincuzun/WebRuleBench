"""
webrulebench/webapp/routes/pages.py — HTML sayfaları: ana sayfa, bölüm sayfaları, alt sayfalar, annotate ekranı, tarayıcı sözlüğü.
"""
from flask import Blueprint

from webrulebench.webapp.core import *  # noqa: F401,F403 — paylaşılan yardımcılar, yollar, kimlik doğrulama

bp = Blueprint("pages", __name__)


def _section_view(key):
    return lambda: render_template(f"sections/{key}.html", active=key,
                                   section=_SECTIONS_BY_KEY[key])


for _s in SECTIONS:
    bp.add_url_rule(_s["path"], f"section_{_s['key']}", _section_view(_s["key"]))


@bp.route("/i18n/<lang>.js")
def i18n_catalog(lang):
    """Tarayıcı sözlüğü (giriş gerektirmez; sürüm parametresiyle önbelleklenir)."""
    lang = I18N.norm(lang)
    body = "window.I18N = " + json.dumps(I18N.catalog(lang), ensure_ascii=False) + ";"
    r = Response(body, mimetype="application/javascript")
    r.headers["Cache-Control"] = "public, max-age=86400"
    return r


@bp.route("/")
def home():
    return render_template("home.html", active=None)


@bp.route("/schema/<tid>")
def schema_edit(tid):
    return render_template("sections/schema_edit.html", active="schema",
                           section=_SECTIONS_BY_KEY["schema"], tid=tid)


@bp.route("/schema/<tid>/prompts")
def schema_prompts(tid):
    return render_template("sections/schema_prompts.html", active="schema",
                           section=_SECTIONS_BY_KEY["schema"], tid=tid)


@bp.route("/ground-truth/<domain>")
def gt_site(domain):
    return render_template("sections/gt_site.html", active="groundtruth",
                           section=_SECTIONS_BY_KEY["groundtruth"], domain=domain)


@bp.route("/ground-truth/<domain>/<layout_id>")
def gt_compile(domain, layout_id):
    return render_template("sections/gt_compile.html", active="groundtruth",
                           section=_SECTIONS_BY_KEY["groundtruth"], domain=domain, layout_id=layout_id)


@bp.route("/settings/users")
def settings_users():
    return render_template("settings_users.html", active=None, section=None)


@bp.route("/settings/llm-models")
def settings_llm_models():
    return render_template("settings_llm.html", active=None, section=None)


@bp.route("/evaluation/new")
def evaluation_new():
    return render_template("sections/evaluation_new.html", active="evaluation", section=_SECTIONS_BY_KEY["evaluation"])


@bp.route("/evaluation/quick")
def evaluation_quick():
    return render_template("sections/evaluation_quick.html", active="evaluation", section=_SECTIONS_BY_KEY["evaluation"])


@bp.route("/evaluation/group/<gid>")
def evaluation_group(gid):
    return render_template("sections/evaluation_group.html", active="evaluation",
                           section=_SECTIONS_BY_KEY["evaluation"], gid=gid)


@bp.route("/evaluation/compare")
def evaluation_compare():
    return render_template("sections/evaluation_compare.html", active="evaluation", section=_SECTIONS_BY_KEY["evaluation"])


@bp.route("/evaluation/<exp_id>")
def evaluation_detail(exp_id):
    return render_template("sections/evaluation_detail.html", active="evaluation",
                           section=_SECTIONS_BY_KEY["evaluation"], exp_id=exp_id)


@bp.route("/annotate")
def index():
    return render_template("index.html")
