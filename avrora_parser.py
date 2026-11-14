"""аврора: пошук товару за штрихкодом і сканування знижок у вибраному магазині."""

from __future__ import annotations

import asyncio

import requests

from avrora_api import (
    KtFilter,
    Product,
    Store,
    get_product,
    get_stores,
    is_online_only,
    parse_kt,
    scan_discounts,
    stores_in,
)
from common import (
    Config,
    Scan,
    accent,
    ask_number,
    clear_screen,
    dim,
    failed_line,
    money,
    table,
)

config = Config("config.json")
TOP = 20


def select_store() -> tuple[str, Store] | None:
    print(dim("завантажую магазини…"))
    try:
        stores = get_stores()
    except (requests.RequestException, ValueError) as e:
        print("не вдалося отримати магазини:", e)
        return None
    city = input(f"місто ({len(stores)} магазинів): ").strip()
    found = stores_in(stores, city)
    if not found:
        print("у цьому місті магазинів не знайдено")
        return None
    for i, s in enumerate(found, 1):
        print(f"{i:3d}  {s.shop_number:>6}  {s.name}")
    return city, found[ask_number("номер: ", 1, len(found)) - 1]


def print_product(p: Product) -> None:
    price = money(p.price)
    if p.price_old > p.price:
        price += "  " + accent(f"-{p.discount}%") + f", було {money(p.price_old)}"
    print()
    print(p.name)
    print(f"  ціна     {price}")
    print(f"  артикул  {p.code}")
    print(f"  залишок  {p.rem_qty:g}")
    print(f"  kt       {p.kt or '-'}")


def search(shop_number: str, kt: KtFilter) -> None:
    while True:
        barcode = input("\nштрихкод (порожньо — назад): ").strip()
        if not barcode or barcode.lower() == "exit":
            return
        if not barcode.isdigit():
            print("штрихкод складається лише з цифр")
            continue
        try:
            p = get_product(barcode, shop_number)
        except (requests.RequestException, ValueError) as e:
            print("помилка запиту:", e)
            continue
        if p is None:
            print("товар не знайдено")
        elif not p.in_kt(kt):
            print(dim(f"пропущено: kt {p.kt or '-'} не у фільтрі"))
        elif p.rem_qty == 0 and is_online_only(p.name):
            print("товар є лише на сайті")
        else:
            print_product(p)


def print_scan(res: Scan) -> None:
    found = sorted(res.found, key=lambda p: p.discount, reverse=True)
    print(f"перевірено товарів: {res.checked}, знижок: {len(found)}")
    if found:
        print()
        rows = [
            [f"-{p.discount}%", money(p.price), money(p.price_old), p.code, p.name]
            for p in found[:TOP]
        ]
        print(table(["знижка", "ціна", "було", "код", "назва"], rows))
    if res.failed:
        print()
        print(failed_line("штрихкодів", res.failed))


def main() -> None:
    clear_screen()
    cfg = config.load()
    shop_number = cfg.get("shop_number")
    shop_name = cfg.get("shop_name", "")
    kt_text = cfg.get("kt_filter", "all") or "all"

    if not shop_number:
        picked = select_store()
        if not picked:
            return
        city, store = picked
        shop_number, shop_name = store.shop_number, store.name
        config.save(city=city, shop_number=shop_number, shop_name=shop_name, kt_filter=kt_text)

    while True:
        print()
        print(f"аврора  {dim(f'{shop_name} ({shop_number}), kt: {kt_text}')}")
        print("  1  пошук за штрихкодом")
        print("  2  сканувати знижки")
        print("  3  змінити магазин")
        print("  4  змінити kt-фільтр")
        print("  0  вихід")
        choice = input("> ").strip()

        if choice == "1":
            search(str(shop_number), parse_kt(kt_text))
        elif choice == "2":
            print()
            print_scan(asyncio.run(scan_discounts(str(shop_number), parse_kt(kt_text))))
        elif choice == "3":
            picked = select_store()
            if picked:
                city, store = picked
                shop_number, shop_name = store.shop_number, store.name
                config.save(city=city, shop_number=shop_number, shop_name=shop_name)
        elif choice == "4":
            kt_text = input("kt через кому або all: ").strip() or "all"
            config.save(kt_filter=kt_text)
        elif choice == "0":
            return
        else:
            print("такого пункту немає")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print()
