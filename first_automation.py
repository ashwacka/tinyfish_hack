from dotenv import load_dotenv
load_dotenv()

from tinyfish import TinyFish

client = TinyFish()

with client.agent.stream(
    url="https://scrapeme.live/shop",
    goal="Extract the first 2 product names and prices. Return as JSON.",
) as stream:
    for event in stream:
        print(event)
    