"""Incremental SSE/NDJSON transport shared by provider adapters."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def stream_json(url, payload, headers=None, *, ndjson=False):
    request = Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})}, method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            data = []
            for raw_line in response:
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if ndjson:
                    if line.strip():
                        item = json.loads(line)
                        if item.get("error"):
                            raise RuntimeError(str(item["error"]))
                        yield item
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif not line and data:
                    value = "\n".join(data)
                    data = []
                    if value == "[DONE]":
                        return
                    item = json.loads(value)
                    if item.get("error"):
                        raise RuntimeError(str(item["error"]))
                    yield item
            if data and "\n".join(data) != "[DONE]":
                item = json.loads("\n".join(data))
                if item.get("error"):
                    raise RuntimeError(str(item["error"]))
                yield item
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Model stream returned HTTP {exc.code}: {detail[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not connect to model stream: {exc.reason}") from exc
