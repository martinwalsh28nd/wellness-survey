#!/usr/bin/env python3
"""Anonymous wellness cards, served on localhost with standard-library Python."""

import csv
import html
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


CARD_ID = re.compile(r"[A-Za-z0-9-]{8,64}")
ALLOWED_ORIGINS = {
    "https://wellness.martingwalsh.solutions",
    "http://wellness.martingwalsh.solutions",  # served over http until GitHub issues the certificate
    "https://martinwalsh28nd.github.io",
}
YES_NO_FIELDS = ("mentor", "responsive", "health_time")
ANSWER_FIELDS = (*YES_NO_FIELDS, "fix_first", "free_text")
BURNOUT_FIELDS = ("burnout_ee", "burnout_dp")
FREQUENCIES = (
    "never", "few_times_year", "monthly", "few_times_month",
    "weekly", "few_times_week", "daily",
)
FIX_OPTIONS = tuple("ABCDEF")
# Mistreatment: frequency scale and sources as in Hu et al., N Engl J Med 2019.
MISTREAT_FREQ = ("never", "few_times_year", "few_times_month", "few_times_week", "daily")
MISTREAT_SOURCES = ("attendings", "residents", "patients", "staff", "admin")
CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
MAX_BODY = 4096


def reject_json_constant(value):
    raise ValueError("Invalid JSON constant.")


def validate_answers(payload):
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object.")
    website = payload.get("website", "")
    if not isinstance(website, str):
        raise ValueError("Invalid website field.")
    if website:
        return None

    answers = {}
    for field in ANSWER_FIELDS:
        value = payload.get(field, "")
        if not isinstance(value, str):
            raise ValueError("Answers must be strings.")
        if field in YES_NO_FIELDS and value not in ("", "yes", "no"):
            raise ValueError("Invalid yes/no answer.")
        if field == "fix_first" and value not in ("", *FIX_OPTIONS):
            raise ValueError("Invalid fix option.")
        if field == "free_text":
            value.encode("utf-8")
            value = CONTROLS.sub("", value)[:500]
        answers[field] = value
    for field in BURNOUT_FIELDS:
        if field in payload:
            value = payload[field]
            if not isinstance(value, str) or value not in FREQUENCIES:
                raise ValueError("Invalid burnout frequency.")
            answers[field] = value
    freq = payload.get("mistreat_freq", "")
    if not isinstance(freq, str) or freq not in ("", *MISTREAT_FREQ):
        raise ValueError("Invalid mistreatment frequency.")
    if freq:
        answers["mistreat_freq"] = freq
    sources = payload.get("mistreat_from", [])
    if not isinstance(sources, list) or len(sources) > len(MISTREAT_SOURCES) or any(
            not isinstance(s, str) or s not in MISTREAT_SOURCES for s in sources):
        raise ValueError("Invalid mistreatment source.")
    if sources:
        answers["mistreat_from"] = [s for s in MISTREAT_SOURCES if s in sources]
    card_id = payload.get("card_id")
    if card_id is not None:
        # Random per-card token from the phone; lets a retry after a lost reply
        # land once instead of twice. Not tied to the person or the device.
        if not isinstance(card_id, str) or not CARD_ID.fullmatch(card_id):
            raise ValueError("Invalid card id.")
        answers["card_id"] = card_id
    return answers


def csv_cell(value):
    # Quoting CSV alone does not prevent spreadsheet formula execution.
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def summarize(responses):
    counts = {field: {"yes": 0, "no": 0, "blank": 0} for field in YES_NO_FIELDS}
    fixes = {option: 0 for option in (*FIX_OPTIONS, "blank")}
    burnout = {}
    mistreat = {"freq": dict.fromkeys(MISTREAT_FREQ, 0), "any": 0, "answered": 0,
                "from": dict.fromkeys(MISTREAT_SOURCES, 0)}
    for response in responses:
        freq = response.get("mistreat_freq")
        if freq in mistreat["freq"]:
            mistreat["freq"][freq] += 1
            mistreat["answered"] += 1
            if freq != "never":
                mistreat["any"] += 1
        for source in response.get("mistreat_from") or []:
            if source in mistreat["from"]:
                mistreat["from"][source] += 1
        for field in YES_NO_FIELDS:
            counts[field][response.get(field) or "blank"] += 1
        fixes[response.get("fix_first") or "blank"] += 1
        for field in BURNOUT_FIELDS:
            if field in response:
                tally = burnout.setdefault(field, {
                    "counts": dict.fromkeys(FREQUENCIES, 0), "weekly_or_more": 0,
                })
                value = response[field]
                tally["counts"][value] += 1
                if value in FREQUENCIES[4:]:
                    tally["weekly_or_more"] += 1

    columns = ["ts", *ANSWER_FIELDS]
    columns.extend(field for field in BURNOUT_FIELDS if field in burnout)
    columns.extend(["mistreat_freq", "mistreat_from"])
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    for response in responses:
        row = []
        for field in columns:
            value = response.get(field, "")
            row.append(csv_cell(";".join(value) if isinstance(value, list) else value))
        writer.writerow(row)
    return {
        "n": len(responses),
        "counts": counts,
        "fix_first": fixes,
        "burnout": burnout,
        "mistreatment": mistreat,
        "free_text": [
            response["free_text"] for response in reversed(responses)
            if response.get("free_text")
        ],
        "csv": output.getvalue(),
    }


