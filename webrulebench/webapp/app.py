"""
webapp/app.py — uygulamayı kurar ve başlatır.

    webrulebench serve                       # http://127.0.0.1:5001, veri: data/
    WRB_DATA_DIR=demo/data WRB_PORT=5002 webrulebench serve
"""
from webrulebench.webapp.core import BASE_DIR, app
from webrulebench.webapp.routes import BLUEPRINTS

for _bp in BLUEPRINTS:
    app.register_blueprint(_bp)


def main():
    # WRB_PORT / WRB_HOST / WRB_DEBUG (bkz. paths.py): demo ve Docker için (varsayılan 127.0.0.1:5001, debug açık)
    from webrulebench.paths import env
    port  = int(env("PORT", "5001"))
    host  = env("HOST", "127.0.0.1")
    debug = env("DEBUG", "1") != "0"
    print("=" * 50)
    print("  WebRuleBench")
    print(f"  http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}")
    print(f"  data: {BASE_DIR}")
    print("=" * 50)
    app.run(debug=debug, port=port, host=host)


if __name__ == "__main__":
    main()
