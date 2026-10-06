"""
Client for the AccuClass legacy "Service" API.

Every call is one HTTP request:

    POST {base_url}Service/?action=<action>[&token=<login token>]
    body:     the call's parameters as a compact JSON object (no Content-Type header)
    response: JSON, with "success": true/false

This mirrors Engineerica's own .NET client (EngineericaApi.dll), whose source Engineerica
published in https://github.com/engineerica/engineerica-dev (``deprecated/api``). Request
bodies are byte-for-byte identical to the ones that client sends.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Callable, Dict, Iterator, List, Optional

DEFAULT_BASE_URL = "https://www.accuclass.net/"

# accuclass.net sits behind Cloudflare, which rejects Python's built-in User-Agent
# ("Python-urllib/3.x") with HTTP 403 / "error code: 1010". A desktop-browser User-Agent
# is the value proven to work in live use. Override with ACCUCLASS_USER_AGENT or
# AccuClass(user_agent=...).
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)

# Numeric values of the .NET client's ExportType enum (Json.NET serialises enums as integers).
EXPORT_TYPES = {
    "students": 0,
    "instructors": 1,
    "enrollment": 2,
    "classes": 3,
    "swipes": 4,
    "attendance": 5,
}

#: Pass as a parameter value to send an explicit JSON ``null`` (plain ``None`` means "omit").
JSON_NULL = object()


class AccuClassError(RuntimeError):
    """Raised when the server answers ``success: false``, or the HTTP request fails."""


class _ContentTypeHandler(urllib.request.BaseHandler):
    """Runs after urllib's own processing and sets the Content-Type exactly as configured.

    urllib labels every POST body as a web form by default; the .NET client sends no
    Content-Type at all, so with ``content_type=None`` the header is removed.
    """

    handler_order = 900

    def __init__(self, content_type: Optional[str]):
        self.content_type = content_type

    def http_request(self, req):
        if req.data is not None:
            req.remove_header("Content-type")
            if self.content_type:
                req.add_unredirected_header("Content-type", self.content_type)
        return req

    https_request = http_request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Following a redirect would silently turn the POST into a GET and drop the body,
    # so surface it as an error that names the new location instead.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AccuClassError(
            f"Server redirected ({code}) to {newurl}. "
            f"Use that site's root as the base URL instead."
        )


def _to_json_value(value: Any) -> Any:
    """Serialise Python values the way Json.NET serialises the .NET client's types."""
    if value is JSON_NULL:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)  # lower-case "D" format, like Guid.ToString()
    if isinstance(value, dt.datetime):
        return value.replace(microsecond=0).isoformat()  # 2026-01-31T09:00:00
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day).isoformat()
    return value


