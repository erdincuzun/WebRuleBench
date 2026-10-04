# Reviewer demo

Try WebRuleBench in two minutes — no LLM, API key or real data needed:

```bash
pip install -e .
webrulebench demo          # or ./run_demo.sh — serves http://127.0.0.1:5002
```

or with Docker:

```bash
docker build -t webrulebench . && docker run --rm -p 5002:5002 webrulebench
```

On first run the demo data are generated into `demo/data/` (not in the repository; the pages are
synthetic and deterministic, so everyone gets the same data). The login for the admin user
`reviewer` is printed and saved in `demo/data/REVIEWER_LOGIN.txt`. Use `--rebuild` to start fresh.

The demo code lives in [`webrulebench/demo/`](../webrulebench/demo/):
`generate_pages.py` (three synthetic news sites), `setup_demo.py` (annotators, ground truth,
replay LLM models, ready experiments). See the main [README](../README.md#try-it-in-two-minutes-reviewer-demo)
for a suggested tour.
