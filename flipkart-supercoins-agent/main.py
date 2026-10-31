import os
from datetime import datetime

from playwright.sync_api import sync_playwright

from config import MAX_PRODUCTS
from scraper import collect_products, login_to_flipkart
from extractor import extract_product
from analyzer import analyze_products


def _log(message):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


def save_progress_snapshot(results):
    if not results:
        _log("No results captured yet; skipping snapshot save.")
        return None

    output_dir = "output"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"supercoins_report_{timestamp}.xlsx"
    _log(f"Saving progress snapshot to {output_dir}/{file_name}")
    analyze_products(results, output_dir=output_dir, output_name=file_name)
    return file_name


direct_url = os.getenv("FLIPKART_URL")
if direct_url and direct_url.strip():
    categories = [direct_url.strip()]
    _log(f"Using direct Flipkart URL override: {direct_url}")
else:
    with open("data/categories.txt") as f:
        categories = [
            line.strip()
            for line in f
            if line.strip()
        ]
    _log(f"Loaded {len(categories)} categories from data/categories.txt")

login_required = os.getenv("FLIPKART_LOGIN_REQUIRED")
if login_required is None:
    print("Choose Flipkart login mode:")
    print("1) Login required")
    print("2) No login (skip login)")
    try:
        choice = input("Enter 1 or 2: ").strip().lower()
        if choice in {"2", "no", "skip", "n", "false", "0"}:
            login_required = "false"
        else:
            login_required = "true"
    except EOFError:
        login_required = "true"
    except KeyboardInterrupt:
        login_required = "true"

login_required = login_required not in {"0", "false", "no", "n", "skip", "off"}

with sync_playwright() as p:
    _log("Launching Playwright browser session.")
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    results = []

    try:
        if login_required:
            _log("Starting Flipkart login sequence.")
            login_to_flipkart(page, wait_for_login_seconds=None)
        else:
            _log("Skipping Flipkart login because no-login mode was selected.")

        _log(f"Collecting product URLs with limit {MAX_PRODUCTS}.")
        urls = collect_products(categories, limit=MAX_PRODUCTS, page=page)
        _log(f"Collected {len(urls)} product URLs to process.")

        for index, url in enumerate(urls, start=1):
            _log(f"Processing product {index}/{len(urls)}: {url}")
            result = extract_product(url, page=page)
            results.append(result)
            _log(f"Scanned {index}/{len(urls)} and stored one result.")

            if index % 10 == 0 or index == len(urls):
                save_progress_snapshot(results)

        _log(f"Finished product extraction. Final result count: {len(results)}")
        analyze_products(results)
    except KeyboardInterrupt:
        _log("Interrupted by user. Saving captured progress...")
        save_progress_snapshot(results)
    except Exception as exc:
        _log(f"Scraping stopped unexpectedly: {exc}")
        save_progress_snapshot(results)
        raise
    finally:
        try:
            _log("Closing browser session.")
            browser.close()
        except Exception:
            _log("Browser already closed or shutdown failed.")

_log("Scanning completed!")