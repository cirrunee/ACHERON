"""Bounded HTTP client. Credentials are never put in URLs or diagnostics."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("The AI endpoint redirected the request; refusing to forward credentials or evidence.")


def json_request(url, payload=None, key="", timeout=180):
    parsed = urlsplit(url)
    local = parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port is not None
    cloud = parsed.scheme == "https" and parsed.netloc == "api.openai.com"
    if not (local or cloud) or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Use the built-in local engine or the official OpenAI endpoint.")
    headers = {"Content-Type": "application/json", "User-Agent": "ACHERON-CHARON/0.2"}
    if key:
        headers["Authorization"] = "Bearer " + key
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    opener = build_opener(NoRedirect(), *([ProxyHandler({})] if local else []))
    try:
        with opener.open(Request(url, data=body, headers=headers), timeout=timeout) as response:
            data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ValueError("AI response exceeded the 2 MB limit.")
            return json.loads(data)
    except HTTPError as exc:
        descriptions = {401: "API key was rejected", 403: "This account cannot access that model", 404: "Model or endpoint was not found",
                        429: "Provider rate limit or account quota reached", 503: "The model is loading or unavailable"}
        raise ValueError(descriptions.get(exc.code, f"AI provider returned HTTP {exc.code}")) from None
    except (URLError, TimeoutError) as exc:
        raise ValueError("Could not reach the model. Check the connection or start the local engine, then retry.") from None
