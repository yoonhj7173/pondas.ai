"""Stripe live products + prices 일괄 생성 (go-live step 6).

네 sk_live로 네 터미널에서 한 번만 실행 — 키가 채팅/리포지토리를 거치지 않는다.
6개(starter/pro/studio 구독 + pack_s/m/l 일회성) products+prices를 만들고, 우리 config의
stripe_prices 맵에 그대로 붙일 JSON을 출력한다. 멱등: 같은 이름 product가 있으면 재사용한다.

실행:
    STRIPE_SECRET_KEY=sk_live_xxx python backend/scripts/create_live_prices.py
(또는 cursor 세션에서:  ! STRIPE_SECRET_KEY=sk_live_xxx python backend/scripts/create_live_prices.py)

⚠️ sk_live는 환경변수로만 넘긴다. 코드/채팅에 키를 붙이지 말 것.
"""

from __future__ import annotations

import json
import os
import sys

import stripe

# item_key → (표시이름, USD 금액(센트), 'sub'|'once', plan|None, credits)
CATALOG = [
    ("starter", "pondas Starter", 1200, "sub", "starter", 2000),
    ("pro", "pondas Pro", 4000, "sub", "pro", 8000),
    ("studio", "pondas Studio", 20000, "sub", "studio", 45000),
    ("pack_s", "pondas Credit Pack S", 500, "once", None, 500),
    ("pack_m", "pondas Credit Pack M", 1300, "once", None, 1500),
    ("pack_l", "pondas Credit Pack L", 4000, "once", None, 5000),
]


def _find_product(name: str):
    """같은 이름의 product가 이미 있으면 재사용(중복 생성 방지)."""
    for p in stripe.Product.list(active=True, limit=100).auto_paging_iter():
        if p.name == name:
            return p
    return None


def main() -> None:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key.startswith("sk_live_"):
        sys.exit("STRIPE_SECRET_KEY must be a LIVE secret key (sk_live_...). Got: "
                 + (key[:8] + "..." if key else "<empty>"))
    stripe.api_key = key

    prices: dict[str, str] = {}
    for item_key, name, amount, kind, plan, credits in CATALOG:
        product = _find_product(name) or stripe.Product.create(name=name)
        md = {"item_key": item_key, "credits": str(credits)}
        if plan:
            md["plan"] = plan
        params = {
            "product": product.id,
            "currency": "usd",
            "unit_amount": amount,
            "metadata": md,
            "nickname": f"{item_key} (live)",
        }
        if kind == "sub":
            params["recurring"] = {"interval": "month"}
        price = stripe.Price.create(**params)
        prices[item_key] = price.id
        print(f"  {item_key:8s} {name:24s} ${amount/100:>6.2f} {kind:4s} -> {price.id}")

    print("\n=== config stripe_prices (이 JSON을 그대로 전달해줘) ===")
    print(json.dumps(prices))


if __name__ == "__main__":
    main()
