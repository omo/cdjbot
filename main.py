import os, sys
import cdjbot
import asyncio

@asyncio.coroutine
def start(loop, tg_token, mongo_url):
    bot = cdjbot.DojoBot(tg_token)
    store = cdjbot.MongoStore(mongo_url)
    app = cdjbot.DojoBotApp(bot, store)
    yield from store.print_description()
    yield from bot.print_description()
    yield from app.run()

if __name__ == "__main__":
    tg_token = os.environ.get("CDJBOT_TELEGRAM_TOKEN")
    if None == tg_token or "INVALID" == tg_token:
        print("Error: Specify CDJBOT_TELEGRAM_TOKEN!")
        sys.exit(-1)
    mongo_url = os.environ.get("CDJBOT_MONGO_URL")
    if None == mongo_url or "INVALID" == mongo_url:
        print("Error: Specify CDJBOT_MONGO_URL!")
        sys.exit(-1)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(start(loop, tg_token, mongo_url))
    print("Done.")
