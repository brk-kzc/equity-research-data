#!/usr/bin/env python3
"""Equity research pipeline helper.

  python3 scripts/er.py plan [--date YYYY-MM-DD]   # which tasks are due today, per stock (JSON to stdout)
  python3 scripts/er.py build                      # regenerate data/<T>/latest.json and data/index.json
  python3 scripts/er.py validate                   # validate every JSON file under data/ against the schema

The plan is deterministic: the agent runs exactly the tasks it lists, in order.
"""
import argparse
import datetime as dt
import glob
import json
import os
import sys
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
WATCHLIST = os.path.join(ROOT, "config", "watchlist.json")
SCHEMA = os.path.join(ROOT, "schema", "research.schema.json")

TASK_ORDER = [
    "initiate", "thesis_write", "earnings", "model_update", "thesis_check",
    "earnings_preview", "catalysts", "thesis_review", "sector", "morning_note",
]
SKILL = {
    "initiate": "equity-research:initiating-coverage",
    "thesis_write": "equity-research:thesis-tracker",
    "earnings": "equity-research:earnings-analysis",
    "model_update": "equity-research:model-update",
    "thesis_check": "equity-research:thesis-tracker",
    "thesis_review": "equity-research:thesis-tracker",
    "thesis_update": "equity-research:thesis-tracker",
    "earnings_preview": "equity-research:earnings-preview",
    "catalysts": "equity-research:catalyst-calendar",
    "sector": "equity-research:sector-overview",
    "morning_note": "equity-research:morning-note",
}


def load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def d(s):
    return dt.date.fromisoformat(s) if s else None


def today_et(cfg):
    return dt.datetime.now(ZoneInfo(cfg.get("timezone", "America/New_York"))).date()


def plan_for(stock, cfg, today):
    s = cfg["settings"]
    t = stock["ticker"]
    state = load(os.path.join(DATA, t, "state.json"))
    tasks, why = [], {}

    def add(task, reason):
        if task not in tasks:
            tasks.append(task)
            why[task] = reason

    if not state or not state.get("initiated") or stock.get("reinitiate"):
        add("initiate", "not initiated" if not stock.get("reinitiate") else "reinitiate flag set in watchlist")
        add("thesis_write", "new coverage needs a thesis")
        add("catalysts", "new coverage needs a catalyst calendar")
        add("morning_note", "daily")
    else:
        last_run = state.get("last_run", {})
        ne = state.get("next_earnings") or None
        le = state.get("last_earnings") or None

        # Earnings has happened?
        if ne and ne.get("date"):
            rd = d(ne["date"])
            reported = rd < today or (rd == today and ne.get("timing") == "pre_market")
            if reported:
                add("earnings", f"{ne.get('quarter')} reported {ne['date']}")
                add("model_update", "after earnings")
                add("thesis_check", "after earnings")
                add("catalysts", "roll calendar forward after earnings")
            elif 0 <= (rd - today).days <= s["preview_window_days"] and not ne.get("preview_done"):
                add("earnings_preview", f"{ne.get('quarter')} reports in {(rd - today).days} days")
        # Unfinished post-earnings steps from an earlier run
        if le and le.get("analyzed"):
            if not le.get("model_updated"):
                add("model_update", f"{le.get('quarter')} model not yet updated")
            if not le.get("thesis_checked"):
                add("thesis_check", f"{le.get('quarter')} thesis not yet checked")

        lc = d(last_run.get("catalysts"))
        if not ne or not ne.get("date") or lc is None or (today - lc).days >= s["catalyst_refresh_days"]:
            add("catalysts", "weekly refresh" if ne and ne.get("date") else "next earnings date unknown")

        thesis = load(os.path.join(DATA, t, "thesis.json"))
        if thesis and thesis.get("review_due") and d(thesis["review_due"]) <= today and "thesis_check" not in tasks:
            add("thesis_review", f"periodic review due {thesis['review_due']}")

        ls = d(last_run.get("sector"))
        if today.day <= s["sector_refresh_day_of_month"] + 3 and (ls is None or (ls.year, ls.month) != (today.year, today.month)):
            add("sector", "monthly refresh")

        add("morning_note", "daily")

    ordered = [x for x in TASK_ORDER if x in tasks]
    return {
        "ticker": t,
        "tasks": [{"task": x, "skill": SKILL[x], "reason": why[x]} for x in ordered],
        "conditional": [{"task": "thesis_update", "skill": SKILL["thesis_update"],
                         "when": "morning_note.thesis_update_triggered is true (material news)"}],
    }


def cmd_plan(args):
    cfg = load(WATCHLIST)
    today = d(args.date) if args.date else today_et(cfg)
    out = {"run_date": today.isoformat(), "weekday": today.strftime("%A"),
           "stocks": [plan_for(st, cfg, today) for st in cfg["stocks"] if st.get("active", True)]}
    json.dump(out, sys.stdout, indent=2)
    print()


def newest(pattern):
    files = sorted(glob.glob(pattern))
    return files[-1] if files else None


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/") if p else None


