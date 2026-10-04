#!/bin/bash
# Web application (data/, port 5001). Same as: webrulebench serve
cd "$(dirname "$0")"
python -m webrulebench serve "$@"