def results_html(result):
    def table(headers, rows):
        head = "".join(f"<th scope='col'>{html.escape(str(cell))}</th>" for cell in headers)
        body = "".join(
            "<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>"
            for row in rows
        )
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    labels = {
        "mentor": "Mentor who cares",
        "responsive": "Satisfied with program response",
        "health_time": "Unhappy with time for own health",
    }
    parts = [
        "<!doctype html><html lang='en'><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<meta name='robots' content='noindex'><title>Wellness card results</title>",
        "<style>body{font:18px system-ui,sans-serif;margin:1rem auto;padding:0 1rem;",
        "max-width:44rem;line-height:1.5}table{border-collapse:collapse;width:100%;",
        "margin-bottom:1.5rem}th,td{text-align:left;vertical-align:top;padding:.5rem;",
        "border-bottom:1px solid #ccc;overflow-wrap:anywhere}h2{font-size:1.2rem}",
        "pre{overflow-x:auto;font-size:.8rem}summary{padding:.75rem 0}</style>",
        f"<body><h1>Wellness card results</h1><p>Responses: {result['n']}</p>",
        table(("Item", "Yes", "No", "Blank"), (
            (labels[field], tally["yes"], tally["no"], tally["blank"])
            for field, tally in result["counts"].items()
        )),
        "<h2>Fix first</h2>",
        table(("Option", "Count"), result["fix_first"].items()),
    ]
    for field, tally in result["burnout"].items():
        parts.extend([
            f"<h2>{html.escape(field)}</h2>",
            table(("Frequency", "Count"), tally["counts"].items()),
            f"<p>Weekly or more: {tally['weekly_or_more']}</p>",
        ])
    mt = result["mistreatment"]
    parts.extend([
        f"<h2>Mistreatment since starting residency</h2><p>Any: {mt['any']} of {mt['answered']} who answered</p>",
        table(("Frequency", "Count"), mt["freq"].items()),
        "<h2>From whom (pick all that apply)</h2>",
        table(("Source", "Count"), mt["from"].items()),
    ])
    parts.extend([
        "<h2>Free text, newest first</h2>",
        table(("Answer",), ((answer,) for answer in result["free_text"])),
        "<details><summary>CSV (one row per response)</summary><pre>",
        html.escape(result["csv"]),
        "</pre></details>",
        "</body></html>",
    ])
    return "".join(parts)


