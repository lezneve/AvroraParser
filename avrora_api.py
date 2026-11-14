"""api «аврори»: магазини, товар за штрихкодом, позначка «тільки на сайті», сканування."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import requests
from selectolax.parser import HTMLParser

from common import HEADERS, Scan, discount, get_json, get_sync, scan, session

PRICE_TAG_URL = "https://pt.avrora.ua/api/PriceTag/getInfo"
STORES_URL = "https://avrora.ua/index.php"
SEARCH_URL = "https://avrora.ua/"
ONLINE_ONLY_BADGE = "span.labels-item.variant_3520"
ONLINE_ONLY_TEXT = "Тільки на сайті"

KtFilter = frozenset[str] | None


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class Store:
    shop_number: str
    name: str
    city: str

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Store:
        return cls(str(d.get("shopNumber") or ""), d.get("name") or "", d.get("city") or "")


@dataclass(frozen=True)
class Product:
    name: str
    code: str
    kt: str
    price: float
    price_old: float
    rem_qty: float

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> Product:
        return cls(
            name=str(d.get("name") or "?"),
            code=str(d.get("code") or "-"),
            kt=str(d.get("kt") or "").strip(),
            price=_num(d.get("price")),
            price_old=_num(d.get("priceOld")),
            rem_qty=_num(d.get("remQty")),
        )

    @property
    def discount(self) -> int:
        return discount(self.price_old, self.price)

    def in_kt(self, kt: KtFilter) -> bool:
        return kt is None or self.kt in kt


def parse_kt(text: str) -> KtFilter:
    """'all' або порожньо означає без фільтра, інакше коди через кому."""
    text = text.strip().lower()
    if not text or text == "all":
        return None
    return frozenset(x.strip() for x in text.split(",") if x.strip())


def extract_product(data: Any) -> Product | None:
    """товар із відповіді api: сам корінь або поле data."""
    if not isinstance(data, dict):
        return None
    if data.get("name") or data.get("code"):
        return Product.from_api(data)
    inner = data.get("data")
    if isinstance(inner, dict) and (inner.get("name") or inner.get("code")):
        return Product.from_api(inner)
    return None


def price_params(barcode: int | str, shop_number: str) -> dict[str, str]:
    return {"barcode": str(barcode), "shopNumber": str(shop_number)}


def get_stores() -> list[Store]:
    data = get_sync(STORES_URL, {"dispatch": "pwa.store_locations", "is_ajax": 1})
    objects = data.get("objects", []) if isinstance(data, dict) else []
    if isinstance(objects, dict):
        objects = list(objects.values())
    return [Store.from_api(o) for o in objects if isinstance(o, dict)]


def stores_in(stores: list[Store], city: str) -> list[Store]:
    q = city.lower()
    return [s for s in stores if q in s.city.lower()]


def get_product(barcode: str, shop_number: str) -> Product | None:
    return extract_product(get_sync(PRICE_TAG_URL, price_params(barcode, shop_number)))


def is_online_only(name: str) -> bool:
    """шукає товар на сайті за латинськими словами з назви й дивиться на позначку."""
    words = " ".join(re.findall(r"[A-Za-z0-9]+", name))
    if not words:
        return False
    try:
        resp = requests.get(
            SEARCH_URL,
            params={"q": words, "dispatch": "products.search"},
            headers=HEADERS,
            timeout=10,
        )
        badge = HTMLParser(resp.text).css_first(ONLINE_ONLY_BADGE)
    except requests.RequestException:
        return False
    return badge is not None and ONLINE_ONLY_TEXT in badge.text()


def pick_discount(kt: KtFilter) -> Callable[[Any], tuple[int, list[Product]]]:
    """відбирає товари зі знижкою, залишком від 1 і потрібним kt."""

    def handle(data: Any) -> tuple[int, list[Product]]:
        p = extract_product(data)
        if p is None:
            return 0, []
        ok = p.in_kt(kt) and p.rem_qty >= 1 and p.price_old > p.price
        return 1, [p] if ok else []

    return handle


async def scan_barcodes(
    fetch: Callable[[int], Awaitable[Any]],
    start: int,
    end: int,
    kt: KtFilter,
    workers: int = 15,
) -> Scan:
    return await scan(
        range(start, end + 1),
        end - start + 1,
        fetch,
        pick_discount(kt),
        workers=workers,
        unit="штрихкодів",
        found_label="знижок",
    )


async def scan_discounts(
    shop_number: str, kt: KtFilter, start: int = 1, end: int = 150_000, workers: int = 15
) -> Scan:
    async with session(workers) as s:

        def fetch(barcode: int) -> Awaitable[Any]:
            return get_json(s, PRICE_TAG_URL, price_params(barcode, shop_number), timeout=5)

        return await scan_barcodes(fetch, start, end, kt, workers)
