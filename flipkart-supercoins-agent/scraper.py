import getpass
import os
import re
import time
from datetime import datetime
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright

from config import HEADLESS


def _log(message):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


def _count_locator(locator):
    try:
        count_value = locator.count()
    except Exception:
        return 0

    try:
        return int(count_value)
    except (TypeError, ValueError):
        return 0


def _click_first_visible(page, selectors):
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if _count_locator(locator) > 0:
                locator.click()
                return True
        except Exception:
            continue
    return False


def sort_products_by_price_high_to_low(page):
    """Sort the current Flipkart search results by price descending before collecting items."""
    if page is None:
        _log("Sort skipped because page is None.")
        return False

    _log("Attempting to sort products by price: High to Low.")

    sort_openers = [
        "button:has-text('Sort')",
        "div:has-text('Sort')",
        "text=Sort",
        "[aria-label='Sort']",
        "a:has-text('Sort')",
    ]
    sort_options = [
        "text=Price -- High to Low",
        "text=Price: High to Low",
        "text=Price High to Low",
        "a:has-text('Price -- High to Low')",
        "div:has-text('Price -- High to Low')",
        "span:has-text('Price -- High to Low')",
        "[title='Price -- High to Low']",
        "div[title='Price -- High to Low']",
    ]

    if _click_first_visible(page, sort_openers):
        _log("Opened sort menu.")
        page.wait_for_timeout(1000)

    if _click_first_visible(page, sort_options):
        _log("Selected 'Price -- High to Low'.")
        page.wait_for_timeout(2000)
        return True

    _log("Sort option 'Price -- High to Low' was not found.")
    return False


def normalize_category_url(category):
    if category is None:
        return None

    category = str(category).strip()
    if not category:
        return None

    if "://" in category:
        return category

    return f"https://www.flipkart.com/search?q={quote_plus(category)}"


def should_skip_login():
    value = os.getenv("FLIPKART_LOGIN_REQUIRED", "true").strip().lower()
    return value in {"0", "false", "no", "n", "skip", "off"}


def login_to_flipkart(playwright_or_page, wait_for_login_seconds=None, require_login=True):
    """Open Flipkart and wait until the user is actually signed in before continuing."""
    if require_login is False:
        _log("Login disabled by FLIPKART_LOGIN_REQUIRED; continuing without Flipkart login.")
        return playwright_or_page

    page = playwright_or_page
    browser = None

    if hasattr(playwright_or_page, "chromium"):
        browser = playwright_or_page.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        _log("Browser launched for Flipkart login flow.")
    elif hasattr(playwright_or_page, "context") and playwright_or_page.context is not None:
        browser = playwright_or_page.context.browser

    if getattr(page, "_flipkart_logged_in", False) is True:
        _log("Page already marked as logged in. Reusing existing session.")
        return page

    try:
        if page.is_closed() is True:
            _log("Login aborted because page is already closed.")
            return browser or page
    except Exception:
        _log("Could not inspect page state; returning early.")
        return browser or page

    username = os.getenv("FLIPKART_USERNAME")
    password = os.getenv("FLIPKART_PASSWORD")
    if username and password:
        _log("Using environment credentials for Flipkart login.")
    else:
        _log("No FLIPKART_USERNAME / FLIPKART_PASSWORD found; waiting for manual login.")

    try:
        _log("Opening Flipkart homepage.")
        page.goto("https://www.flipkart.com", wait_until="domcontentloaded", timeout=60000)
    except Exception:
        _log("Failed to open Flipkart homepage.")
        return browser or page

    login_trigger = page.locator("text=Login, text=Sign in").first
    try:
        if login_trigger.count() > 0:
            login_trigger.click()
    except TypeError:
        pass

    if username and password:
        phone_input = page.locator("input[type='tel'], input[type='email'], input[name*='mobile'], input[name*='phone']").first
        password_input = page.locator("input[type='password']").first

        try:
            if phone_input.count() > 0:
                phone_input.fill(username)
        except TypeError:
            pass

        try:
            if password_input.count() > 0:
                password_input.fill(password)
        except TypeError:
            pass

        submit_button = page.locator(
            "button:has-text('Login'), button:has-text('Request OTP'), button[type='submit'], input[type='submit']"
        ).first
        try:
            if submit_button.count() > 0:
                submit_button.click()
        except TypeError:
            pass

    if wait_for_login_seconds is not None and wait_for_login_seconds <= 0:
        _log("Login wait time is zero; skipping manual-login wait.")
        return browser or page

    print("Please log in to Flipkart in the browser window. The scraper will continue once you are signed in.")
    _log("Waiting for Flipkart login confirmation...")

    logged_in = False

    while True:
        try:
            if page.is_closed() is True:
                return browser or page
        except Exception:
            return browser or page

        try:
            logout_locator = page.locator("text=Logout")
            if logout_locator.count() > 0 or "logout" in str(getattr(page, "url", "")).lower():
                logged_in = True
                _log("Flipkart login detected via Logout state.")
                break
        except Exception:
            pass

        try:
            login_locator = page.locator("text=Login")
            account_locator = page.locator("text=My Account")
            if login_locator.count() == 0 and account_locator.count() > 0:
                logged_in = True
                _log("Flipkart login detected via 'My Account' state.")
                break
        except Exception:
            pass

        try:
            page.wait_for_timeout(2000)
        except Exception:
            return browser or page

    page._flipkart_logged_in = True
    _log("Login confirmation successful. Continuing scrape session.")
    return browser or page


