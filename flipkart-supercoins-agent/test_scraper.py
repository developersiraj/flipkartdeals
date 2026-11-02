import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from analyzer import analyze_products
from extractor import (
    _extract_coupon_value,
    _extract_discount_value,
    _extract_price_block,
    extract_product,
    extract_products_parallel,
)
from scraper import (
    collect_products,
    login_to_flipkart,
    normalize_category_url,
    should_skip_login,
    sort_products_by_price_high_to_low,
)


class NormalizeCategoryUrlTests(unittest.TestCase):
    def test_category_name_is_converted_to_search_url(self):
        self.assertEqual(
            normalize_category_url("Mobiles"),
            "https://www.flipkart.com/search?q=Mobiles",
        )

    def test_existing_url_is_preserved(self):
        url = "https://www.flipkart.com/search?q=Electronics"
        self.assertEqual(normalize_category_url(url), url)

    def test_analyze_products_creates_timestamped_excel_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            products = [{
                "url": "https://example.com/product",
                "product": "Sample Watch",
                "price": "₹ 999",
                "supercoins": 20,
            }]

            result = analyze_products(products, output_dir=temp_dir)

            self.assertEqual(len(result), 1)
            saved_files = [name for name in os.listdir(temp_dir) if name.endswith(".xlsx")]
            self.assertTrue(saved_files)
            self.assertTrue(any("supercoins_report_" in name for name in saved_files))

    def test_analyze_products_falls_back_when_excel_write_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            products = [{
                "url": "https://example.com/product",
                "product": "Sample Watch",
                "price": "₹ 999",
                "supercoins": 20,
            }]

            original_to_excel = __import__("analyzer").pd.DataFrame.to_excel

            def fake_to_excel(self, path, *args, **kwargs):
                if str(path).endswith("sample.xlsx"):
                    raise RuntimeError("IO_WRITE")
                return original_to_excel(self, path, *args, **kwargs)

            with patch("analyzer.pd.DataFrame.to_excel", new=fake_to_excel):
                result = analyze_products(products, output_dir=temp_dir, output_name="sample.xlsx")

            self.assertEqual(len(result), 1)
            saved_files = [name for name in os.listdir(temp_dir) if name.endswith(".xlsx")]
            self.assertTrue(saved_files)
            self.assertTrue(any("backup" in name.lower() or "fallback" in name.lower() for name in saved_files))

    def test_discount_and_coupon_are_extracted_from_price_context(self):
        text = "₹ 3,399\n₹ 3,999\n52% off\nwith Black Deal"

        self.assertEqual(_extract_discount_value(text), "52%")
        self.assertEqual(_extract_coupon_value(text), "Black Deal")

    def test_extract_product_reads_discount_and_coupon_from_discount_badge_dom(self):
        page = MagicMock()
        page.title.return_value = "Sample Watch"

        discount_badge = MagicMock()
        discount_badge.inner_text.return_value = "84% off"
        coupon_badge = MagicMock()
        coupon_badge.inner_text.return_value = "with Black Deal"
        body_locator = MagicMock(inner_text=MagicMock(return_value="₹ 3,999\n₹ 2,999\n84% off\nwith Black Deal"))

        def mock_locator(selector, *args, **kwargs):
            if selector == "body":
                return body_locator
            if selector == "div.v1zwn222.v1zwn20._1psv1zeb9._1psv1ze0._1psv1zeif":
                locator = MagicMock()
                locator.count.return_value = 1
                locator.nth.return_value = discount_badge
                return locator
            if selector == "div[class*='Black Deal']":
                locator = MagicMock()
                locator.count.return_value = 1
                locator.nth.return_value = coupon_badge
                return locator
            locator = MagicMock()
            locator.count.return_value = 0
            return locator

        page.locator.side_effect = mock_locator

        result = extract_product("https://example.com/watch", page=page)

        self.assertEqual(result["discount"], "84%")
        self.assertEqual(result["coupon"], "Black Deal")

    def test_discount_is_none_when_discount_badge_is_absent(self):
        page = MagicMock()
        page.title.return_value = "Sample Watch"

        def mock_locator(selector, *args, **kwargs):
            if selector == "body":
                return MagicMock(inner_text=MagicMock(return_value="₹ 3,999\n₹ 2,999\nBlack Deal"))
            locator = MagicMock()
            locator.count.return_value = 0
            return locator

        page.locator.side_effect = mock_locator

        result = extract_product("https://example.com/watch", page=page)

        self.assertIsNone(result["discount"])

    def test_extract_product_uses_exact_price_badge_when_present(self):
        page = MagicMock()
        page.title.return_value = "Sample Watch"

        def mock_locator(selector, *args, **kwargs):
            if selector == "body":
                return MagicMock(inner_text=MagicMock(return_value="₹ 59,990\n₹ 49,990\n37% off\nBlack Deal"))
            if selector == "div.v1zwn21n.v1zwn20._1psv1zeb9._1psv1ze0":
                locator = MagicMock()
                locator.count.return_value = 1
                locator.nth.return_value.inner_text.return_value = "₹49,990"
                return locator
            locator = MagicMock()
            locator.count.return_value = 0
            return locator

        page.locator.side_effect = mock_locator

        result = extract_product("https://example.com/watch", page=page)

        self.assertEqual(result["price"], "₹49,990")
        self.assertIsNone(result["discount"])

    def test_price_block_tracks_discount_and_prices_without_numeric_columns(self):
        text = "5%\n₹15,795\n₹15,000\nwith Black Deal"

        self.assertEqual(
            _extract_price_block(text),
            {"discount": "5%", "actual_price": "₹15,795", "discount_price": "₹15,000"},
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            df = analyze_products([
                {
                    "url": "https://example.com/product",
                    "product": "Sample Watch",
                    "discount": "5%",
                    "actual_price": "₹15,795",
                    "discount_price": "₹15,000",
                    "coupon": "Black Deal",
                    "supercoins": 20,
                }
            ], output_dir=temp_dir)

            self.assertNotIn("price_numeric", df.columns)
            self.assertNotIn("coins_per_1000", df.columns)


class LoginToFlipkartTests(unittest.TestCase):
    @patch("scraper.os.environ", {"FLIPKART_USERNAME": "user@example.com", "FLIPKART_PASSWORD": "secret"})
    def test_login_uses_environment_credentials(self):
        with patch("scraper.sync_playwright") as mock_playwright:
            mock_page = mock_playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_page.return_value
            mock_page.is_visible.return_value = True

            result = login_to_flipkart(mock_playwright.return_value.__enter__.return_value, wait_for_login_seconds=0)

            self.assertTrue(result)
            mock_page.goto.assert_any_call("https://www.flipkart.com", wait_until="domcontentloaded", timeout=60000)

    @patch("extractor.login_to_flipkart")
    def test_extract_product_reuses_existing_logged_in_page(self, login_mock):
        page = MagicMock()
        page.title.return_value = "Sample Product"
        page.locator.return_value.inner_text.return_value = "₹ 999 5 SuperCoins"

        result = extract_product("https://example.com/product", page=page)

        self.assertEqual(result["product"], "Sample Product")
        self.assertEqual(result["supercoins"], 5)
        login_mock.assert_not_called()
        page.goto.assert_called_once_with("https://example.com/product", wait_until="domcontentloaded", timeout=60000)

    @patch("scraper.os.environ", {"FLIPKART_USERNAME": "user@example.com", "FLIPKART_PASSWORD": "secret"})
    def test_login_only_runs_once_per_page(self):
        class LocatorStub:
            def count(self):
                return 1

        class PageStub:
            def __init__(self):
                self._flipkart_logged_in = True
                self.url = "https://www.flipkart.com/"
                self.goto_calls = 0

            def goto(self, *args, **kwargs):
                self.goto_calls += 1

            def is_closed(self):
                return False

            def locator(self, *_args, **_kwargs):
                return LocatorStub()

        page = PageStub()

        login_to_flipkart(page, wait_for_login_seconds=None)

        self.assertEqual(page.goto_calls, 0)

    def test_extract_products_parallel_returns_all_results(self):
        with patch("extractor.extract_product", side_effect=[{"url": "a"}, {"url": "b"}]) as mock_extract:
            result = extract_products_parallel(["a", "b"], max_workers=2)

            self.assertEqual(result, [{"url": "a"}, {"url": "b"}])
            self.assertEqual(mock_extract.call_count, 2)

    def test_login_returns_cleanly_when_page_is_closed(self):
        class ClosedPage:
            def is_closed(self):
                return True

            def goto(self, *_args, **_kwargs):
                return None

            def locator(self, *_args, **_kwargs):
                raise RuntimeError("page is closed")

        result = login_to_flipkart(ClosedPage(), wait_for_login_seconds=None)

        self.assertIsNotNone(result)

    @patch.dict("os.environ", {"FLIPKART_LOGIN_REQUIRED": "false"}, clear=False)
    def test_should_skip_login_returns_true_when_no_login_mode_is_selected(self):
        self.assertTrue(should_skip_login())

    def test_sort_products_by_price_high_to_low_uses_sort_option(self):
        page = MagicMock()
        page.locator.return_value.count.return_value = 1

        result = sort_products_by_price_high_to_low(page)

        self.assertTrue(result)
        page.locator.assert_called()

    def test_collect_products_walks_all_result_pages(self):
        class LocatorStub:
            def __init__(self, count_value=0, click_action=None):
                self._count = count_value
                self._click_action = click_action

            @property
            def first(self):
                return self

            def count(self):
                return self._count

            def click(self):
                if self._click_action is not None:
                    self._click_action()

        class PageStub:
            def __init__(self):
                self.current_page = 1
                self._page_hrefs = {
                    1: [
                        "https://www.flipkart.com/p/itma123",
                        "https://www.flipkart.com/p/itmb456",
                    ],
                    2: [
                        "https://www.flipkart.com/p/itmc789",
                        "https://www.flipkart.com/p/itmd012",
                    ],
                }

            def goto(self, *args, **kwargs):
                self.current_page = max(1, self.current_page)

            def wait_for_timeout(self, *_args, **_kwargs):
                return None

            def locator(self, selector, *args, **kwargs):
                if selector.startswith("a[href]"):
                    return MagicMock(evaluate_all=MagicMock(return_value=self._page_hrefs[self.current_page]))
                if "Price -- High to Low" in selector or "Price High to Low" in selector or "Price: High to Low" in selector or "Sort" in selector:
                    return LocatorStub(count_value=1)
                if "Next" in selector:
                    if self.current_page < 2:
                        return LocatorStub(count_value=1, click_action=lambda: setattr(self, "current_page", 2))
                    return LocatorStub(count_value=0)
                return LocatorStub(count_value=0)

        page = PageStub()

        results = collect_products(["Watches"], limit=1000, page=page)

        self.assertEqual(
            results,
            [
                "https://www.flipkart.com/p/itma123",
                "https://www.flipkart.com/p/itmb456",
                "https://www.flipkart.com/p/itmc789",
                "https://www.flipkart.com/p/itmd012",
            ],
        )


if __name__ == "__main__":
    unittest.main()
