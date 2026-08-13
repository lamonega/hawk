"""Test stealth against bot.sannysoft.com."""
import asyncio
import time
from hawk.mcp_server import server


async def main():
    # Launch browser with stealth
    r = await server.call_tool('browser_launch', {'headless': False})
    print(f"Launch: {r.structured_content.get('result', '')}")

    # Navigate to bot detection test
    r = await server.call_tool('browser_navigate', {'url': 'https://bot.sannysoft.com/'})
    print(f"Navigate: {r.structured_content.get('result', '')}")

    # Wait for page to load fully
    time.sleep(5)

    # Take screenshot
    r = await server.call_tool('browser_screenshot', {'filename': 'stealth_test.png'})
    print(f"Screenshot: {r}")

    # Close
    r = await server.call_tool('browser_close', {})
    print(f"Close: {r.structured_content.get('result', '')}")


if __name__ == "__main__":
    asyncio.run(main())
