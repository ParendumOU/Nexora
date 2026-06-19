"""Repository file-tree fetching and caching helpers."""
import httpx
import json
import logging
from src.core.redis import get_redis

logger = logging.getLogger(__name__)


def _parse_repo_path(repo_url: str) -> str:
    url = repo_url.rstrip("/")
    for prefix in ["https://github.com/", "https://gitlab.com/", "http://github.com/", "http://gitlab.com/"]:
        if url.startswith(prefix):
            url = url[len(prefix):]
            break
    return url.removesuffix(".git")


async def _fetch_repo_tree(
    repo_url: str,
    repo_type: str,
    token: str,
    branch: str,
    base_url: str | None = None,
) -> list[dict]:
    repo = _parse_repo_path(repo_url)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            if repo_type == "github":
                headers = {
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
                r = await client.get(
                    f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1",
                    headers=headers,
                )
                if r.status_code != 200:
                    logger.warning(f"GitHub tree fetch failed ({r.status_code}): {r.text[:200]}")
                    return []
                return [
                    {"path": item["path"], "type": "dir" if item["type"] == "tree" else "file"}
                    for item in r.json().get("tree", [])
                ]
            else:
                _base = (base_url or "https://gitlab.com").rstrip("/")
                encoded = repo.replace("/", "%2F")
                headers = {"PRIVATE-TOKEN": token}
                items: list[dict] = []
                page = 1
                while len(items) < 500:
                    r = await client.get(
                        f"{_base}/api/v4/projects/{encoded}/repository/tree"
                        f"?recursive=true&ref={branch}&per_page=100&page={page}",
                        headers=headers,
                    )
                    if r.status_code != 200:
                        logger.warning(f"GitLab tree fetch failed ({r.status_code}): {r.text[:200]}")
                        break
                    batch = r.json()
                    if not batch:
                        break
                    items.extend(batch)
                    if len(batch) < 100:
                        break
                    page += 1
                return [
                    {"path": item["path"], "type": "dir" if item["type"] == "tree" else "file"}
                    for item in items
                ]
    except Exception as exc:
        logger.warning(f"Repo tree fetch error: {exc}")
        return []


async def _get_cached_repo_tree(
    project_id: str,
    repo_url: str,
    repo_type: str,
    token: str,
    branch: str,
    base_url: str | None = None,
) -> list[dict]:
    redis = get_redis()
    cache_key = f"repo_tree:{project_id}:{branch}"
    try:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    tree = await _fetch_repo_tree(repo_url, repo_type, token, branch, base_url)
    if tree:
        try:
            await redis.setex(cache_key, 300, json.dumps(tree))
        except Exception:
            pass
    return tree
