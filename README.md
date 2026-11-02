# Wellness card
Anonymous residency wellness survey; static form and Python 3.11+ standard-library API.

Run from this directory:
```sh
export WELLNESS_RESULTS_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 server/wellness_server.py
```
The API binds to `127.0.0.1:8787`. `WELLNESS_RESULTS_KEY` protects results; keep it private.
Optional: `WELLNESS_PORT` (8787), `WELLNESS_DATA_DIR` (`~/.local/share/wellness-survey`); responses append to `responses.jsonl`.
Smoke check: `scripts/smoke.sh http://127.0.0.1:8787 "$WELLNESS_RESULTS_KEY"` adds one sample card and prints `n`. Delete that line from `responses.jsonl` before quoting numbers.
Funnel: `tailscale funnel --bg --https=10000 http://127.0.0.1:8787` exposes `https://mini.tailf65cf9.ts.net:10000`.
GitHub Pages: select `main` and `/docs`; set custom domain `wellness.martingwalsh.solutions` (also in `docs/CNAME`).
Fallback frontend: `https://martinwalsh28nd.github.io/wellness-survey/`.
JSON results: `curl --get --data-urlencode "key=$WELLNESS_RESULTS_KEY" https://mini.tailf65cf9.ts.net:10000/api/results`.
Add `-H 'Accept: text/html'` for a phone-readable table or `--data-urlencode 'format=csv'` for CSV.
In a browser, open `/api/results?key=YOUR_URL_ENCODED_KEY` on the API origin; append `&format=csv` for CSV.
Local layout preview: `python3 -m http.server -d docs 8000`; production-only CORS blocks cross-origin localhost submissions, even with a local `API_BASE`.
`launchd/com.martin.wellness-survey.plist` is a template: replace its key placeholder with your random secret before Martin manually installs it.
The template uses absolute Mac mini paths and logs to `/Users/martin/Library/Logs/wellness-survey.log`; it is not installed or loaded here.
