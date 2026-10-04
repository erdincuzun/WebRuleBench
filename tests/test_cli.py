"""
test_cli.py — `webrulebench` komutu: sürüm ve kullanıcı yönetimi (geçici veri klasöründe).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CLI = [sys.executable, "-m", "webrulebench"]   # depo kökünden (cwd=ROOT)


def test_version():
    out = subprocess.run(CLI + ["--version"], capture_output=True, text=True, check=True, cwd=ROOT).stdout
    assert out.startswith("WebRuleBench ")


def test_users_create_admin_in_separate_data_dir(tmp_path):
    env = {**os.environ, "WRB_DATA_DIR": str(tmp_path)}
    out = subprocess.run(CLI + ["users", "create-admin", "ci-admin"], capture_output=True, text=True, check=True, env=env, cwd=ROOT).stdout
    assert "Token" in out
    users = json.loads((tmp_path / "users.json").read_text())
    assert users["ci-admin"]["role"] == "admin" and "token_hash" in users["ci-admin"]
    assert (tmp_path / "layout_templates.json").exists()          # defaults/ kopyalandı
