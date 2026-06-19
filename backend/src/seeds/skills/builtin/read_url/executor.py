"""Read URL executor — fetches a web page and extracts visible text."""
from html.parser import HTMLParser
from src.core.pubsub import broadcast as _broadcast


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self.parts.append(stripped)


async def execute(args: dict, chat_id: str, agent_id, agent_name) -> dict | None:
    import httpx

    url = args.get("url", "").strip()
    if not url:
        return {"error": "Missing required field: url"}

    await _broadcast(chat_id, {
        "type": "activity_status", "status": "running",
        "tool": "read_url", "label": f"Fetching {url[:80]}…",
    })

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            resp = await client.get(
                url, headers={"User-Agent": "Mozilla/5.0 (compatible; AgenticChats/1.0)"}
            )
        ct = resp.headers.get("content-type", "")
        if "html" in ct:
            parser = _TextExtractor()
            parser.feed(resp.text)
            text = "\n".join(parser.parts)
        else:
            text = resp.text
        max_chars = 12_000
        result: dict = {"url": url, "status_code": resp.status_code, "content": text[:max_chars]}
        if len(text) > max_chars:
            result["truncated"] = True
        return {"data": result}
    except Exception as exc:
        return {"error": str(exc)}
