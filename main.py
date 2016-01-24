import bot
import os

if __name__ == "__main__":
    tg_token = os.environ("CDJBOT_TELEGRAM_TOKEN")
    app = bot.DojoBotApp(bot.DojoBot(tg_token))
    app.start()
    print("Done.")
