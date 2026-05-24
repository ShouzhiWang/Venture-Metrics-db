from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - project installs bs4; regex fallback supports lightweight routing.
    BeautifulSoup = None

try:
    import trafilatura
except ImportError:  # pragma: no cover - project installs trafilatura; fallback keeps URL routing lightweight.
    trafilatura = None


ORG_TYPE_TERMS = {
    "accelerator": ("accelerator", "incubator", "venture studio", "孵化器", "加速器", "创业服务中心"),
    "association": ("association", "chamber", "alliance", "network", "coalition",
                    "协会", "公会", "商会", "联盟", "联会", "促进会", "联合会"),
    "vc_group": ("venture capital", " vc ", "investor", "fund",
                 "创投", "私募", "天使投资", "风投", "基金"),
    "government_agency": ("government", "ministry", "agency", ".gov", "authority",
                          "政府", "局", "委员会", "办公室"),
    "directory": ("directory", "members", "member directory", "ecosystem map", "startup database"),
    "university": ("university", "college", "research institute",
                   "大学", "学院", "研究院", "实验室", "研究中心"),
    "nonprofit": ("nonprofit", "non-profit", "foundation",
                  "基金会", "非营利", "非盈利", "慈善"),
    "industry_group": ("industry", "chamber of commerce", "trade",
                       "产业", "行业", "工业", "电子", "半导体", "新能源", "无人机"),
}

GEOGRAPHY_TERMS = (
    "Singapore", "新加坡",
    "Hong Kong", "香港",
    "Shenzhen", "深圳",
    "China", "中国", "中国内地",
    "Asia", "亚洲",
    "Malaysia", "马来西亚",
    "Indonesia", "印度尼西亚", "印尼",
    "Vietnam", "越南",
    "Thailand", "泰国",
    "India", "印度",
    "Japan", "日本",
    "Korea", "韩国",
    "United States", "美国",
    "United Kingdom", "英国",
    "Guangdong", "广东",
    "Beijing", "北京",
    "Shanghai", "上海",
    "Greater Bay Area", "大湾区", "粤港澳大湾区",
)

REPORT_TERMS = ("report", "white paper", "whitepaper", "methodology", "executive summary", "appendix")
NEWS_TERMS = ("/news/", "/press/", "/blog/", "article", "posted on", "published on")


@dataclass
class SourceRoute:
    source_route: str
    confidence_score: float
    reason: str


def classify_source_route(
    *,
    url: str | None,
    source_type: str | None = None,
    html: bytes | str | None = None,
    title: str | None = None,
) -> SourceRoute:
    lowered_url = (url or "").lower()
    if source_type == "pdf" or lowered_url.endswith(".pdf"):
        return SourceRoute("report_pdf", 0.95, "PDF source")
    if source_type in {"csv", "xlsx", "api"}:
        return SourceRoute("dataset", 0.9, f"{source_type} source")
    if any(term in lowered_url for term in ("login", "signup", "register", "checkout")):
        return SourceRoute("gated", 0.75, "gated URL pattern")

    text, html_title, meta_description, link_count = html_signals(html)
    combined = " ".join([lowered_url, (title or html_title or ""), meta_description or "", text[:3000]]).lower()
    if any(term in lowered_url for term in NEWS_TERMS) or re.search(r"/20\d{2}/\d{2}/", lowered_url):
        return SourceRoute("news_article", 0.7, "news/article URL pattern")
    if _is_directory(combined, link_count):
        return SourceRoute("organization_directory", 0.78, "directory/member listing signals")
    if source_type == "html" and _is_html_report(combined, len(text)):
        return SourceRoute("html_report", 0.72, "HTML report signals")
    if _is_organization_page(combined, lowered_url, link_count):
        return SourceRoute("ecosystem_organization", 0.76, "organization homepage signals")
    if source_type == "html":
        return SourceRoute("landing_page", 0.55, "generic HTML page")
    return SourceRoute("unknown", 0.3, "no strong route signals")


def extract_ecosystem_organization(html: bytes | str, source: dict) -> dict:
    text, title, meta_description, _link_count = html_signals(html)
    url = source.get("original_url")
    name = clean_title(title) or hostname_name(url) or "Unknown organization"
    description = meta_description or first_useful_paragraph(html) or compact(text, 600)
    combined = " ".join([name, description or "", text[:3000], url or ""])
    organization_type = infer_organization_type(combined)
    geography = infer_geography(combined)
    confidence = 0.62
    if title:
        confidence += 0.12
    if description:
        confidence += 0.08
    if organization_type:
        confidence += 0.08
    if geography:
        confidence += 0.05
    return {
        "name": name,
        "website_url": url,
        "description": description,
        "organization_type": organization_type,
        "geography": geography,
        "source_id": source.get("id"),
        "original_source_url": url,
        "confidence_score": min(confidence, 0.95),
        "review_status": "pending",
        "metadata": {
            "source_route": "ecosystem_organization",
            "html_title": title,
            "meta_description": meta_description,
        },
    }


def extract_directory_candidates(html: bytes | str, base_url: str | None) -> list[dict]:
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(_decode_html(html), "html.parser")
    candidates = []
    for anchor in soup.find_all("a", href=True):
        label = compact(anchor.get_text(" ", strip=True), 120)
        href = anchor["href"].strip()
        if not label or len(label) < 3 or len(label.split()) > 8:
            continue
        lowered = label.lower()
        if any(skip in lowered for skip in ("read more", "learn more", "contact", "privacy", "terms", "download")):
            continue
        nearby = compact(anchor.parent.get_text(" ", strip=True) if anchor.parent else "", 300)
        if not any(term in nearby.lower() for terms in ORG_TYPE_TERMS.values() for term in terms) and not href.startswith("http"):
            continue
        candidates.append({"name": label, "url": href, "context": nearby, "base_url": base_url, "confidence_score": 0.72})
    return candidates[:25]


