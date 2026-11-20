"""Don't carry credentials across redirects to another host.

urllib copies every header (Authorization included) to the redirect target. A Kaggle download answers with a redirect to a
signed Google Cloud Storage URL: forwarding the Kaggle credentials there leaks them to another host, and GCS rejects a signed
URL that also carries an Authorization header (HTTP 400), so the download fails. Same-host redirects keep their headers.
"""
from __future__ import annotations

import urllib.parse
import urllib.request

_SENSITIVE = ("authorization", "cookie", "proxy-authorization")


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc.lower() != urllib.parse.urlsplit(req.full_url).netloc.lower():
            for name in list(new.headers):
                if name.lower() in _SENSITIVE:
                    del new.headers[name]
            for name in list(new.unredirected_hdrs):
                if name.lower() in _SENSITIVE:
                    del new.unredirected_hdrs[name]
        return new


_installed = False


def install() -> None:
    global _installed
    if not _installed:
        urllib.request.install_opener(urllib.request.build_opener(SafeRedirectHandler))
        _installed = True
