# Equity research agent — runbook

This repo holds the JSON output of an automated equity-research agent, which a website reads.
A scheduled task runs on weekdays at about 6:30am ET. Each run follows this file from top to bottom.

## Layout

```
config/watchlist.json        stocks to cover + timing settings (edit by hand)
schema/research.schema.json  JSON Schema for every file under data/
scripts/er.py                plan | build | validate
data/index.json              website entry point (generated)
data/<T>/latest.json         one snapshot per stock for the website (generated)
data/<T>/state.json          where the stock is in its cycle (agent-maintained)
data/<T>/initiation.json     initiation report (once; again only if watchlist sets reinitiate)
data/<T>/thesis.json         living thesis, append-only log
data/<T>/catalysts.json      event calendar
data/<T>/model.json          estimates; changes appended on each update
data/<T>/previews/<YYYY-QN>.json   earnings previews
data/<T>/earnings/<YYYY-QN>.json   earnings analyses
data/<T>/notes/<YYYY-MM-DD>.json   morning notes
data/<T>/sector/<YYYY-MM>.json     monthly sector refresh
data/runs/<YYYY-MM-DD>.json  run log
```

Never hand-edit `latest.json` or `index.json`. They are rebuilt by `scripts/er.py build`.

## Run procedure

1. `git pull --ff-only`, then `pip install --break-system-packages -q jsonschema` if it's missing.
2. `python3 scripts/er.py plan` prints the tasks due today for each stock, in order. Run **exactly** those tasks, in that order. Don't add or skip any.
   On a weekend or US market holiday, still run the plan, but only do `catalysts` and the `earnings` group if they're listed. Skip `morning_note`.
3. For each task:
   - Load the skill named in the plan with the Skill tool, and use its workflow for the analysis.
     **Override:** the output goes into the JSON file below, not a DOCX/XLSX/markdown deliverable. Long-form prose goes in `body_md`.
     If the skill isn't available in the session, do the same analysis by following the task notes below.
   - Research with WebSearch/WebFetch. Use primary sources first (company IR, SEC filings, earnings releases and transcripts), then reputable financial press.
   - Write the output file. Then update `state.json` as the table below says.
4. If the morning note sets `thesis_update_triggered: true`, run `thesis_update` (append to `thesis.log` and adjust pillars/conviction if warranted).
5. Write `data/runs/<run_date>.json` (type `run_log`): one entry per task with `ok` / `skipped` / `failed`, the reason, and the output paths.
6. `python3 scripts/er.py build`, then `python3 scripts/er.py validate`. Fix every validation error before continuing.
7. Commit everything to `main` with the message `run <run_date>: <tickers> — <task list>` and push.
   Use `git -c push.negotiate=true push`. If the push is rejected, pull, rebase, rebuild, validate and push again.

If a task fails (for example, sources can't be found), log it as `failed` with the reason, leave its state flags unchanged so the next run retries it, and carry on with the other tasks.

## Tasks → outputs → state updates

| Task | Output | State update |
|---|---|---|
| `initiate` | `initiation.json` + `model.json` (first version) | `initiated: true`, `initiated_on`, set `last_earnings` (most recent reported quarter, all flags true) and `next_earnings`; set `reinitiate: false` in the watchlist if it was true |
| `thesis_write` | `thesis.json` | — |
| `earnings` | `earnings/<Q>.json` | move `next_earnings` → `last_earnings` with `analyzed: true, model_updated: false, thesis_checked: false`; set `next_earnings: null` |
| `model_update` | `model.json` (replace estimates; **append** to `changes`) | `last_earnings.model_updated: true` |
| `thesis_check` / `thesis_review` / `thesis_update` | `thesis.json` (**append** to `log`; update pillars, status, conviction, `last_reviewed`, `review_due` = +90 days) | `last_earnings.thesis_checked: true` for `thesis_check` |
| `earnings_preview` | `previews/<Q>.json` | `next_earnings.preview_done: true` |
| `catalysts` | `catalysts.json` (mark past events `occurred` with an `outcome`; add new ones; horizon = `catalyst_horizon_days`) | set or refresh `next_earnings` from the earnings event (`confirmed` true only if the company announced it) |
| `sector` | `sector/<YYYY-MM>.json` | — |
| `morning_note` | `notes/<run_date>.json` | — |

After every task that succeeds, set `state.last_run.<task> = run_date`. Also recompute `state.phase`:
`pre_earnings` if the next report is ≤ `preview_window_days` away; `post_earnings` if the last report was ≤ `post_earnings_window_days` ago or any post-earnings flag is false; otherwise `quiet`.
Set `state.generated_at`, `as_of` and `summary` on every write.

## Task notes (fallback if the skill isn't loaded)

- **initiate** — Business description, segments with TTM revenue, 3 historical fiscal years plus the current year and 2 years of estimates (`kind: estimate` for ours, `consensus` where sourced), valuation with at least 2 methods (e.g. P/E on next-year EPS, DCF), a fair-value range, competitive position, key risks.
- **thesis** — 3–5 falsifiable pillars, 3–5 risks with observable triggers, explicit falsifiers, a fair-value range. Record disconfirming evidence as carefully as confirming evidence.
- **earnings_preview** — Sourced consensus with its date, what to watch ranked, bull/base/bear scenarios, options-implied move if a source has it.
- **earnings** — Results vs consensus (revenue, EPS, segments, margins, capex, FCF), guidance, highlights and lowlights, the stock's reaction, impact on each thesis pillar.
- **model_update** — Roll actuals in, revise the forward estimates, and log every change with old/new values and a reason.
- **catalysts** — Earnings, product events, legal/regulatory rulings, conferences, and relevant macro (FOMC, CPI).
- **morning_note** — Last close, overnight and recent developments with a view on each, events ahead. "Nothing material" is a valid note: set `no_material_news: true`. Set `thesis_update_triggered` only for news that touches a pillar or risk.

## Rules

- Every number comes from a source fetched in this run, or from an earlier file in this repo. Put each source in `sources` (title, url, accessed). If a figure can't be found, use `null`. Never estimate it in place of a sourced number.
- Label estimates (`kind: estimate`) separately from actuals and consensus. Name the source and date of any consensus figure.
- Units: currency `USD`; dollar amounts in `USD_bn` unless the field says otherwise; EPS in USD per share; percentages as numbers (12.5, not 0.125).
- Dates are ISO `YYYY-MM-DD` in US Eastern time. `generated_at` is a UTC ISO timestamp.
- Write in your own words. Don't copy article text; quotes stay under 15 words, at most one per source.
- Language: describe a `stance` (positive / neutral / negative) and a `conviction`. Don't write buy/sell instructions or position-sizing advice. Every document carries the `disclaimer` "Automated research output generated by an AI agent from public sources. Not investment advice."
- History is append-only. Don't delete notes, earnings files, thesis log entries or model changes.
