import re
from urllib.parse import urlparse, parse_qs, urlunparse

def canonicalize_url(url: str) -> str:
    """
    Normalize URLs so identical content maps to 1 canonical URL.
    This prevents duplicate events, duplicate embeddings, and DB clutter.
    """

    if not url:
        return None

    # 1. Lowercase scheme + host
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # 2. Remove tracking params (UTM, fbclid, etc.)
    query = parse_qs(parsed.query)
    query = {
        k: v for k, v in query.items()
        if not k.startswith("utm_") and k not in ("fbclid", "gclid", "mc_cid", "mc_eid")
    }

    # 3. Sort params for stability
    query_string = "&".join(
        f"{k}={v[0]}" for k, v in sorted(query.items())
    )

    # 4. Normalize path (remove trailing slashes)
    path = re.sub(r"/+$", "", parsed.path)

    # 5. Rebuild URL
    canonical = urlunparse((
        scheme,
        netloc,
        path,
        parsed.params,
        query_string,
        parsed.fragment
    ))

    return canonical

