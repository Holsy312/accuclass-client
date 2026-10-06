"""Offline tests: a local mock server stands in for AccuClass. Standard library only.

Run with:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock
from urllib.parse import parse_qs, urlparse

from accuclass_client import DEFAULT_USER_AGENT, JSON_NULL, AccuClass, AccuClassError, __version__
from accuclass_client import cli

TOKEN = "11111111-2222-3333-4444-555555555555"
JOB = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
EXPORT_BYTES = b"\xef\xbb\xbfStudent,Date,Status\r\nAda,2026-09-29,Present\r\n"

# Requests captured from Engineerica's own .NET client (EngineericaApi.dll, run under Mono)
# making the same calls as GoldenRequestTests below. Ours must match byte for byte.
# These check the wire format (GUIDs, dates, nulls, paging args), so they stay valid even
# for actions a given server no longer offers (e.g. attendancelog.listsummary).
GOLDEN = [
    ("login", False, '{"domain":"exampledomain","username":"admin@example.edu","password":"pw","method":"token"}'),
    ("class.list", True, '{"from":0,"count":10}'),
    ("attendancelog.listsummary", True,
     '{"classid":"00000000-0000-0000-0000-000000000001","studentid":"00000000-0000-0000-0000-000000000000",'
     '"start":"2026-09-01","end":"2026-12-31"}'),
    ("session.getschedule", True,
     '{"day":"2026-09-29T09:30:00","student":"00000000-0000-0000-0000-000000000000",'
     '"classroom":"00000000-0000-0000-0000-000000000000","instructor":"00000000-0000-0000-0000-000000000000"}'),
    ("export", True, '{"exporttype":5,"exportformat":"CSV"}'),
    ("bgjob.getstatus", True, '{"jobid":"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee","jobtype":null}'),
    ("logout", True, "{}"),
]


class MockAccuClass:
    """A tiny fake of the AccuClass Service API, recording every request it receives."""

    def __init__(self, n_classes: int = 10, accept_formats=("CSV",), polls_until_done: int = 2):
        self.requests: list = []
        self.classes = [{"Id": str(uuid.UUID(int=i)), "Name": f"Class {i}"} for i in range(1, n_classes + 1)]
        self.accept_formats = accept_formats
        self.polls_until_done = polls_until_done
        self.polls = 0
        self.override = {}  # action -> (status_code, raw body bytes)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code: int, body: bytes, headers=None):
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                outer.requests.append({"method": "GET", "path": self.path,
                                       "user_agent": self.headers.get("User-Agent")})
                if self.path == f"/JobResults/{JOB}.csv":
                    return self._send(200, EXPORT_BYTES)
                self._send(404, b"not found")

            def do_POST(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n).decode("utf-8")
                outer.requests.append({"method": "POST", "path": u.path, "query": q, "body": raw,
                                       "content_type": self.headers.get("Content-Type"),
                                       "user_agent": self.headers.get("User-Agent")})
                action = q.get("action")
                if action in outer.override:
                    code, body, headers = outer.override[action]
                    return self._send(code, body, headers)
                self._send(200, json.dumps(outer.respond(action, q, json.loads(raw or "{}"))).encode())

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def respond(self, action, q, body):
        if action == "login":
            if body.get("password") != "pw":
                return {"success": False, "message": "Invalid credentials"}
            return {"success": True, "token": TOKEN, "FullName": "Test Admin"}
        if q.get("token") != TOKEN:
            return {"success": False, "message": "Not authenticated"}
        if action == "class.list":
            start, count = body.get("from", 0), body.get("count", 10)
            return {"success": True, "results": self.classes[start:start + count]}
        if action == "export":
            if body.get("exportformat") not in self.accept_formats:
                return {"success": False, "message": "Unable to execute action."}
            self.polls = 0
            return {"success": True, "JobId": JOB, "results": []}
        if action == "bgjob.getstatus":
            self.polls += 1
            done = self.polls >= self.polls_until_done
            statuses = [{"Message": "Export started"}] + ([{"Message": "Export finished"}] if done else [])
            return {"success": True, "results": [{"Id": JOB, "Succeed": done, "Statuses": statuses}]}
        return {"success": True, "results": []}

    def posts(self, action=None):
        return [r for r in self.requests if r["method"] == "POST" and (action is None or r["query"]["action"] == action)]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class ServerTestCase(unittest.TestCase):
    server_kwargs: dict = {}

    def setUp(self):
        # keep the tests independent of the machine's proxy and AccuClass settings
        patcher = mock.patch.dict(os.environ, {"NO_PROXY": "*", "no_proxy": "*"})
        patcher.start()
        self.addCleanup(patcher.stop)
        for var in ("ACCUCLASS_URL", "ACCUCLASS_USER_AGENT", "ACCUCLASS_DOMAIN", "ACCUCLASS_USER",
                    "ACCUCLASS_PASSWORD", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ.pop(var, None)
        self.mock = MockAccuClass(**self.server_kwargs)
        self.addCleanup(self.mock.close)

    def client(self, **kw) -> AccuClass:
        return AccuClass(self.mock.url, **kw)


class GoldenRequestTests(ServerTestCase):
    def test_requests_match_official_dotnet_client(self):
        c = self.client()
        c.login("exampledomain", "admin@example.edu", "pw")
        c.call("class.list", **{"from": 0, "count": 10})
        empty = uuid.UUID(int=0)
        c.call("attendancelog.listsummary", classid=uuid.UUID(int=1), studentid=empty,
               start="2026-09-01", end="2026-12-31")
        c.call("session.getschedule", day=dt.datetime(2026, 9, 29, 9, 30), student=empty,
               classroom=empty, instructor=empty)
        c.call("export", exporttype=5, exportformat="CSV")
        c.call("bgjob.getstatus", jobid=JOB, jobtype=JSON_NULL)
        c.logout()

        posts = self.mock.posts()
        self.assertEqual(len(posts), len(GOLDEN))
        for req, (action, authed, body) in zip(posts, GOLDEN):
            with self.subTest(action=action):
                self.assertEqual(req["path"], "/Service/")
                expected_query = {"action": action, **({"token": TOKEN} if authed else {})}
                self.assertEqual(req["query"], expected_query)
                self.assertEqual(req["body"], body)
                self.assertIsNone(req["content_type"], "the .NET client sends no Content-Type")


class ProtocolTests(ServerTestCase):
    def test_must_log_in_first(self):
        with self.assertRaisesRegex(AccuClassError, "logged in"):
            self.client().call("class.list")

    def test_bad_login_raises_server_message(self):
        with self.assertRaisesRegex(AccuClassError, "Invalid credentials"):
            self.client().login("d", "u", "wrong")

    def test_none_omitted_json_null_sent(self):
        c = self.client()
        c.login("d", "u", "pw")
        c.call("search", query=None, keep=JSON_NULL, n=0)
        self.assertEqual(self.mock.posts("search")[0]["body"], '{"keep":null,"n":0}')

    def test_dates_and_non_ascii(self):
        c = self.client()
        c.login("d", "u", "pw")
        c.call("x", day=dt.date(2026, 1, 2), name="Siân Zoë")
        self.assertEqual(self.mock.posts("x")[0]["body"], '{"day":"2026-01-02T00:00:00","name":"Siân Zoë"}')

    def test_context_manager_logs_out(self):
        with self.client() as c:
            c.login("d", "u", "pw")
        self.assertEqual(len(self.mock.posts("logout")), 1)
        self.assertIsNone(c.token)

    def test_non_json_response(self):
        self.mock.override["login"] = (200, b"<html>not json</html>", {})
        with self.assertRaisesRegex(AccuClassError, "did not return JSON"):
            self.client().login("d", "u", "pw")

    def test_cloudflare_block_explained(self):
        self.mock.override["login"] = (403, b"error code: 1010", {})
        with self.assertRaisesRegex(AccuClassError, "(?s)HTTP 403.*1010.*Cloudflare"):
            self.client().login("d", "u", "pw")

    def test_redirect_is_reported_not_followed(self):
        self.mock.override["login"] = (301, b"", {"Location": "https://elsewhere.example/Service/?action=login"})
        with self.assertRaisesRegex(AccuClassError, "redirected \\(301\\) to https://elsewhere.example"):
            self.client().login("d", "u", "pw")
        self.assertEqual(len(self.mock.requests), 1, "redirect must not be followed")

    def test_unreachable_server(self):
        with self.assertRaisesRegex(AccuClassError, "Could not reach"):
            AccuClass("http://127.0.0.1:9/", timeout=5).login("d", "u", "pw")


class HeaderTests(ServerTestCase):
    def test_default_user_agent_is_browser_not_python(self):
        c = self.client()
        c.login("d", "u", "pw")
        ua = self.mock.requests[0]["user_agent"]
        self.assertEqual(ua, DEFAULT_USER_AGENT)
        self.assertTrue(ua.startswith("Mozilla/5.0"))
        self.assertNotIn("Python-urllib", ua, "Cloudflare blocks Python's built-in User-Agent")

    def test_user_agent_override_argument_and_env(self):
        self.client(user_agent="my-tool/1.0").login("d", "u", "pw")
        with mock.patch.dict(os.environ, {"ACCUCLASS_USER_AGENT": "from-env/2.0"}):
            self.client().login("d", "u", "pw")
        self.assertEqual([r["user_agent"] for r in self.mock.requests], ["my-tool/1.0", "from-env/2.0"])

    def test_content_type_option(self):
        self.client(content_type="application/json").login("d", "u", "pw")
        self.assertEqual(self.mock.requests[0]["content_type"], "application/json")

    def test_base_url_from_env(self):
        with mock.patch.dict(os.environ, {"ACCUCLASS_URL": self.mock.url.rstrip("/")}):
            c = AccuClass()
        self.assertEqual(c.base_url, self.mock.url)


class PagingTests(ServerTestCase):
    server_kwargs = {"n_classes": 450}

    def test_list_all_pages_until_short_page(self):
        c = self.client()
        c.login("d", "u", "pw")
        classes = c.classes()
        self.assertEqual(len(classes), 450)
        self.assertEqual([json.loads(r["body"]) for r in self.mock.posts("class.list")],
                         [{"from": 0, "count": 200}, {"from": 200, "count": 200}, {"from": 400, "count": 200}])


class ExportTests(ServerTestCase):
    def test_export_waits_and_returns_bytes_untouched(self):
        c = self.client()
        c.login("d", "u", "pw")
        messages = []
        data = c.export("attendance", "csv", poll_seconds=0, on_status=messages.append)
        self.assertEqual(data, EXPORT_BYTES)
        self.assertEqual(messages, ["Export started", "Export finished"])
        polls = self.mock.posts("bgjob.getstatus")
        self.assertEqual(len(polls), 2)
        golden = dict((a, b) for a, _, b in GOLDEN)
        self.assertEqual(self.mock.posts("export")[0]["body"], golden["export"])
        self.assertTrue(all(p["body"] == golden["bgjob.getstatus"] for p in polls))

    def test_refused_format(self):
        c = self.client()
        c.login("d", "u", "pw")
        with self.assertRaisesRegex(AccuClassError, "Unable to execute action"):
            c.export("attendance", "XLSX", poll_seconds=0)

    def test_download_failure_lists_attempts(self):
        self.mock.accept_formats = ("HTML",)  # job "succeeds" but no .html file exists
        c = self.client()
        c.login("d", "u", "pw")
        with self.assertRaisesRegex(AccuClassError, "(?s)could not be downloaded.*JobResults/.*\\.html"):
            c.export("attendance", "HTML", poll_seconds=0)


class CliTests(ServerTestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        env = {"ACCUCLASS_DOMAIN": "d", "ACCUCLASS_USER": "u", "ACCUCLASS_PASSWORD": "pw"}
        with mock.patch.dict(os.environ, env), mock.patch("time.sleep"), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--base-url", self.mock.url, *argv])
        return code, out.getvalue(), err.getvalue()

    def test_export_saves_exact_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "attendance.csv")
            code, out, err = self.run_cli("export", "--type", "attendance", "--out", path)
            self.assertEqual(code, 0, err)
            with open(path, "rb") as f:
                self.assertEqual(f.read(), EXPORT_BYTES)
        self.assertIn(f"accuclass-client {__version__}", err)

    def test_refused_format_saves_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "attendance.xlsx")
            code, out, err = self.run_cli("export", "--format", "xlsx", "--out", path)
            self.assertEqual(code, 1)
            self.assertIn("refused the format 'XLSX'", err)
            self.assertFalse(os.path.exists(path))

    def test_flags_override_env(self):
        code, out, err = self.run_cli("--domain", "flagdomain", "--user", "flag@x", "raw", "my.profile")
        self.assertEqual(code, 0, err)
        login = json.loads(self.mock.posts("login")[0]["body"])
        self.assertEqual((login["domain"], login["username"]), ("flagdomain", "flag@x"))

    def test_list_classes_to_csv(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "classes.csv")
            code, out, err = self.run_cli("list", "classes", "--out", path)
            self.assertEqual(code, 0, err)
            with open(path, encoding="utf-8-sig") as f:
                lines = f.read().splitlines()
        self.assertEqual(lines[0], "Id,Name")
        self.assertEqual(len(lines), 11)

    def test_raw_parses_ints(self):
        code, out, err = self.run_cli("raw", "export", "exporttype=5", "exportformat=CSV")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["JobId"], JOB)


class RemovedCommandTests(unittest.TestCase):
    def test_unverified_commands_are_not_offered(self):
        parser = cli.build_parser()
        for argv in (["summary", "--out", "x.csv"], ["list", "users", "--out", "x.csv"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parser.parse_args(argv)


class FlattenTests(unittest.TestCase):
    def test_flatten(self):
        self.assertEqual(cli.flatten({"a": 1, "b": {"c": 2, "d": {"e": 3}}, "f": [1, 2]}),
                         {"a": 1, "b.c": 2, "b.d.e": 3, "f": "[1, 2]"})


if __name__ == "__main__":
    unittest.main()
