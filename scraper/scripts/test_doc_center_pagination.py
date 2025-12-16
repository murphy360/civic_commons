#!/usr/bin/env python3
"""Test script to debug Document Center pagination."""

import asyncio
from playwright.async_api import async_playwright


async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        url = "https://www.mytwinsburg.com/DocumentCenter/Index/433"
        print(f"Loading {url}")
        await page.goto(url, wait_until="networkidle")
        await page.wait_for_timeout(2000)
        
        # Count documents on page
        doc_links = await page.query_selector_all("a[href*='/DocumentCenter/View/']")
        print(f"Found {len(doc_links)} document links on first page")
        
        # Get all buttons with aria labels
        print("\nButtons with aria-label:")
        buttons = await page.query_selector_all("button[aria-label]")
        for btn in buttons:
            label = await btn.get_attribute("aria-label")
            disabled = await btn.get_attribute("disabled")
            print(f"  - {label} (disabled={disabled})")
        
        # Check for pagination row selector
        print("\nLooking for pagination controls...")
        
        # MUI pagination uses different selectors
        selectors = [
            ".MuiTablePagination-actions button",
            "[class*='pagination'] button", 
            "button[title*='page']",
            "button[title*='Page']",
            "[aria-label*='page']",
            "[aria-label*='Page']",
        ]
        
        for sel in selectors:
            elems = await page.query_selector_all(sel)
            if elems:
                print(f"  Found {len(elems)} elements for: {sel}")
                for elem in elems:
                    label = await elem.get_attribute("aria-label")
                    title = await elem.get_attribute("title")
                    text = await elem.text_content()
                    print(f"    label={label}, title={title}, text={text[:30] if text else None}")
        
        # Get all text that might indicate pagination
        page_text = await page.locator("text=/Page \\d+ of \\d+/").all_text_contents()
        print(f"\nPage text matching 'Page X of Y': {page_text}")
        
        # Check the rows per page selector
        rows_select = await page.query_selector("select, [role='listbox'], .MuiSelect-root")
        if rows_select:
            print(f"\nRows selector found")
        
        await browser.close()


if __name__ == "__main__":
    asyncio.run(test())
