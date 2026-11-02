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

    explicit_patterns = [
        r"(?:with\s+)?(Black Deal|Bank Offer|No Cost EMI|Exchange Offer|Special Price)",
        r"(?:coupon|code)\s*[:\-]?\s*([A-Za-z0-9]+)",
        r"(?:with\s+)?([A-Za-z0-9]+\s+Deal)",
    ]

    for pattern in explicit_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1) if match.lastindex else match.group(0)
            if value.lower().startswith("with "):
                value = value[5:].strip()
            return value.strip()

    if re.search(r"\bOffer\b", text, re.IGNORECASE):
        return "Offer"
    return None


def _read_text_from_dom(locator):
    try:
        if hasattr(locator, "count") and callable(locator.count):
            count = locator.count()
            values = []
            for index in range(count):
                try:
                    value = locator.nth(index).inner_text().strip()
                    if value:
                        values.append(value)
                except Exception:
                    continue
            return values
    except Exception:
        pass

    try:
        value = locator.inner_text().strip()
        if value:
            return [value]
    except Exception:
        pass

    return []


def _page_is_closed(page):
    if page is None:
        return True
    try:
        return page.is_closed() is True
    except Exception:
        return False


def _extract_discount_from_page(page):
    if page is None or _page_is_closed(page):
        return None

    selector = "div.v1zwn222.v1zwn20._1psv1zeb9._1psv1ze0._1psv1zeif"
    try:
        locator = page.locator(selector)
        for candidate in _read_text_from_dom(locator):
            discount = _extract_discount_value(candidate)
            if discount:
                return discount
    except Exception:
        return None
    return None


def _extract_coupon_from_page(page, text):
    if page is None or _page_is_closed(page):
        return _extract_coupon_value(text)

    selectors = [
        "div.v1zwn222.v1zwn20._1psv1zeb9._1psv1ze0._1psv1zeif",
        "div[class*='v1zwn22'][class*='_1psv1ze']",
        "div[class*='v1zwn22']",
        "div[class*='_1psv1ze']",
        "div[class*='Black Deal']",
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector)
            for candidate in _read_text_from_dom(locator):
                coupon = _extract_coupon_value(candidate)
                if coupon:
                    return coupon
        except Exception:
            continue
    return _extract_coupon_value(text)


def _extract_price_from_page(page):
    if page is None or _page_is_closed(page):
        return None

    selectors = [
        "div.v1zwn21n.v1zwn20._1psv1zeb9._1psv1ze0",
        "div[class*='v1zwn21n'][class*='_1psv1ze0']",
        "div[class*='v1zwn21n']",
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector)
            for candidate in _read_text_from_dom(locator):
                match = re.search(r"₹\s?[\d,]+", candidate)
                if match:
                    return match.group(0).strip()
        except Exception:
            continue
    return None


def extract_product(url, page=None):
    _log(f"Extracting product data for: {url}")

    if page is not None and _page_is_closed(page):
        _log(f"Skipping extraction for closed page: {url}")
        return {
            "url": url,
            "product": None,
            "price": None,
            "discount": None,
            "actual_price": None,
            "discount_price": None,
            "coupon": None,
            "supercoins": None,
        }

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

            if not _page_is_closed(page):
                page.wait_for_timeout(3000)

            title = page.title()
            text = page.locator("body").inner_text()

            coin_match = re.search(
                r"(\d+)\s*SuperCoins",
                text,
                re.IGNORECASE
            )

            price_block = _extract_price_block(text)
            page_price = _extract_price_from_page(page)
            discount_value = _extract_discount_from_page(page)
            coupon_value = _extract_coupon_from_page(page, text) or _extract_coupon_value(text)

            result = {
                "url": url,
                "product": title,
                "price": page_price or price_block["actual_price"] or price_block["discount_price"],
                "discount": discount_value,
                "actual_price": price_block["actual_price"] or page_price,
                "discount_price": price_block["discount_price"] or page_price,
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

    if not _page_is_closed(page):
        page.wait_for_timeout(3000)

    title = page.title()
    text = page.locator("body").inner_text()

    coin_match = re.search(
        r"(\d+)\s*SuperCoins",
        text,
        re.IGNORECASE
    )

    price_block = _extract_price_block(text)
    page_price = _extract_price_from_page(page)
    discount_value = _extract_discount_from_page(page)
    coupon_value = _extract_coupon_from_page(page, text) or _extract_coupon_value(text)

    result = {
        "url": url,
        "product": title,
        "price": page_price or price_block["actual_price"] or price_block["discount_price"],
        "discount": discount_value,
        "actual_price": price_block["actual_price"] or page_price,
        "discount_price": price_block["discount_price"] or page_price,
        "coupon": coupon_value,
        "supercoins": int(coin_match.group(1))
            if coin_match else None
    }
    _log(f"Extracted result for {url}: {result}")
    return result