def html_signals(html: bytes | str | None) -> tuple[str, str | None, str | None, int]:
    if html is None:
        return "", None, None, 0
    decoded = _decode_html(html)
    if BeautifulSoup is None:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", decoded, re.I | re.S)
        meta_match = re.search(
            r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']+)[\"']",
            decoded,
            re.I | re.S,
        )
        text = re.sub(r"<[^>]+>", " ", decoded)
        return compact(text), compact(title_match.group(1)) if title_match else None, compact(meta_match.group(1)) if meta_match else None, len(re.findall(r"<a\b", decoded, re.I))
    soup = BeautifulSoup(decoded, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    meta_description = meta.get("content", "").strip() if meta and meta.get("content") else None
    extracted = trafilatura.extract(decoded) if trafilatura else None
    text = extracted or soup.get_text(" ", strip=True)
    return compact(text), title, meta_description, len(soup.find_all("a"))


def first_useful_paragraph(html: bytes | str) -> str | None:
    if BeautifulSoup is None:
        for match in re.findall(r"<p[^>]*>(.*?)</p>", _decode_html(html), re.I | re.S):
            text = compact(re.sub(r"<[^>]+>", " ", match), 600)
            if len(text) >= 80:
                return text
        return None
    soup = BeautifulSoup(_decode_html(html), "html.parser")
    for paragraph in soup.find_all("p"):
        text = compact(paragraph.get_text(" ", strip=True), 600)
        if len(text) >= 80:
            return text
    return None


def infer_organization_type(text: str) -> str | None:
    lowered = f" {text.lower()} "
    for organization_type, terms in ORG_TYPE_TERMS.items():
        if any(term in lowered for term in terms):
            return organization_type
    return None


def infer_geography(text: str) -> str | None:
    lowered = text.lower()
    # Priority order: specific cities first, then regions
    # This prevents "Hong Kong" matching before "Shenzhen" in texts like "香港中文大学（深圳）"
    CITY_PRIORITY = (
        ("Shenzhen", ("shenzhen", "深圳")),
        ("Hong Kong", ("hong kong", "香港")),
        ("Singapore", ("singapore", "新加坡")),
        ("Beijing", ("beijing", "北京")),
        ("Shanghai", ("shanghai", "上海")),
    )
    REGION_PRIORITY = (
        ("Greater Bay Area", ("greater bay area", "大湾区", "粤港澳大湾区")),
        ("Guangdong", ("guangdong", "广东")),
        ("China", ("china", "中国")),
        ("Asia", ("asia", "亚洲")),
        ("Malaysia", ("malaysia", "马来西亚")),
        ("Indonesia", ("indonesia", "印度尼西亚", "印尼")),
        ("Vietnam", ("vietnam", "越南")),
        ("Thailand", ("thailand", "泰国")),
        ("India", ("india", "印度")),
        ("Japan", ("japan", "日本")),
        ("Korea", ("korea", "韩国")),
        ("United States", ("united states", "美国")),
        ("United Kingdom", ("united kingdom", "英国")),
    )
    # Check cities first (more specific)
    for english_name, keywords in CITY_PRIORITY:
        if any(kw in lowered for kw in keywords):
            return english_name
    # Then regions
    for english_name, keywords in REGION_PRIORITY:
        if any(kw in lowered for kw in keywords):
            return english_name
    return None


def clean_title(title: str | None) -> str | None:
    if not title:
        return None
    name = re.split(r"\s+[|-]\s+", title.strip())[0]
    return compact(name, 160) or None


def hostname_name(url: str | None) -> str | None:
    if not url:
        return None
    hostname = urlparse(url).netloc.lower().removeprefix("www.")
    if not hostname:
        return None
    return hostname.split(".")[0].replace("-", " ").title()


def compact(text: str | None, max_chars: int | None = None) -> str:
    value = re.sub(r"\s+", " ", text or "").strip()
    if max_chars and len(value) > max_chars:
        return value[: max_chars - 1].rstrip() + "..."
    return value


def _decode_html(html: bytes | str) -> str:
    return html.decode("utf-8", errors="ignore") if isinstance(html, bytes) else html


def _is_html_report(combined: str, text_len: int) -> bool:
    return text_len >= 2500 and sum(1 for term in REPORT_TERMS if term in combined) >= 2


def _is_directory(combined: str, link_count: int) -> bool:
    directory_terms = ("directory", "members", "member directory", "ecosystem map", "find investors", "startup database")
    return link_count >= 12 and any(term in combined for term in directory_terms)


def _is_organization_page(combined: str, lowered_url: str, link_count: int) -> bool:
    if link_count >= 50 and _is_directory(combined, link_count):
        return False
    org_term_hit = any(term in combined for terms in ORG_TYPE_TERMS.values() for term in terms)
    homepage_like = urlparse(lowered_url).path.strip("/") in {"", "about", "about-us", "who-we-are"}
    about_hit = any(term in combined for term in ("about us", "our mission", "we support", "we invest", "members include"))
    return org_term_hit and (homepage_like or about_hit)
