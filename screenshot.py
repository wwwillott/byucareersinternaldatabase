import asyncio
from playwright.async_api import async_playwright

async def capture():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 1000})
        await page.goto(
            'https://byucareersinternaldatabase.onrender.com',
            wait_until="networkidle"  # waits until network is quiet
        )
        await page.wait_for_selector(".week-box")  # waits for content to render
        await page.screenshot(path="example.png", full_page=True)
        await browser.close()

asyncio.run(capture())

