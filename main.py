import cdjbot
import os

if __name__ == "__main__":
    tg_token = os.environ.get("CDJBOT_TELEGRAM_TOKEN")
    bot = cdjbot.DojoBot(tg_token)
    app = cdjbot.DojoBotApp(bot)
    app.start()
    print("Done.")
