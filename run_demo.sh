#!/bin/bash
# Reviewer demo: synthetic sites, three annotators, approved ground truth and a replay LLM backend.
# Uses a separate data folder (demo/data/) and port 5002, so it never touches real data. Same as: webrulebench demo
cd "$(dirname "$0")"
python -m webrulebench demo "$@"