class WellnessServer(ThreadingHTTPServer):
    def __init__(self, port, data_dir, results_key):
        self.data_file = data_dir / "responses.jsonl"
        data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.results_key = results_key
        self.storage_lock = threading.Lock()
        self.rate_lock = threading.Lock()
        self.post_times = {}
        self.seen_ids = {r["card_id"] for r in self.read_responses()
                         if isinstance(r, dict) and r.get("card_id")}
        super().__init__(("127.0.0.1", port), WellnessHandler)

    def admit_post(self, address):
        now = time.monotonic()
        with self.rate_lock:
            for client, times in list(self.post_times.items()):
                recent = [stamp for stamp in times if now - stamp < 60]
                if recent:
                    self.post_times[client] = recent
                else:
                    del self.post_times[client]
            times = self.post_times.setdefault(address, [])
            if len(times) >= 30:
                return False
            times.append(now)
            return True

    def append_response(self, answers):
        response = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **answers}
        line = json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n"
        card_id = answers.get("card_id")
        with self.storage_lock:
            if card_id and card_id in self.seen_ids:
                return  # already stored; the phone is retrying after a lost reply
            descriptor = os.open(self.data_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
            if card_id:
                self.seen_ids.add(card_id)

    def read_responses(self):
        with self.storage_lock:
            try:
                responses = []
                with self.data_file.open(encoding="utf-8") as stream:
                    for line in stream:
                        if not line.strip():
                            continue
                        try:
                            responses.append(json.loads(line))
                        except ValueError:
                            continue  # a torn line must not take the tally down
                return responses
            except FileNotFoundError:
                return []

    def handle_error(self, request, client_address):
        # The default handler prints a client address and traceback to stderr.
        pass


class WellnessHandler(BaseHTTPRequestHandler):
    server_version = "wellness"
    sys_version = ""
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_request(self, code="-", size="-"):
        path = CONTROLS.sub("", getattr(self, "path", "/").partition("?")[0])
        method = CONTROLS.sub("", self.command or "")
        print(f"{method} {path} {code}", flush=True)

    def log_message(self, format, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.respond(code, {"error": self.responses.get(code, ("Request failed",))[0]})

    def respond(self, status, body=None, content_type="application/json; charset=utf-8"):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=True)
        encoded = (body or "").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Vary", "Origin")
        origin = self.headers.get("Origin") if hasattr(self, "headers") else None
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        if status == 429:
            self.send_header("Retry-After", "60")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(encoded)

    def do_OPTIONS(self):
        self.respond(204)

    def rate_address(self):
        peer = self.client_address[0]
        forwarded = self.headers.get_all("X-Forwarded-For", [])
        markers = self.headers.get_all("Tailscale-Funnel-Request", [])
        # Funnel overwrites both headers; trust them only on the local proxy hop.
        if ipaddress.ip_address(peer).is_loopback and markers == ["?1"] and len(forwarded) == 1:
            first_hop = forwarded[0].split(",", 1)[0].strip()
            try:
                return str(ipaddress.ip_address(first_hop))
            except ValueError:
                pass
        return peer

    def do_POST(self):
        if self.path.partition("?")[0] != "/api/submit":
            self.respond(404, {"error": "Not found."})
            return
        if self.headers.get_content_type() != "application/json":
            self.respond(415, {"error": "Use application/json."})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if (self.headers.get("Transfer-Encoding") is not None or len(lengths) != 1
                or not re.fullmatch(r"[0-9]+", lengths[0])):
            self.respond(400, {"error": "Invalid request body length."})
            return
        length_text = lengths[0].lstrip("0") or "0"
        if len(length_text) > 4 or int(length_text) > MAX_BODY:
            self.respond(413, {"error": "Request body exceeds 4 KB."})
            return
        length = int(length_text)
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("Incomplete body.")
            payload = json.loads(raw.decode("utf-8"), parse_constant=reject_json_constant)
            answers = validate_answers(payload)
        except (ValueError, UnicodeError, RecursionError, OSError):
            self.respond(400, {"error": "Invalid answers or JSON body."})
            return
        if answers is not None:
            card_id = answers.get("card_id")
            if card_id and card_id in self.server.seen_ids:
                self.respond(200, {"ok": True})  # a retry of a stored card; no rate token
                return
            if not self.server.admit_post(self.rate_address()):
                self.respond(429, {"error": "Too many submissions. Try again in a minute."})
                return
            try:
                self.server.append_response(answers)
            except OSError:
                self.respond(500, {"error": "Could not save the response. Try again."})
                return
        self.respond(200, {"ok": True})

    def do_GET(self):
        try:
            route = urlsplit(self.path)
        except ValueError:
            self.respond(400, {"error": "Invalid request path."})
            return
        if route.path not in ("/api/health", "/api/results"):
            self.respond(404, {"error": "Not found."})
            return
        query = parse_qs(route.query, keep_blank_values=True)
        if route.path == "/api/results":
            keys = query.get("key", [])
            if (not self.server.results_key or len(keys) != 1 or not secrets.compare_digest(
                    keys[0].encode("utf-8"), self.server.results_key.encode("utf-8"))):
                self.respond(401, {"error": "Unauthorized."})
                return
        try:
            responses = self.server.read_responses()
            result = summarize(responses) if route.path == "/api/results" else None
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            self.respond(500, {"error": "Could not read responses."})
            return
        if route.path == "/api/health":
            self.respond(200, {"ok": True, "n": len(responses)})
        elif query.get("format") == ["csv"]:
            self.respond(200, result["csv"], "text/csv; charset=utf-8")
        elif "text/html" in self.headers.get("Accept", "").lower():
            self.respond(200, results_html(result), "text/html; charset=utf-8")
        else:
            self.respond(200, result)


def main():
    port = int(os.environ.get("WELLNESS_PORT", "8787"))
    data_dir = Path(os.environ.get("WELLNESS_DATA_DIR", "~/.local/share/wellness-survey")).expanduser()
    server = WellnessServer(port, data_dir, os.environ.get("WELLNESS_RESULTS_KEY", ""))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
