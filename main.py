import cdjbot
import os, sys

if __name__ == "__main__":
    tg_token = os.environ.get("CDJBOT_TELEGRAM_TOKEN")
    if None == tg_token or "INVALID" == tg_token:
        print("Error: Specify CDJBOT_TELEGRAM_TOKEN!")
        sys.exit(-1)
    bot = cdjbot.DojoBot(tg_token)
    app = cdjbot.DojoBotApp(bot)
    app.start()
    print("Done.")
