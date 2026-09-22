"""Network: FEC bulk files, OpenFEC API, congress-legislators. Retries with backoff; a call budget per run."""
from __future__ import annotations

import csv
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

UA = {"User-Agent": "follow-the-money-tracker (github.com/sabbadoo32)"}


class OutOfBudget(Exception):
    pass


def fetch(url, tries=5, timeout=120):
    delay = 5
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or i == tries - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if i == tries - 1:
                raise
        time.sleep(delay)
        delay = min(delay * 2, 120)


def bulk_ie(url):
    body, headers = fetch(url)
    rows = list(csv.DictReader(io.StringIO(body.decode("latin-1"))))
    return rows, headers.get("Last-Modified")


def bulk_zip_lines(url):
    body, headers = fetch(url)
    z = zipfile.ZipFile(io.BytesIO(body))
    name = z.namelist()[0]
    return z.read(name).decode("latin-1").splitlines(), headers.get("Last-Modified")


def legislators(url):
    body, _ = fetch(url)
    return json.loads(body)


class OpenFEC:
    def __init__(self, base, key, max_calls, min_remaining):
        self.base, self.key = base, key
        self.max_calls, self.min_remaining = max_calls, min_remaining
        self.calls, self.remaining = 0, None

    def get(self, path, **params):
        if self.calls >= self.max_calls or (self.remaining is not None and self.remaining < self.min_remaining):
            raise OutOfBudget(f"{self.calls} calls used, {self.remaining} remaining")
        q = [("api_key", self.key)]
        for k, v in params.items():
            for x in (v if isinstance(v, (list, tuple)) else [v]):
                if x is not None:
                    q.append((k, x))
        url = f"{self.base}{path}?{urllib.parse.urlencode(q)}"
        body, headers = fetch(url)
        self.calls += 1
        rem = {k.lower(): v for k, v in headers.items()}.get("x-ratelimit-remaining")
        if rem is not None:
            self.remaining = int(rem)
        return json.loads(body)

    def pages(self, path, **params):
        """Page-number pagination (efile, schedule_f, election-dates)."""
        page = 1
        while True:
            d = self.get(path, page=page, per_page=100, **params)
            yield from d["results"]
            if page >= (d.get("pagination") or {}).get("pages", 1):
                return
            page += 1

    def keyset(self, path, **params):
        """Keyset pagination (processed schedule_e): follow pagination.last_indexes."""
        extra = {}
        while True:
            d = self.get(path, per_page=100, **params, **extra)
            res = d["results"]
            yield from res
            li = (d.get("pagination") or {}).get("last_indexes")
            if not res or not li:
                return
            extra = li


def api_key():
    return os.environ.get("FEC_API_KEY") or None
