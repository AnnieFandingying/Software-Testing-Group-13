"""Selenium end-to-end checks for Member C.

The tests exercise the Online Boutique frontend like a real user:
set currency, add a product to cart, submit checkout, and verify the
displayed total paid matches the discount contract implemented by
discountservice.

Environment variables:
  FRONTEND_URL: exposed frontend URL, for example http://127.0.0.1:8080
  SELENIUM_BROWSER: chrome or firefox, default chrome
  SELENIUM_HEADLESS: true/false, default true
  SELENIUM_TIMEOUT_SECONDS: explicit wait timeout, default 20
  PRODUCT_ID: product id used by checkout flow, default 1YMWWN1N4O
  PRODUCT_QUANTITY: quantity from the product page dropdown, default 1
  CHECKOUT_ONLY_CURRENCY: optional CNY or USD to run one case only
  TELEMETRY_METRICS_URL: optional telemetry /metrics URL for post-checkout assert
  SELENIUM_RESULT_FILE: optional JSONL output path
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import pytest
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait


DEFAULT_PRODUCT_ID = "1YMWWN1N4O"  # Watch, high enough to hit CNY 700 tier.
CHECKOUT_FORM = "form.cart-checkout-form"


def bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://127.0.0.1:8080").rstrip("/")


def page_url(path: str) -> str:
    return urljoin(frontend_url() + "/", path.lstrip("/"))


def wait_for_ready(driver: webdriver.Remote, timeout: int) -> None:
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def parse_money(text: str) -> Decimal:
    normalized = text.replace(",", "").replace("\xa0", " ")
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        raise AssertionError(f"could not parse money from text: {text!r}")
    return Decimal(match.group(0)).quantize(Decimal("0.01"))


def expected_discount(currency: str, original_total: Decimal) -> tuple[Decimal, str]:
    if currency != "CNY":
        return Decimal("0.00"), "NO_DISCOUNT"

    # discountservice uses Money.Units for tier matching, so nanos are floored.
    units = int(original_total.to_integral_value(rounding=ROUND_FLOOR))
    if units >= 700:
        return Decimal("200.00"), "FULL_700_MINUS_200"
    if units >= 400:
        return Decimal("100.00"), "FULL_400_MINUS_100"
    if units >= 200:
        return Decimal("50.00"), "FULL_200_MINUS_50"
    return Decimal("0.00"), "NO_DISCOUNT"


def checkout_cases() -> Iterable[tuple[str, str, str]]:
    product_id = os.getenv("PRODUCT_ID", DEFAULT_PRODUCT_ID)
    quantity = os.getenv("PRODUCT_QUANTITY", "1")
    only_currency = os.getenv("CHECKOUT_ONLY_CURRENCY")
    if only_currency:
        yield only_currency.upper(), product_id, quantity
        return
    yield "CNY", product_id, quantity
    yield "USD", product_id, quantity


@pytest.fixture()
def driver() -> Iterable[webdriver.Remote]:
    browser = os.getenv("SELENIUM_BROWSER", "chrome").strip().lower()
    headless = bool_env("SELENIUM_HEADLESS", True)

    if browser == "firefox":
        options = webdriver.FirefoxOptions()
        if headless:
            options.add_argument("-headless")
        drv = webdriver.Firefox(options=options)
    else:
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--window-size=1440,1000")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        drv = webdriver.Chrome(options=options)

    drv.set_page_load_timeout(int(os.getenv("SELENIUM_TIMEOUT_SECONDS", "20")))
    try:
        yield drv
    finally:
        drv.quit()


def set_currency(driver: webdriver.Remote, wait: WebDriverWait, currency: str) -> None:
    driver.get(page_url("/"))
    wait_for_ready(driver, wait._timeout)
    selector = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "select[name='currency_code']"))
    )
    Select(selector).select_by_value(currency)
    def selected_currency_matches(d: webdriver.Remote) -> bool:
        try:
            return (
                Select(d.find_element(By.CSS_SELECTOR, "select[name='currency_code']"))
                .first_selected_option.get_attribute("value")
                == currency
            )
        except StaleElementReferenceException:
            return False

    wait.until(selected_currency_matches)
    wait_for_ready(driver, wait._timeout)


def add_product_to_cart(
    driver: webdriver.Remote, wait: WebDriverWait, product_id: str, quantity: str
) -> None:
    driver.get(page_url(f"/product/{product_id}"))
    wait_for_ready(driver, wait._timeout)
    Select(wait.until(EC.element_to_be_clickable((By.ID, "quantity")))).select_by_visible_text(
        quantity
    )
    wait.until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "form[action$='/cart'] button[type='submit']")
        )
    ).click()
    wait.until(EC.url_contains("/cart"))
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, CHECKOUT_FORM)))


def read_cart_total(driver: webdriver.Remote, wait: WebDriverWait) -> Decimal:
    row = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".cart-summary-total-row"))
    )
    return parse_money(row.text)


def submit_checkout(driver: webdriver.Remote, wait: WebDriverWait) -> Decimal:
    wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, f"{CHECKOUT_FORM} button"))).click()
    wait.until(
        EC.presence_of_element_located(
            (By.XPATH, "//*[contains(normalize-space(), 'Your order is complete')]")
        )
    )
    total_paid = wait.until(
        EC.presence_of_element_located(
            (
                By.XPATH,
                "//*[normalize-space()='Total Paid']/following-sibling::*[1]",
            )
        )
    )
    return parse_money(total_paid.text)


def fetch_telemetry_metrics(expected_rule: str) -> str | None:
    metrics_url = os.getenv("TELEMETRY_METRICS_URL")
    if not metrics_url or expected_rule == "NO_DISCOUNT":
        return None

    last_error: Exception | None = None
    for _ in range(5):
        try:
            with urllib.request.urlopen(metrics_url, timeout=3) as response:
                text = response.read().decode("utf-8", "replace")
            if f'boutique_discount_hits_total{{rule="{expected_rule}"' in text:
                return text
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
        time.sleep(1)

    if last_error:
        raise AssertionError(f"telemetry metrics endpoint failed: {last_error}")
    raise AssertionError(f"telemetry metrics did not include rule {expected_rule}")


def write_result(payload: dict) -> None:
    result_file = Path(
        os.getenv(
            "SELENIUM_RESULT_FILE",
            "results/member_c/selenium/checkout_discount_results.jsonl",
        )
    )
    result_file.parent.mkdir(parents=True, exist_ok=True)
    with result_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


@pytest.mark.parametrize("currency,product_id,quantity", list(checkout_cases()))
def test_checkout_total_matches_discount_contract(
    driver: webdriver.Remote, currency: str, product_id: str, quantity: str
) -> None:
    timeout = int(os.getenv("SELENIUM_TIMEOUT_SECONDS", "20"))
    wait = WebDriverWait(driver, timeout)
    timings: dict[str, float] = {}

    started = time.perf_counter()
    try:
        step = time.perf_counter()
        set_currency(driver, wait, currency)
        timings["set_currency_ms"] = round((time.perf_counter() - step) * 1000, 2)

        step = time.perf_counter()
        add_product_to_cart(driver, wait, product_id, quantity)
        timings["add_to_cart_ms"] = round((time.perf_counter() - step) * 1000, 2)

        cart_total = read_cart_total(driver, wait)
        discount, expected_rule = expected_discount(currency, cart_total)
        expected_total = (cart_total - discount).quantize(Decimal("0.01"))

        step = time.perf_counter()
        order_total = submit_checkout(driver, wait)
        timings["checkout_ms"] = round((time.perf_counter() - step) * 1000, 2)

        tolerance = Decimal("0.05")
        assert abs(order_total - expected_total) <= tolerance, (
            f"{currency} checkout total mismatch: cart={cart_total}, "
            f"discount={discount}, expected={expected_total}, actual={order_total}"
        )

        metrics_text = fetch_telemetry_metrics(expected_rule)
        payload = {
            "status": "passed",
            "frontend_url": frontend_url(),
            "currency": currency,
            "product_id": product_id,
            "quantity": int(quantity),
            "cart_total": str(cart_total),
            "expected_discount": str(discount),
            "expected_rule": expected_rule,
            "actual_total_paid": str(order_total),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "timings": timings,
            "telemetry_checked": metrics_text is not None,
        }
        write_result(payload)
    except TimeoutException as exc:
        write_result(
            {
                "status": "failed",
                "frontend_url": frontend_url(),
                "currency": currency,
                "product_id": product_id,
                "quantity": quantity,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "error": f"selenium timeout: {exc}",
                "timings": timings,
            }
        )
        raise
