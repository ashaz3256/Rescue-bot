"""Live dashboard. Reads the newest run in data/runs/ while navigator.py is running.

  python dashboard/app.py     then open http://localhost:5000
"""
import json
import os

from flask import Flask, abort, jsonify, send_from_directory

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RUNS = os.environ.get("RUNS_DIR", os.path.join(ROOT, "data", "runs"))
app = Flask(__name__, static_folder=None)


def latest_run():
    if not os.path.isdir(RUNS):
        return None
    runs = sorted(d for d in os.listdir(RUNS) if os.path.isdir(os.path.join(RUNS, d)))
    return runs[-1] if runs else None


@app.get("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "index.html")


@app.get("/api/run")
def run_state():
    run = latest_run()
    if not run:
        return jsonify({"run": None, "steps": [], "report": None})
    folder = os.path.join(RUNS, run)
    steps = []
    log = os.path.join(folder, "log.jsonl")
    if os.path.exists(log):
        with open(log) as f:
            for line in f:
                try:
                    steps.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    report = None
    rp = os.path.join(folder, "report.json")
    if os.path.exists(rp):
        with open(rp) as f:
            report = json.load(f)
    return jsonify({"run": run, "steps": steps, "report": report})


@app.get("/frames/<run>/<name>")
def frame(run, name):
    folder = os.path.join(RUNS, run)
    if not os.path.isdir(folder) or "/" in name or ".." in name:
        abort(404)
    return send_from_directory(folder, name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