class AccuClass:
    """AccuClass API client.

    Use :meth:`call` for any action, or the helper methods for common reads::

        with AccuClass() as ac:
            ac.login("yourdomain", "you@example.edu", "password")
            classes = ac.classes()
            data = ac.export("attendance", "CSV")

    Args:
        base_url: AccuClass site root. Defaults to ``ACCUCLASS_URL`` or https://www.accuclass.net/.
        timeout: seconds to wait for each HTTP request.
        verbose: print each request (password masked) to stderr.
        user_agent: User-Agent header. Defaults to ``ACCUCLASS_USER_AGENT`` or a
            desktop-browser value (see ``DEFAULT_USER_AGENT``).
        content_type: Content-Type for request bodies. ``None`` (default) sends none,
            matching Engineerica's .NET client.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: int = 60,
        verbose: bool = False,
        user_agent: Optional[str] = None,
        content_type: Optional[str] = None,
    ):
        base_url = base_url or os.environ.get("ACCUCLASS_URL") or DEFAULT_BASE_URL
        if not base_url.endswith("/"):
            base_url += "/"
        self.base_url = base_url
        self.timeout = timeout
        self.verbose = verbose
        self.user_agent = user_agent or os.environ.get("ACCUCLASS_USER_AGENT") or DEFAULT_USER_AGENT
        self.token: Optional[str] = None
        self.profile: Dict[str, Any] = {}
        # build_opener keeps the default ProxyHandler, so system proxy settings apply.
        self._opener = urllib.request.build_opener(_NoRedirect(), _ContentTypeHandler(content_type))
        self._opener.addheaders = [("User-Agent", self.user_agent), ("Accept", "*/*")]

    # ------------------------------------------------------------------ core protocol

    def call(self, action: str, _auth: bool = True, **params: Any) -> Dict[str, Any]:
        """Execute one API action and return the decoded JSON response.

        Parameters set to ``None`` are left out of the request; use :data:`JSON_NULL`
        to send an explicit ``null``. Actions other than ``login``, ``doc`` and
        ``listtimezones`` need :meth:`login` first.
        """
        query = {"action": action}
        if _auth:
            if not self.token:
                raise AccuClassError("You must be logged in to execute this action.")
            query["token"] = self.token
        url = self.base_url + "Service/?" + urllib.parse.urlencode(query)

        body = {k: _to_json_value(v) for k, v in params.items() if v is not None}
        data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")

        if self.verbose:
            shown = dict(body)
            if "password" in shown:
                shown["password"] = "***"
            print(f"--> POST Service/?action={action}  {json.dumps(shown)}", file=sys.stderr)

        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                text = resp.read().decode("utf-8-sig", errors="replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            hint = ""
            if e.code == 403 and ("1010" in detail or "1020" in detail or "cloudflare" in detail.lower()):
                hint = ("\nThe site's Cloudflare protection blocked the request. Ask your AccuClass "
                        "administrator or Engineerica support whether API access needs to be "
                        "allowed for your network.")
            raise AccuClassError(f"HTTP {e.code} calling '{action}': {detail}{hint}") from None
        except urllib.error.URLError as e:
            raise AccuClassError(f"Could not reach {self.base_url}: {e.reason}") from None

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            raise AccuClassError(
                f"'{action}' did not return JSON (is the base URL right?). First 300 chars:\n{text[:300]}"
            ) from None

        if isinstance(result, dict) and result.get("success") is False:
            msg = result.get("message") or result.get("error") or result.get("Message") or text[:500]
            raise AccuClassError(f"'{action}' failed: {msg}")
        return result

    def login(self, domain: str, username: str, password: str) -> Dict[str, Any]:
        """Log in and keep the session token for later calls. Returns the login response."""
        res = self.call("login", _auth=False, domain=domain, username=username,
                        password=password, method="token")
        token = res.get("token")
        if not token:
            raise AccuClassError(f"Login response had no token: {json.dumps(res)[:300]}")
        self.token = token
        self.profile = res
        return res

    def logout(self) -> None:
        """End the session (also done automatically when used as a context manager)."""
        if self.token:
            try:
                self.call("logout")
            finally:
                self.token = None

    def __enter__(self) -> "AccuClass":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.logout()

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def results(response: Dict[str, Any]) -> List[Any]:
        """Return the list inside a list-style response (usually its ``results`` key)."""
        for key in ("results", "Results", "items", "data"):
            if isinstance(response.get(key), list):
                return response[key]
        return []

    def list_all(self, action: str, page_size: int = 200, max_pages: int = 1000,
                 **params: Any) -> Iterator[Dict[str, Any]]:
        """Yield every record from an action that pages with ``from``/``count``."""
        start = 0
        for _ in range(max_pages):
            page = self.results(self.call(action, **{"from": start, "count": page_size}, **params))
            yield from page
            if len(page) < page_size:
                return
            start += page_size

    # Read-only wrappers, limited to actions confirmed on a live server --------
    # (anything else is still reachable through call()).

    def semesters(self) -> List[Dict[str, Any]]:
        """Every semester (``semester.list``)."""
        return list(self.list_all("semester.list"))

    def classes(self) -> List[Dict[str, Any]]:
        """Every class (``class.list``)."""
        return list(self.list_all("class.list"))

    # Bulk export ----------------------------------------------------------------

    def export(self, export_type: str = "attendance", export_format: str = "CSV",
               poll_seconds: float = 2.0, timeout_seconds: float = 600,
               on_status: Optional[Callable[[str], None]] = None) -> bytes:
        """Run a server-side export, wait for it, and return the file exactly as produced.

        Args:
            export_type: students | instructors | enrollment | classes | swipes | attendance
            export_format: sent to the server as-is, e.g. CSV, HTML, XLSX. Nothing is
                converted locally.
            on_status: optional callback receiving each new job status message.
        """
        etype = EXPORT_TYPES[export_type.lower()]
        fmt = export_format.upper()
        res = self.call("export", exporttype=etype, exportformat=fmt)
        job_id = res.get("JobId") or res.get("jobId") or res.get("jobid")
        if not job_id:
            raise AccuClassError(f"Export did not return a JobId: {json.dumps(res)[:300]}")

        seen = set()
        deadline = time.time() + timeout_seconds
        status: Dict[str, Any] = {}
        while time.time() < deadline:
            time.sleep(poll_seconds)
            status = self.call("bgjob.getstatus", jobid=job_id, jobtype=JSON_NULL)
            jobs = self.results(status)
            job = jobs[0] if jobs else {}
            for s in job.get("Statuses") or []:
                m = s.get("Message") if isinstance(s, dict) else str(s)
                if m and m not in seen:
                    seen.add(m)
                    if on_status:
                        on_status(m)
            if job.get("Succeed") is True:
                break
        else:
            raise AccuClassError(f"Export job {job_id} did not finish within {timeout_seconds}s")

        return self._download_job_result(job_id, fmt, status)

    def _download_job_result(self, job_id: str, fmt: str, status: Dict[str, Any]) -> bytes:
        # Prefer any link the server gave; otherwise use {base}JobResults/{jobId}.{ext},
        # the location used in Engineerica's own example code.
        candidates: List[str] = []

        def find_links(o: Any) -> None:
            if isinstance(o, dict):
                for v in o.values():
                    find_links(v)
            elif isinstance(o, list):
                for v in o:
                    find_links(v)
            elif isinstance(o, str) and "JobResults" in o:
                candidates.append(urllib.parse.urljoin(self.base_url, o))

        find_links(status)
        exts = {"CSV": ["csv", "zip"], "HTML": ["html", "htm"], "XLS": ["xls", "xlsx"],
                "XLSX": ["xlsx", "xls"]}.get(fmt, [fmt.lower()])
        candidates += [f"{self.base_url}JobResults/{job_id}.{e}" for e in exts]

        errors = []
        for url in candidates:
            try:
                with self._opener.open(urllib.request.Request(url), timeout=self.timeout) as r:
                    return r.read()
            except (urllib.error.HTTPError, urllib.error.URLError, AccuClassError) as e:
                errors.append(f"{url}: {e}")
        raise AccuClassError(
            "Export finished but the file could not be downloaded. Tried:\n  "
            + "\n  ".join(errors)
            + f"\nLast job status: {json.dumps(status)[:800]}"
        )