def _next_page_button(page):
    selectors = [
        "a:has-text('Next')",
        "button:has-text('Next')",
        "[aria-label='Next']",
        "text=Next",
        "a[rel='next']",
        "a[title='Next']",
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if _count_locator(locator) > 0:
                return locator
        except Exception:
            continue
    return None


def _collect_product_links_on_page(page):
    try:
        links = page.locator("a[href]").evaluate_all("""els => els.map(a => a.href)""")
    except Exception:
        return []

    return [link for link in links if link and re.search(r"/p/", link)]


def collect_products(category_urls, limit=1000, page=None):

    products = {}
    browser = None
    _log(f"Starting product collection for {len(category_urls)} source entries. Limit: {limit}")

    def collect_for_page(category_url):
        nonlocal products

        if page is None or getattr(page, "is_closed", lambda: False)() is True:
            _log("Collection stopped because the page is closed.")
            return

        _log(f"Opening source URL: {category_url}")
        try:
            page.goto(category_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
        except Exception:
            _log(f"Failed to open source URL: {category_url}")
            return

        sort_products_by_price_high_to_low(page)

        page_index = 1
        while len(products) < limit:
            links = _collect_product_links_on_page(page)
            _log(f"Page {page_index}: found {len(links)} product links on current page.")
            for link in links:
                if len(products) >= limit:
                    break
                products[link] = link

            if len(products) >= limit:
                _log(f"Reached product limit {limit}. Stopping collection.")
                break

            next_page = _next_page_button(page)
            if next_page is None:
                _log("No next page button found. Ending category collection.")
                break

            try:
                _log(f"Moving to next category page #{page_index + 1}.")
                next_page.click()
                page.wait_for_timeout(3500)
                page_index += 1
            except Exception:
                _log("Could not click next page; stopping category collection.")
                break

    if page is None:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=HEADLESS)
            page = browser.new_page()
            _log("Launching browser for standalone collection mode.")
            login_to_flipkart(page)

            for category in category_urls:
                if len(products) >= limit:
                    break

                category_url = normalize_category_url(category)
                if not category_url:
                    _log(f"Skipping empty category: {category!r}")
                    continue

                _log(f"Processing category/source: {category}")
                collect_for_page(category_url)
                time.sleep(3)

            browser.close()

        _log(f"Standalone collection finished with {len(products)} unique product links.")
        return list(products.keys())[:limit]

    for category in category_urls:
        if len(products) >= limit:
            break

        category_url = normalize_category_url(category)
        if not category_url:
            _log(f"Skipping empty category/source: {category!r}")
            continue

        _log(f"Processing category/source: {category}")
        collect_for_page(category_url)
        time.sleep(3)

    _log(f"Collection finished with {len(products)} unique product links.")
    return list(products.keys())[:limit]