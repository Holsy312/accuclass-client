"""The ``accuclass`` command-line tool."""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import sys
from typing import Any, Dict, List, Optional

from ._version import __version__
from .client import DEFAULT_BASE_URL, EXPORT_TYPES, AccuClass, AccuClassError


# ------------------------------------------------------------------------ CSV helpers

def flatten(obj: Any, prefix: str = "") -> Dict[str, Any]:
    """Flatten nested JSON into one level: {"Class": {"Name": "x"}} -> {"Class.Name": "x"}."""
    out: Dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(flatten(v, key))
            elif isinstance(v, list):
                out[key] = json.dumps(v, ensure_ascii=False)
            else:
                out[key] = v
    else:
        out[prefix or "value"] = obj
    return out


def write_csv(rows: List[Dict[str, Any]], path: str) -> int:
    """Write records to CSV (UTF-8 with BOM, so Excel detects the encoding). Returns row count."""
    flat = [flatten(r) for r in rows]
    columns: List[str] = []
    for r in flat:
        for k in r:
            if k not in columns:
                columns.append(k)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(flat)
    return len(flat)


# ------------------------------------------------------------------------ commands

def _connect(args: argparse.Namespace) -> AccuClass:
    domain = args.domain or os.environ.get("ACCUCLASS_DOMAIN") or input("AccuClass domain: ").strip()
    user = args.user or os.environ.get("ACCUCLASS_USER") or input("Email: ").strip()
    pwd = os.environ.get("ACCUCLASS_PASSWORD") or getpass.getpass("Password (hidden): ")
    client = AccuClass(args.base_url, verbose=args.verbose)
    res = client.login(domain, user, pwd)
    print(f"Logged in as {res.get('FullName') or user}", file=sys.stderr)
    return client


def cmd_probe(args: argparse.Namespace) -> None:
    c = _connect(args)
    with c:
        shown = {k: v for k, v in c.profile.items() if k.lower() != "token"}
        print("Login response (token hidden):")
        print(json.dumps(shown, indent=2)[:1500])
        for action in ("semester.list", "class.list"):
            try:
                first = c.results(c.call(action, **{"from": 0, "count": 5}))
                print(f"\n{action}: first {len(first)} record(s)")
                if first:
                    print(json.dumps(first[0], indent=2)[:1200])
            except AccuClassError as e:
                print(f"\n{action}: {e}")
    print("\nConnection works.")


def cmd_export(args: argparse.Namespace) -> None:
    """Save exactly the file AccuClass produces: no conversion, no renaming."""
    c = _connect(args)
    with c:
        try:
            data = c.export(args.type, args.format,
                            on_status=lambda m: print("  " + m, file=sys.stderr))
        except AccuClassError as e:
            if args.format != "CSV" and "'export' failed" in str(e):
                raise AccuClassError(
                    f"{e}\nThe server refused the format '{args.format}' through the API. "
                    f"Try --format CSV."
                ) from None
            raise
    with open(args.out, "wb") as f:
        f.write(data)
    print(f"Saved {len(data):,} bytes to {args.out}")


# Only list types confirmed on a live server. Others can be reached with `raw`.
LIST_ACTIONS = {"classes": "class.list", "semesters": "semester.list"}


def cmd_list(args: argparse.Namespace) -> None:
    c = _connect(args)
    with c:
        rows = list(c.list_all(LIST_ACTIONS[args.what]))
    n = write_csv(rows, args.out)
    print(f"Saved {n} {args.what} to {args.out}")


def cmd_raw(args: argparse.Namespace) -> None:
    """Call any action and print the JSON, e.g.  raw attendancelog.listclass classid=<guid>"""
    params: Dict[str, Any] = {}
    for kv in args.params:
        k, _, v = kv.partition("=")
        params[k] = int(v) if v.lstrip("-").isdigit() else v
    c = _connect(args)
    with c:
        res = c.call(args.action, _auth=args.action not in ("login", "doc", "listtimezones"), **params)
    print(json.dumps(res, indent=2, ensure_ascii=False))


# ------------------------------------------------------------------------ entry point

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="accuclass",
        description="Unofficial command-line client for the AccuClass attendance API.",
        epilog="Credentials can also come from ACCUCLASS_DOMAIN, ACCUCLASS_USER and "
               "ACCUCLASS_PASSWORD; anything missing is prompted for.",
    )
    p.add_argument("--version", action="version", version=f"accuclass-client {__version__}")
    p.add_argument("--base-url", help=f"AccuClass site root (default: ACCUCLASS_URL or {DEFAULT_BASE_URL})")
    p.add_argument("--domain", help="AccuClass account domain (default: ACCUCLASS_DOMAIN)")
    p.add_argument("--user", help="login email (default: ACCUCLASS_USER)")
    p.add_argument("-v", "--verbose", action="store_true", help="print each request (password masked)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="log in and show a sample of data (connection test)").set_defaults(func=cmd_probe)

    e = sub.add_parser("export", help="server-side bulk export, saved exactly as produced")
    e.add_argument("--type", default="attendance", choices=list(EXPORT_TYPES))
    e.add_argument("--format", default="CSV", type=str.upper, choices=["CSV", "HTML", "XLSX", "XLS"],
                   help="file format requested from AccuClass (default CSV)")
    e.add_argument("--out", required=True, help="file to save")
    e.set_defaults(func=cmd_export)

    li = sub.add_parser("list", help="save a list of records to CSV")
    li.add_argument("what", choices=list(LIST_ACTIONS))
    li.add_argument("--out", required=True, help="CSV file to save")
    li.set_defaults(func=cmd_list)

    r = sub.add_parser("raw", help="call any API action and print the JSON response")
    r.add_argument("action", help="e.g. attendancelog.listclass")
    r.add_argument("params", nargs="*", help="key=value pairs")
    r.set_defaults(func=cmd_raw)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"accuclass-client {__version__}", file=sys.stderr)  # so pasted output shows the version
    try:
        args.func(args)
    except AccuClassError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
