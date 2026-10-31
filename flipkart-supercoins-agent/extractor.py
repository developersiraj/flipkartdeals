import re
from datetime import datetime

from playwright.sync_api import sync_playwright

from scraper import login_to_flipkart


def _log(message):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


def extract_products_parallel(urls, page=None, max_workers=None):
    """Use the same authenticated session for the whole extraction run to avoid repeated login prompts."""
    if not urls:
        _log("No product URLs to extract.")
        return []

    _log(f"Starting extraction for {len(urls)} product URLs.")
    if page is not None:
        results = [extract_product(url, page=page) for url in urls]
        _log(f"Finished extraction for {len(results)} products with a shared page.")
        return results

    results = [extract_product(url) for url in urls]
    _log(f"Finished extraction for {len(results)} products in standalone mode.")
    return results


def _extract_discount_value(text):
    if not text:
        return None

    patterns = [
        r"(\d{1,3})%\s*(?:off|discount)",
        r"(\d{1,3})%",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return f"{match.group(1)}%"
    return None


def _extract_price_block(text):
    if not text:
        return {"discount": None, "actual_price": None, "discount_price": None}

    discount_value = _extract_discount_value(text)
    prices = re.findall(r"₹\s?[\d,]+", text)

    actual_price = None
    discount_price = None

    if len(prices) >= 2:
        actual_price = prices[0].strip()
        discount_price = prices[-1].strip()
    elif len(prices) == 1:
        discount_price = prices[0].strip()

    return {
        "discount": discount_value,
        "actual_price": actual_price,
        "discount_price": discount_price,
    }


def _extract_coupon_value(text):
    if not text:
        return None

    patterns = [
        r"(?:with\s+)?(?:Black Deal|Bank Offer|Coupon|Offer|Deal)",
        r"(?:coupon|code|offer)\s*[:\-]?\s*([A-Za-z0-9]+)",
        r"(?:get|use|apply)\s+([A-Za-z0-9]+)\s+(?:coupon|code)",
        r"(?:with\s+)?([A-Za-z0-9]+\s+Deal)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(0).strip()
            if value.lower().startswith("with "):
                return value[5:].strip()
            return value
    return None


def extract_product(url, page=None):
    _log(f"Extracting product data for: {url}")

    if page is None:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            login_to_flipkart(page)

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000
            )

            page.wait_for_timeout(3000)

            title = page.title()
            text = page.locator("body").inner_text()

            coin_match = re.search(
                r"(\d+)\s*SuperCoins",
                text,
                re.IGNORECASE
            )

            price_block = _extract_price_block(text)
            discount_value = price_block["discount"]
            coupon_value = _extract_coupon_value(text)

            result = {
                "url": url,
                "product": title,
                "price": price_block["actual_price"] or price_block["discount_price"],
                "discount": discount_value,
                "actual_price": price_block["actual_price"],
                "discount_price": price_block["discount_price"],
                "coupon": coupon_value,
                "supercoins": int(coin_match.group(1))
                    if coin_match else None
            }

            _log(f"Extracted result for {url}: {result}")
            browser.close()

            return result

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60000
    )

    page.wait_for_timeout(3000)

    title = page.title()
    text = page.locator("body").inner_text()

    coin_match = re.search(
        r"(\d+)\s*SuperCoins",
        text,
        re.IGNORECASE
    )

    price_block = _extract_price_block(text)
    discount_value = price_block["discount"]
    coupon_value = _extract_coupon_value(text)

    result = {
        "url": url,
        "product": title,
        "price": price_block["actual_price"] or price_block["discount_price"],
        "discount": discount_value,
        "actual_price": price_block["actual_price"],
        "discount_price": price_block["discount_price"],
        "coupon": coupon_value,
        "supercoins": int(coin_match.group(1))
            if coin_match else None
    }
    _log(f"Extracted result for {url}: {result}")
    return result