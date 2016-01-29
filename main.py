import os, sys
import cdjbot

if __name__ == "__main__":
    tg_token = os.environ.get("CDJBOT_TELEGRAM_TOKEN")
    if None == tg_token or "INVALID" == tg_token:
        print("Error: Specify CDJBOT_TELEGRAM_TOKEN!")
        sys.exit(-1)
    mongo_url = os.environ.get("CDJBOT_MONGO_URL")
    if None == mongo_url or "INVALID" == mongo_url:
        print("Error: Specify CDJBOT_MONGO_URL!")
        sys.exit(-1)

    bot = cdjbot.DojoBot(tg_token)
    store = cdjbot.MongoStore(mongo_url)
    bot.print_description()
    store.print_description()
    app = cdjbot.DojoBotApp(bot, store)
    app.start()
    print("Done.")
