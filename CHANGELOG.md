# Changelog

## 0.6.0

First version shared on GitHub.

- **Only features confirmed on a live server are included:** `probe`, `export`, `list classes|semesters` and `raw`. In Python, that's `call`, `login`, `logout`, `list_all`, `classes`, `semesters` and `export`.
- **Removed:** the `summary` command and `attendance_summary()`. Current servers answer `attendancelog.listsummary` with "not registered in the service".
- **Removed until verified:** `list users|departments|classrooms`, and the `users`, `class_enrollment`, `student_enrollment`, `class_attendance`, `student_attendance` and `session_attendance` helpers, plus the `IMPORT_TYPES` and `SWIPE_TYPES` constants. These actions can still be called with `raw` or `call()`.
- **The default User-Agent is a desktop browser's again**, as in 0.2.0 to 0.3.0, because Cloudflare blocks Python's built-in one. Change it with `ACCUCLASS_USER_AGENT`.
- **README:** explains the `python -m accuclass_client` fallback for when the `accuclass` command isn't on PATH.

## 0.5.0 (test build, not published)

First packaged build, shared privately for testing.

- New `accuclass` command and importable `accuclass_client` module, installed with `pip install accuclass-client`.
- The default User-Agent is now `accuclass-client/<version> (Python)`. Change it with `ACCUCLASS_USER_AGENT` or `AccuClass(user_agent=...)`.
- New `--domain` and `--user` options. Environment variables and prompts still work as before.
- Settings are now constructor options (`base_url`, `timeout`, `verbose`, `user_agent`, `content_type`) rather than module-level globals.
- Automated, offline test suite, including a byte-for-byte comparison with requests from Engineerica's .NET client.

## Before 0.5.0 (unpublished single-file script)

- **0.3.0**: exports saved exactly as the server produces them, with no conversion or renaming. `--format` accepts `XLSX`. Version shown on every run.
- **0.2.0**: clearer handling of Cloudflare `HTTP 403 / error code: 1010` responses.
- **0.1.0**: first version, reproducing the protocol of Engineerica's .NET client in pure Python.

Version 0.4.0 was a private, site-specific build and was never published.
