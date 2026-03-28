from dotenv import load_dotenv
load_dotenv()

from tinyfish import ProxyCountryCode, TinyFish, BrowserProfile, ProxyConfig

client = TinyFish()

with client.agent.stream(
    url="https://www.carousell.sg/search/home%20baked/",
    goal="""
    If a 'verify you are human' or Cloudflare challenge page appears, wait for it to complete automatically before doing anything else.
    Close any popups. Scroll down to load listings.
    Extract the first 5 listings with:
    - title
    - price  
    - seller username
    - location
    - listing URL
    Return as JSON array.
    """,
    browser_profile=BrowserProfile.STEALTH,
    proxy_config=ProxyConfig(
    enabled=True,
    country_code=ProxyCountryCode.JP,
),
    on_streaming_url=lambda e: print(f"Watch: {e.streaming_url}"),
    on_progress=lambda e: print(f"> {e.purpose}"),
) as stream:
    for event in stream:
        if event.type == "COMPLETE":
            print(event.result_json)