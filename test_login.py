"""Test script: launch browser, navigate to LinkedIn login, wait for human."""
import asyncio
import time
from hawk.mcp_server import server


async def main():
    # Launch browser
    r = await server.call_tool('browser_launch', {'headless': False})
    print(f"Launch: {r.structured_content.get('result', '')}")

    # Navigate to LinkedIn login
    r = await server.call_tool('browser_navigate', {'url': 'https://www.linkedin.com/login'})
    print(f"Navigate: {r.structured_content.get('result', '')}")

    print("\n>>> LOG IN TO LINKEDIN IN THE BROWSER WINDOW <<<")
    print(">>> Waiting 120 seconds... <<<")
    
    # Wait for user to log in
    for i in range(120, 0, -1):
        print(f"\r>>> {i}s remaining... <<<", end="", flush=True)
        time.sleep(1)
    
    print("\n")

    # Check session
    r = await server.call_tool('browser_check_session', {})
    print(f"Session: {r.structured_content.get('result', '')}")

    # Check profile
    r = await server.call_tool('hawk_check_profile', {})
    print(f"Profile: {r.structured_content.get('result', '')[:300]}")

    # Close
    r = await server.call_tool('browser_close', {})
    print(f"Close: {r.structured_content.get('result', '')}")


if __name__ == "__main__":
    asyncio.run(main())
