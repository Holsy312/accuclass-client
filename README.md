# accuclass-client

An unofficial Python client and command-line tool for the [AccuClass](https://www.engineerica.com/accuclass/) attendance system. It uses AccuClass's legacy "Service" API, so you can pull attendance exports and records without .NET, Visual Studio or Engineerica's Windows tools. It uses only Python's standard library, so it has no dependencies.

> **Not affiliated with Engineerica.** AccuClass is a product of Engineerica Systems, Inc. This project isn't affiliated with or endorsed by them. Only use it with an AccuClass account you're authorised to use, and within your institution's agreement with Engineerica.

## Install

```
pip install accuclass-client
```

Requires Python 3.9 or later. This installs the `accuclass` command and the `accuclass_client` Python module.

If Windows says `accuclass` isn't recognised, Python's Scripts folder isn't on your PATH. That's common with the Microsoft Store version of Python. Use `python -m accuclass_client` instead, e.g. `python -m accuclass_client probe`.

## Quick start

```
accuclass probe
accuclass export --type attendance --format CSV --out attendance.csv
```

`probe` logs in and shows a sample of your data, which confirms the connection works. You'll be asked for anything that isn't already set:

| Setting | Command-line flag | Environment variable |
|---|---|---|
| AccuClass domain (your account name) | `--domain` | `ACCUCLASS_DOMAIN` |
| Login email | `--user` | `ACCUCLASS_USER` |
| Password | (always prompted, or…) | `ACCUCLASS_PASSWORD` |
| Site address (default `https://www.accuclass.net/`) | `--base-url` | `ACCUCLASS_URL` |
| User-Agent header (default: a desktop browser's) | — | `ACCUCLASS_USER_AGENT` |

Exports need an account with export rights, usually an administrator.

**About the User-Agent:** accuclass.net is behind Cloudflare, which blocks Python's built-in User-Agent (`Python-urllib/3.x`) with `HTTP 403 … error code: 1010`. The client therefore sends a desktop browser's User-Agent by default, since that's the value proven in live use. Set `ACCUCLASS_USER_AGENT` to send something else.

## Commands

| Command | What it does |
|---|---|
| `accuclass probe` | Log in and print a sample semester and class. |
| `accuclass export --type T --format F --out FILE` | Run one of AccuClass's own exports and save the file **exactly as the server produces it**. Types: `attendance`, `swipes`, `students`, `instructors`, `enrollment`, `classes`. Formats: `CSV`, `HTML`, `XLSX`. |
| `accuclass list classes\|semesters --out FILE` | Save every class or semester as a CSV. |
| `accuclass raw ACTION key=value …` | Call any API action and print the JSON reply, e.g. `accuclass raw semester.list from=0 count=5`. |

The commands and helpers are limited to what's been confirmed on a live server. Some actions in Engineerica's original .NET client no longer exist on current servers: `attendancelog.listsummary`, for example, now returns "not registered in the service". Anything else can still be tried with `raw` or `AccuClass.call()`.

Add `-v` to print each request as it's sent (passwords are masked). `accuclass --version` shows the installed version.

## Python

```python
from accuclass_client import AccuClass

with AccuClass() as ac:                                   # logs out automatically
    ac.login("yourdomain", "you@example.edu", "password")
    classes = ac.classes()                                # every class, paged automatically
    data = ac.export("attendance", "CSV")                 # bytes, exactly as the server produced them
    page = ac.call("class.list", **{"from": 0, "count": 50})   # any action, called directly
```

`ac.call(action, **params)` reaches any action of the API. Parameters set to `None` are left out; pass `accuclass_client.JSON_NULL` to send an explicit `null`. Failures raise `AccuClassError`.

## How it works

Every call is a single HTTP request:

```
POST https://www.accuclass.net/Service/?action=<action>&token=<session token>
body: the parameters as a compact JSON object
```

`login` returns the session token. Exports run as background jobs: the client polls `bgjob.getstatus` and then downloads the finished file from `JobResults/`.

This mirrors Engineerica's own .NET client, `EngineericaApi.dll`, whose source they published in [engineerica/engineerica-dev](https://github.com/engineerica/engineerica-dev). The test suite checks that our requests are byte-for-byte identical to those the .NET client sends.

## Status

This is an early release (alpha). So far it has been used against one institution's live AccuClass server for logging in, the attendance export, and listing classes and semesters. The automated tests run offline against a mock server. Reports of what works on your server are very welcome. Please open an issue.

## Troubleshooting

| Message | Meaning |
|---|---|
| `HTTP 403 … error code: 1010` | The site's Cloudflare protection blocked the request. Ask your AccuClass administrator or Engineerica support whether API access needs to be allowed for your network. |
| `Server redirected (301) to …` | Your institution uses a different AccuClass address. Pass it with `--base-url`. |
| `'login' failed: …` | Wrong domain, email or password, or the account isn't allowed to use the API. |
| `'export' failed: Unable to execute action.` | The server refused that export type or format. Try `--format CSV`. |
| `Action '…' is not registered in the service.` | That action doesn't exist on your server, probably because it was retired after the original .NET client was written. |
| `HTTP 404` / `did not return JSON` | The address is wrong, or this legacy API isn't available for your account. Engineerica's newer REST APIs are documented at [developers.engineerica.com](https://developers.engineerica.com/). |
| Proxy problems | The client uses your system's proxy settings, the same as your browser. |

## Development

```
python -m unittest discover -s tests -v
```

The tests run offline against a local mock server. See [CHANGELOG.md](CHANGELOG.md) for version history.

## Licence

[MIT](LICENSE) © 2026 Oliver Holdsworth
