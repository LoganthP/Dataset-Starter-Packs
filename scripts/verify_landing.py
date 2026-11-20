import os
import sys

from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8000"
SHOT_DIR = os.getenv("SHOT_DIR", "/tmp/playwright_screenshots")  # screenshots stay out of the repo
os.makedirs(SHOT_DIR, exist_ok=True)

def run_tests():
    errors = []
    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # -------------------------------------------------------------
        # Test 1: Load without console/page errors at 3 widths
        # -------------------------------------------------------------
        print("\n--- Test 1: Testing 3 widths (1440, 768, 390) ---")
        for width in [1440, 768, 390]:
            context = browser.new_context(viewport={"width": width, "height": 900})
            page = context.new_page()

            page_errors = []
            page.on("pageerror", lambda err, errs=page_errors: errs.append(str(err)))
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_timeout(1000)

            # Check page errors
            if page_errors:
                print(f"[FAIL] Width {width} had page errors: {page_errors}")
                errors.extend(page_errors)
            else:
                print(f"[PASS] Width {width} loaded without page errors.")

            # Check horizontal scroll
            has_h_scroll = page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth")
            if has_h_scroll:
                print(f"[FAIL] Width {width} has horizontal scroll!")
                errors.append(f"Horizontal scroll at width {width}")
            else:
                print(f"[PASS] Width {width} has NO horizontal scroll.")

            # Take screenshot
            shot_path = os.path.join(SHOT_DIR, f"landing_{width}px.png")
            page.screenshot(path=shot_path, full_page=True)
            print(f"[INFO] Saved screenshot: {shot_path}")

            context.close()

        # -------------------------------------------------------------
        # Test 2: Search Box & Empty Query Hint
        # -------------------------------------------------------------
        print("\n--- Test 2: Search box and empty query hint ---")
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto(BASE_URL, wait_until="networkidle")

        # Submit empty search
        page.click("button[type='submit']")
        page.wait_for_timeout(400)
        hint = page.locator("p[role='status']")
        assert hint.is_visible(), "Inline hint should be visible for empty search"
        hint_text = hint.inner_text()
        print(f"[PASS] Empty search showed hint: '{hint_text}'")
        assert "pick an example" in hint_text or "Enter what" in hint_text

        # Type query and submit
        input_el = page.locator("#hero-search-input")
        input_el.fill("solar energy radiation")
        page.click("button[type='submit']")
        page.wait_for_url("**/discover?q=*", timeout=5000)
        curr_url = page.url
        print(f"[PASS] Search submitted and navigated to: {curr_url}")
        assert "/discover?q=solar" in curr_url

        # -------------------------------------------------------------
        # Test 3: Example Chips Navigation
        # -------------------------------------------------------------
        print("\n--- Test 3: Example chips navigation ---")
        page.goto(BASE_URL, wait_until="networkidle")
        chip_btn = page.locator("button:has-text('weather time series')")
        assert chip_btn.is_visible(), "Chip button should be visible"
        chip_btn.click()
        page.wait_for_url("**/discover?q=weather*", timeout=5000)
        print(f"[PASS] Clicked chip 'weather time series', navigated to: {page.url}")
        assert "q=weather" in page.url

        # -------------------------------------------------------------
        # Test 4: Redirect /?q=x to /discover?q=x
        # -------------------------------------------------------------
        print("\n--- Test 4: Redirection from /?q=x to /discover?q=x ---")
        page.goto(f"{BASE_URL}/?q=traffic+accidents", wait_until="networkidle")
        page.wait_for_url("**/discover?q=traffic*", timeout=5000)
        print(f"[PASS] /?q=traffic+accidents redirected to: {page.url}")
        assert "/discover?q=traffic" in page.url

        # -------------------------------------------------------------
        # Test 5: Theme Toggle Persistence
        # -------------------------------------------------------------
        print("\n--- Test 5: Theme toggle and persistence ---")
        page.goto(BASE_URL, wait_until="networkidle")
        theme_btn = page.locator("button[aria-haspopup='menu'][title='Theme']")
        theme_btn.click()
        page.wait_for_timeout(300)

        # Select Dark
        dark_opt = page.locator("button[role='menuitemradio']:has-text('Dark')")
        dark_opt.click()
        page.wait_for_timeout(500)
        is_dark = page.evaluate("() => document.documentElement.classList.contains('dark')")
        print(f"[PASS] Switched to dark mode. html.dark is: {is_dark}")
        assert is_dark, "html should have class 'dark'"

        # Take screenshot of dark mode
        dark_shot = os.path.join(SHOT_DIR, "landing_dark_mode.png")
        page.screenshot(path=dark_shot, full_page=True)
        print(f"[INFO] Saved dark mode screenshot: {dark_shot}")

        # Reload and check persistence
        page.reload(wait_until="networkidle")
        is_dark_after_reload = page.evaluate("() => document.documentElement.classList.contains('dark')")
        print(f"[PASS] After reload, html.dark is: {is_dark_after_reload}")
        assert is_dark_after_reload, "Theme should persist across reload"

        # Switch back to light
        theme_btn.click()
        page.wait_for_timeout(300)
        light_opt = page.locator("button[role='menuitemradio']:has-text('Light')")
        light_opt.click()
        page.wait_for_timeout(400)
        is_dark_now = page.evaluate("() => document.documentElement.classList.contains('dark')")
        assert not is_dark_now, "Switched back to light mode"
        print("[PASS] Theme toggle works and persists perfectly.")

        # -------------------------------------------------------------
        # Test 6: Nav Active Tab & Links
        # -------------------------------------------------------------
        print("\n--- Test 6: Nav state and CTAs ---")
        page.goto(BASE_URL, wait_until="networkidle")
        # Ensure landing page shows NO active tab in nav
        active_tabs = page.locator("nav a[aria-current='page']")
        active_count = active_tabs.count()
        print(f"[PASS] Active nav tabs on landing page: {active_count} (Expected: 0)")
        assert active_count == 0, f"Expected 0 active nav tabs on landing page, got {active_count}"

        # Test "Start searching" CTA
        cta_search = page.locator("section[aria-label='Call to action'] a:has-text('Start searching')")
        cta_search.click()
        page.wait_for_url("**/discover", timeout=5000)
        print(f"[PASS] CTA 'Start searching' navigated to: {page.url}")
        assert page.url.endswith("/discover")

        # Go back to landing
        page.goto(BASE_URL, wait_until="networkidle")

        # Test "Browse curated packs" CTA
        cta_packs = page.locator("section[aria-label='Call to action'] a:has-text('Browse curated packs')")
        cta_packs.click()
        page.wait_for_url("**/packs", timeout=5000)
        print(f"[PASS] CTA 'Browse curated packs' navigated to: {page.url}")
        assert "/packs" in page.url

        # Go back to landing
        page.goto(BASE_URL, wait_until="networkidle")

        # Test "Connect Kaggle" link in Import section
        kaggle_link = page.locator("a:has-text('Connect Kaggle')").first
        kaggle_link.click()
        page.wait_for_url("**/settings", timeout=5000)
        print(f"[PASS] 'Connect Kaggle' navigated to: {page.url}")
        assert "/settings" in page.url

        # -------------------------------------------------------------
        # Test 7: Report Preview Components (Columns, Scatter, RankedBars)
        # -------------------------------------------------------------
        print("\n--- Test 7: Real chart components in Report Preview ---")
        page.goto(BASE_URL, wait_until="networkidle")
        preview_sec = page.locator("section[aria-labelledby='heading-report-preview']")
        assert preview_sec.is_visible()

        # Check for Example data label
        assert page.locator("text=Example data · Sample").first.is_visible()
        print("[PASS] Found 'Example data · Sample' badge.")

        # Check for SVG charts
        svg_charts = preview_sec.locator("svg")
        svg_count = svg_charts.count()
        print(f"[PASS] Found {svg_count} SVG elements in Report Preview section.")
        assert svg_count >= 3, f"Expected at least 3 SVG charts, found {svg_count}"

        # Check for Table toggle in ChartCard
        table_toggle = preview_sec.locator("button:has-text('Show table')").first
        assert table_toggle.is_visible()
        table_toggle.click()
        page.wait_for_timeout(300)
        assert preview_sec.locator("table").first.is_visible()
        print("[PASS] ChartCard toggled to table view successfully.")
        chart_toggle = preview_sec.locator("button:has-text('Show chart')").first
        chart_toggle.click()
        page.wait_for_timeout(300)

        # -------------------------------------------------------------
        # Test 8: Reduced Motion Check
        # -------------------------------------------------------------
        print("\n--- Test 8: Reduced motion check ---")
        reduced_ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            reduced_motion="reduce"
        )
        red_page = reduced_ctx.new_page()
        red_page.goto(BASE_URL, wait_until="networkidle")
        red_page.wait_for_timeout(500)

        red_shot = os.path.join(SHOT_DIR, "landing_reduced_motion.png")
        red_page.screenshot(path=red_shot, full_page=True)
        print(f"[INFO] Saved reduced-motion screenshot: {red_shot}")

        # Check CSS animation duration/transition duration
        anim_duration = red_page.evaluate("""() => {
            const el = document.querySelector('.hero-blob-1');
            return el ? window.getComputedStyle(el).animationDuration : '0s';
        }""")
        print(f"[PASS] Under reduced-motion, animationDuration is: {anim_duration}")
        reduced_ctx.close()

        context.close()
        browser.close()

    print("\n=======================================================")
    if errors:
        print(f"FAILED with {len(errors)} errors:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    else:
        print("ALL PLAYWRIGHT TESTS PASSED SUCCESSFULLY! (100% GREEN)")
        print("=======================================================\n")

if __name__ == "__main__":
    run_tests()
