"""
CapturedResponse
================
Data model representing a captured HTTP response from a browser session,
with methods to serialize/deserialize from JSON and convert to authenticated
requests.Session objects.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import cast

import requests
from playwright._impl._api_structures import Cookie


@dataclass
class CapturedResponse:
    url: str
    method: str
    headers: dict[str, str]
    body: dict | list | str | None
    request_headers: dict[str, str]
    request_post_data: str | None = None
    cookies: list[Cookie] = field(default_factory=list)

    def to_json_file(self, filename: str = "captured_response.json") -> None:
        """Write this captured response to a JSON file."""
        with open(filename, "w", encoding="utf-8") as file:
            json.dump(asdict(self), file, indent=2)

    def to_session(self) -> requests.Session:
        """
        Build an authenticated ``requests.Session`` from this captured response.

        Applies request headers (dropping HTTP/2 pseudo-headers prefixed with ``:``
        and the raw ``cookie`` header) and cookies from this captured response.

        The ``cookie`` header is excluded because it contains stale cookie values
        from the original request. Fresh cookies (including Set-Cookie updates)
        are applied via ``session.cookies`` instead.
        """
        if not isinstance(self.request_headers, dict):
            raise ValueError("request_headers must be a dictionary")
        if not isinstance(self.cookies, list):
            raise ValueError("cookies must be a list")

        normalized_headers: dict[str, str] = {}
        for key, value in self.request_headers.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("request_headers keys and values must be strings")
            if not key.startswith(":") and key.lower() != "cookie":
                normalized_headers[key] = value

        session = requests.Session()
        session.headers.update(normalized_headers)
        for cookie in self.cookies:
            if not isinstance(cookie, dict):
                raise ValueError("Each cookie must be an object")
            c = cast(dict[str, str], cookie)
            name = c.get("name")
            value = c.get("value")
            if not isinstance(name, str) or not name:
                raise ValueError("Each cookie must include a non-empty string 'name'")
            if not isinstance(value, str):
                raise ValueError("Each cookie must include a string 'value'")
            domain = c.get("domain")
            path = c.get("path")
            if domain is not None and not isinstance(domain, str):
                raise ValueError("Cookie 'domain' must be a string when provided")
            if path is not None and not isinstance(path, str):
                raise ValueError("Cookie 'path' must be a string when provided")
            session.cookies.set(name, value, domain=domain, path=path)
        return session

    @staticmethod
    def from_json_file(filename: str = "captured_response.json") -> "CapturedResponse":
        """Read a JSON file and convert it into a ``CapturedResponse``."""
        if not filename.strip():
            raise ValueError("filename must be a non-empty string")

        path = Path(filename)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {filename}")
        if not path.is_file():
            raise ValueError(f"Path is not a file: {filename}")

        try:
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in file: {filename}") from exc

        if not isinstance(data, dict):
            raise ValueError("CapturedResponse JSON must be an object")

        required_fields = {
            "url",
            "method",
            "headers",
            "body",
            "request_headers",
            "request_post_data",
            "cookies",
        }
        missing_fields = required_fields - set(data)
        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ValueError(f"Missing required fields: {missing}")

        if not isinstance(data["url"], str) or not data["url"]:
            raise ValueError("'url' must be a non-empty string")
        if not isinstance(data["method"], str) or not data["method"]:
            raise ValueError("'method' must be a non-empty string")
        if not isinstance(data["headers"], dict):
            raise ValueError("'headers' must be an object")
        if not isinstance(data["request_headers"], dict):
            raise ValueError("'request_headers' must be an object")
        if data["request_post_data"] is not None and not isinstance(
            data["request_post_data"], str
        ):
            raise ValueError("'request_post_data' must be a string or null")
        if not isinstance(data["cookies"], list):
            raise ValueError("'cookies' must be an array")
        if data["body"] is not None and not isinstance(data["body"], (dict, list)):
            raise ValueError("'body' must be an object, array, or null")

        normalized_cookies: list[Cookie] = []
        for cookie in data["cookies"]:
            if not isinstance(cookie, dict):
                raise ValueError("Each cookie must be an object")
            if not isinstance(cookie.get("name"), str) or not isinstance(
                cookie.get("value"), str
            ):
                raise ValueError("Each cookie must include string 'name' and 'value'")
            normalized_cookies.append(cast(Cookie, cookie))

        return CapturedResponse(
            url=data["url"],
            method=data["method"],
            headers=cast(dict[str, str], data["headers"]),
            body=cast(dict | list | None, data["body"]),
            request_headers=cast(dict[str, str], data["request_headers"]),
            request_post_data=cast(str | None, data["request_post_data"]),
            cookies=normalized_cookies,
        )
