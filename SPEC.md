# Wellness card, web version (spec)

Note 2026-11-02 evening: the shipped form has SEVEN items (two Maslach burnout items were added after a literature check) and slightly different wording for items 4 and 5; `docs/ITEMS.md` is authoritative for item text and sources. The hosting and API sections below are current.

Purpose: an anonymous short survey for a surgery residency wellness talk on Tue 2026-11-03 07:00. Residents scan a QR code on a slide and answer on their phones. It mirrors a paper index card handed out in the room, so paper and web answers merge.

Hosting (decided 2026-11-02 evening; Vercel is NOT available for this account right now):
- Frontend: a static page on GitHub Pages, served from the `docs/` folder of this repo on `main`, custom domain `wellness.martingwalsh.solutions` (put that in `docs/CNAME`). It must also work from the fallback origin `https://martinwalsh28nd.github.io/wellness-survey/`.
- Backend: a tiny Python 3 standard-library HTTP server that runs on Martin's Mac mini, bound to 127.0.0.1:8787, and is published by Tailscale Funnel at `https://mini.tailf65cf9.ts.net:10000` (Funnel does the TLS; the server speaks plain HTTP on localhost). No third-party Python packages at all.
- Storage: append-only JSON Lines file, default `~/.local/share/wellness-survey/responses.jsonl` (override with env `WELLNESS_DATA_DIR`). One line per response, written with a lock and flushed.

## Files (keep it to these)
- `docs/index.html` -- the form. Inline CSS and JS, no framework, no build step, no external scripts or fonts. Mobile first (answers come from phones in a lecture hall). Plain, calm, readable at arm's length: system font stack, 18px base, large tap targets, one column, no images. A single constant near the top of the script: `const API_BASE = "https://mini.tailf65cf9.ts.net:10000";` and it POSTs JSON to `API_BASE + "/api/submit"`.
- `docs/CNAME` -- `wellness.martingwalsh.solutions`
- `docs/robots.txt` -- disallow all. Also `<meta name="robots" content="noindex">` in the page.
- `server/wellness_server.py` -- Python 3.11+ standard library only (`http.server.ThreadingHTTPServer`, `json`, `threading`, `pathlib`, `os`, `time`, `re`, `secrets`). Routes:
  - `OPTIONS *` -- CORS preflight.
  - `POST /api/submit` -- JSON body, max 4 KB. Validate (see privacy rules), append one JSON line with a server timestamp (`ts`, ISO 8601 UTC) and the answers, return `{"ok": true}`. Anything malformed: 400. Wrong content type: 415. Too big: 413.
  - `GET /api/results?key=...` -- requires `key` equal to env `WELLNESS_RESULTS_KEY` (401 otherwise). Returns JSON by default: `n`, counts per item (yes/no/blank), counts per fix option A-F, free-text answers newest first, and a `csv` string with one row per response. If the `Accept` header includes `text/html`, return a tiny HTML table of the same data (readable on a phone). Also `?format=csv` returns the CSV with `text/csv`.
  - `GET /api/health` -- `{"ok": true, "n": <count>}`.
  - CORS: `Access-Control-Allow-Origin` only for `https://wellness.martingwalsh.solutions` and `https://martinwalsh28nd.github.io` (echo the matching origin; otherwise omit the header). Allow `POST, GET, OPTIONS`, header `Content-Type`. `Cache-Control: no-store` on every API response. `X-Robots-Tag: noindex`.
  - In-memory rate limit: at most 10 POSTs per minute per client address, 429 beyond that. The address is used only for that counter and is never written anywhere.
  - Config by env: `WELLNESS_PORT` (default 8787), `WELLNESS_DATA_DIR`, `WELLNESS_RESULTS_KEY`. Log one line per request to stdout with method, path, status, and nothing else (no addresses, no bodies).
- `launchd/com.martin.wellness-survey.plist` -- a LaunchAgent that runs the server with `python3` at login and keeps it alive, logging to `~/Library/Logs/wellness-survey.log`. Do NOT install it; just write the file (Martin installs LaunchAgents himself).
- `scripts/smoke.sh` -- takes a base URL and the results key, POSTs one sample response with curl, then fetches `/api/results` and prints `n`.
- `README.md` -- 20 lines max: what it is, how to run the server locally, the env vars, how Funnel exposes it, how GitHub Pages serves `docs/`, how to read results.

## The form (exact wording, same as the paper card)
Heading: "Wellness card". Subheading: "no names, no PGY year. takes about 30 seconds."
1. Do you have a mentor who genuinely cares about you and your career?  Yes / No
2. Are you satisfied with how the program responds to resident concerns?  Yes / No
3. Are you unhappy with your time for routine health stuff (doctor, dentist)?  Yes / No
4. Fix first (pick one):
   A) a monthly "here's what changed" on what comes in through the anonymous channel
   B) Big Sib: every intern gets a senior who isn't grading them
   C) out by 10 means out by 10, and someone covers
   D) protected didactics that stay protected
   E) float: Friday chief chat, real resident input on schedules
   F) workroom: 3 more computers and a printer that works
5. One thing that makes the day worse and could be fixed (optional, free text, 500 chars max)
Button: "Send it". Yes/No and A-F are big toggle buttons or radio cards, not tiny radios.

After a successful submit, replace the form with: "Thanks. For comparison, nationally: 67% have a mentor who genuinely cares, 72% are satisfied with program responsiveness, 48% are unhappy with time for their own doctor/dentist." plus a line "You can close this." Set `localStorage.wellnessCardSent = 1` and on reload show the thanks view instead of the form (soft one-per-device; no server-side device tracking).

## Field keys (stable; the question wording may still be adjusted after a literature check, the keys will not)
`mentor` (yes/no), `responsive` (yes/no), `health_time` (yes/no), `fix_first` (A-F), `free_text` (string). Also accept two optional burnout items that may be added: `burnout_ee` and `burnout_dp`, each one of `never, few_times_year, monthly, few_times_month, weekly, few_times_week, daily` (the MBI frequency scale). Tally those too if present (count of weekly-or-more). Build the form so adding a question is a one-block edit in index.html.

## Privacy rules (hard)
- Store ONLY the five answers and a server timestamp. No IP, no user agent, no cookies, no analytics, no third-party requests of any kind.
- A hidden honeypot text field named `website`; if filled, return 200 `{ ok: true }` and store nothing.
- Cap free text at 500 chars server side; strip control characters.
- All five fields optional on the server (a card with blanks is still a card), but the client requires at least one answer before enabling the button.
- Free-text answers are shown only on the key-protected results endpoint.

## Env vars
- `WELLNESS_RESULTS_KEY` (random string)
- `WELLNESS_DATA_DIR`, `WELLNESS_PORT` (optional)

## Done looks like
`python3 server/wellness_server.py` serves on 127.0.0.1:8787; `scripts/smoke.sh http://127.0.0.1:8787 <key>` posts one response and prints n=1; opening `docs/index.html` from a local static server (`python3 -m http.server -d docs 8000`) shows the form and a submit against the local API succeeds when `API_BASE` is pointed at it. No tests beyond the smoke script, no bundler, no dependencies. Do not commit; leave the working tree for review.