def cmd_build(_args):
    cfg = load(WATCHLIST)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    stocks = []
    for st in cfg["stocks"]:
        if not st.get("active", True):
            continue
        t = st["ticker"]
        base = os.path.join(DATA, t)
        state = load(os.path.join(base, "state.json"), {})
        thesis = load(os.path.join(base, "thesis.json"), {})
        cats = load(os.path.join(base, "catalysts.json"), {})
        init = load(os.path.join(base, "initiation.json"), {})
        model = load(os.path.join(base, "model.json"), {})
        note_p = newest(os.path.join(base, "notes", "*.json"))
        earn_p = newest(os.path.join(base, "earnings", "*.json"))
        prev_p = newest(os.path.join(base, "previews", "*.json"))
        note, earn, prev = load(note_p, {}) if note_p else {}, load(earn_p, {}) if earn_p else {}, load(prev_p, {}) if prev_p else {}
        upcoming = sorted([e for e in cats.get("events", []) if e.get("status") == "upcoming"], key=lambda e: e["date"])[:8]
        md = init.get("market_data", {})
        price = (note.get("market") or {}).get("last_close") or md.get("price")
        fv = thesis.get("fair_value") or {}
        latest = {
            "schema_version": "1.0", "type": "latest", "ticker": t, "name": st.get("name"),
            "generated_at": now,
            "phase": state.get("phase"),
            "price": price,
            "price_date": (note.get("market") or {}).get("close_date") or md.get("price_date"),
            "stance": thesis.get("stance"), "conviction": thesis.get("conviction"),
            "thesis_status": thesis.get("thesis_status"), "thesis_statement": thesis.get("statement"),
            "fair_value": fv or None,
            "upside_to_base_pct": round((fv["base"] / price - 1) * 100, 1) if fv.get("base") and price else None,
            "pillars": [{k: p.get(k) for k in ("id", "title", "status", "trend")} for p in thesis.get("pillars", [])],
            "next_earnings": state.get("next_earnings"),
            "last_earnings": {"quarter": earn.get("quarter"), "report_date": earn.get("report_date"),
                              "verdict": earn.get("verdict"), "summary": earn.get("summary")} if earn else None,
            "latest_note": {"date": note.get("as_of"), "headline": note.get("headline"), "summary": note.get("summary")} if note else None,
            "latest_preview": {"quarter": prev.get("quarter"), "report_date": prev.get("report_date"), "summary": prev.get("summary")} if prev else None,
            "upcoming_catalysts": upcoming,
            "recent_thesis_log": sorted(thesis.get("log", []), key=lambda x: x["date"], reverse=True)[:5],
            "model_updated_through": model.get("updated_through"),
            "files": {
                "state": rel(os.path.join(base, "state.json")),
                "initiation": rel(os.path.join(base, "initiation.json")) if init else None,
                "thesis": rel(os.path.join(base, "thesis.json")) if thesis else None,
                "catalysts": rel(os.path.join(base, "catalysts.json")) if cats else None,
                "model": rel(os.path.join(base, "model.json")) if model else None,
                "latest_note": rel(note_p), "latest_earnings": rel(earn_p), "latest_preview": rel(prev_p),
                "notes": [rel(p) for p in sorted(glob.glob(os.path.join(base, "notes", "*.json")), reverse=True)[:30]],
                "earnings": [rel(p) for p in sorted(glob.glob(os.path.join(base, "earnings", "*.json")), reverse=True)],
                "previews": [rel(p) for p in sorted(glob.glob(os.path.join(base, "previews", "*.json")), reverse=True)],
            },
            "disclaimer": "Automated research output generated by an AI agent from public sources. Not investment advice.",
        }
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, "latest.json"), "w") as f:
            json.dump(latest, f, indent=2)
            f.write("\n")
        stocks.append({k: latest[k] for k in ("ticker", "name", "phase", "price", "price_date", "stance", "conviction",
                                              "thesis_status", "fair_value", "upside_to_base_pct", "next_earnings")}
                      | {"headline": (latest["latest_note"] or {}).get("headline"), "latest": rel(os.path.join(base, "latest.json"))})
    last_run = newest(os.path.join(DATA, "runs", "*.json"))
    index = {"schema_version": "1.0", "type": "index", "generated_at": now,
             "last_run_log": rel(last_run), "stocks": stocks}
    with open(os.path.join(DATA, "index.json"), "w") as f:
        json.dump(index, f, indent=2)
        f.write("\n")
    print(f"built index.json and {len(stocks)} latest.json file(s)")


def cmd_validate(_args):
    from jsonschema import Draft202012Validator, FormatChecker
    schema = load(SCHEMA)
    errors = 0
    files = sorted(glob.glob(os.path.join(DATA, "**", "*.json"), recursive=True))
    for p in files:
        try:
            doc = load(p)
        except json.JSONDecodeError as e:
            print(f"FAIL {rel(p)}: invalid JSON: {e}")
            errors += 1
            continue
        typ = doc.get("type")
        if typ not in schema["$defs"]:
            print(f"FAIL {rel(p)}: unknown type {typ!r}")
            errors += 1
            continue
        sub = dict(schema)
        sub.pop("oneOf", None)
        sub = {**sub, "$ref": f"#/$defs/{typ}"}
        v = Draft202012Validator(sub, format_checker=FormatChecker())
        errs = sorted(v.iter_errors(doc), key=lambda e: list(e.path))
        if errs:
            errors += 1
            for e in errs[:10]:
                print(f"FAIL {rel(p)}: {'/'.join(map(str, e.path)) or '<root>'}: {e.message}")
        else:
            print(f"ok   {rel(p)}")
    print(f"\n{len(files)} file(s), {errors} with errors")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("plan"); p.add_argument("--date"); p.set_defaults(fn=cmd_plan)
    sp.add_parser("build").set_defaults(fn=cmd_build)
    sp.add_parser("validate").set_defaults(fn=cmd_validate)
    a = ap.parse_args()
    a.fn(a)
