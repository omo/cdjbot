
import cdjbot as bot
import asyncio
import unittest
import unittest.mock as mock
import dockerip
import dateutil.parser as dp
import json
import time


def get_mock_coro(return_value=None):
    @asyncio.coroutine
    def mock_coro(*args, **kwargs):
        return return_value
    return mock.Mock(wraps=mock_coro)


class HelloTest(unittest.TestCase):
    def test_hello(self):
        self.assertTrue(True)

DOCKER_MONGO_URL=dockerip.get_docker_host_mongo_url("cdjbot-test")
USER_ID = 1234

def make_clean_mongo_store():
    store = bot.MongoStore(DOCKER_MONGO_URL)
    store.drop_all_collections()
    return store

def make_message_dict(text, user_id=USER_ID):
    return { 'from': { 'id': user_id, 'firstname': 'Alice', 'username': 'alice' }, 'text': text }

def make_mock_bot():
    b = mock.Mock(bot.DojoBot)
    b.sendMessage = get_mock_coro()
    b.declare_checkin = get_mock_coro()
    b.declare_checkout = get_mock_coro()
    b.declare_abort = get_mock_coro()
    b.ask_minutes = get_mock_coro()
    b.ack_quit = get_mock_coro()
    b.ask_topic = get_mock_coro()
    b.ask_topic_with_suggestions = get_mock_coro()
    b.tell_error = get_mock_coro()
    b.tell_stats = get_mock_coro()
    b.tell_where_you_are = get_mock_coro()
    return b


def make_message_with_text(text, **kwargs):
    return bot.Message(make_message_dict(text, **kwargs))

def make_record_with_text(text, **kwargs):
    msg = make_message_with_text(text, **kwargs)
    return bot.Record.from_message(msg)

MSG_JSON_WITH_CHAT = """
{
 "text": "/iamhere@foobot",
 "from": {"username": "foo", "first_name": "Hajime", "id": 5678, "last_name": "Morrita"},
 "date": 1454605481, "message_id": 34,
 "chat": {"title": "The Title", "type": "group", "id": -6789}
}
"""

def make_test_user(user_id=5678):
    return bot.User(
        {"username": "foo", "first_name": "Hajime", "id": user_id, "last_name": "Morrita"},
        {"title": "The Title", "type": "group", "id": -6789}
    )


def make_chat_aimhere_message():
    return bot.Message(json.loads(MSG_JSON_WITH_CHAT))


class MessageTest(unittest.TestCase):
    def test_command_fix_postfix(self):
        msg = make_message_with_text('/cmd@foobot')
        self.assertEqual(msg.command, '/cmd')

    def test_chat_id_title(self):
        msg = make_chat_aimhere_message()
        self.assertEqual(msg.chat_id, -6789)
        self.assertEqual(msg.chat_title, 'The Title')


class RecordTest(unittest.TestCase):
    def test_instantiate(self):
        record = bot.Record.from_message(make_message_with_text('/ci'))
        self.assertEqual(record.state, bot.Record.OPEN)
        self.assertTrue(record.planned_minutes == None)
        self.assertTrue(record.topic == None)

    def test_instantiate_with_minutes(self):
        record = bot.Record.from_message(make_message_with_text('/ci 30'))
        self.assertEqual(record.planned_minutes, 30)
        self.assertEqual(record.topic, None)

    def test_instantiate_with_minutes_and_topic(self):
        record = bot.Record.from_message(make_message_with_text('/ci 10 hello, world'))
        self.assertEqual(record.state, bot.Record.OPEN)
        self.assertEqual(record.planned_minutes, 10)
        self.assertEqual(record.topic, 'hello, world')

    def test_instantiate_with_something(self):
        record = bot.Record.from_message(make_message_with_text('/ci foo'))
        self.assertTrue(record.planned_minutes == None)

    def test_instantiate_ci15(self):
        record = bot.Record.from_message(make_message_with_text('/ci15'))
        self.assertEqual(record.planned_minutes, 15)
        self.assertEqual(record.topic, None)
        self.assertTrue(record.needs_resolution())

    def test_instantiate_ci15_with_topic(self):
        record = bot.Record.from_message(make_message_with_text('/ci15 hello, world'))
        self.assertEqual(record.planned_minutes, 15)
        self.assertEqual(record.topic, 'hello, world')
        self.assertFalse(record.needs_resolution())


class RecordStatsTest(unittest.TestCase):
    def test_format_weekly_monthly(self):
        text = bot.RecordStats.format_weekly_monthly(
            bot.RecordStats(30, 1, 1),
            bot.RecordStats(80, 3, 3),
        )
        self.assertTrue(0 < text.index('00:30'))
        self.assertTrue(0 < text.index('01:20'))

class ConversationTest(unittest.TestCase):
    def setUp(self):
        self._bot = make_mock_bot()
        self._store = make_clean_mongo_store()
        # http://stackoverflow.com/questions/23033939/how-to-test-python-3-4-asyncio-code
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)

    def tearDown(self):
        self.loop.close()

    def assert_record_added(self):
        self.assertEqual(self._store.record_count(), 1)

    def assert_record_not_added(self):
        self.assertEqual(self._store.record_count(), 0)

    def assert_asking_none(self, co):
        self.assertTrue(co._asking == None)

    def assert_asking_any(self, co):
        self.assertTrue(co._asking != None)

    def last_record(self):
        return self._store.last_record()

    def wait_for(self, future):
        return self.loop.run_until_complete(future)

class CheckinTest(ConversationTest):
    def test_no_more(self):
        co = self.wait_for(
            bot.CheckinConversation.start(
                self._bot, self._store, make_message_with_text('/ci15 hello, world')))
        self.assertEqual(1234, co.key)
        self.assertFalse(co.needs_more)
        self._bot.declare_checkin.assert_called_once_with(USER_ID, mock.ANY, mock.ANY)
        self.assert_record_added()

    def test_needs_topics(self):
        co = self.wait_for(
            bot.CheckinConversation.start(
                self._bot, self._store, make_message_with_text('/ci15')))
        self.assertTrue(co.needs_more)
        self.assert_record_not_added()
        self._bot.ask_topic.assert_called_once_with(mock.ANY)
        self.wait_for(co.follow(make_message_with_text("Topic")))

    def test_needs_topics_suggested(self):
        self._store.add_record(make_record_with_text('/ci15 LAST', user_id=USER_ID))
        self._store.add_record(make_record_with_text('/ci20 LAST', user_id=USER_ID))
        co = self.wait_for(
            bot.CheckinConversation.start(
                self._bot, self._store, make_message_with_text('/ci15')))
        self._bot.ask_topic_with_suggestions.assert_called_once_with(mock.ANY, ['LAST'])
        self.wait_for(co.follow(make_message_with_text("Topic")))

    def test_needs_topic_minutes(self):
        co = self.wait_for(
            bot.CheckinConversation.start(
                self._bot, self._store, make_message_with_text('/ci')))
        self._bot.ask_topic.assert_called_once_with(mock.ANY)
        self.assert_record_not_added()
        self.assert_asking_any(co)

        self.wait_for(co.follow(make_message_with_text('Topic')))
        self._bot.ask_minutes.assert_called_once_with(mock.ANY)
        self.assert_record_not_added()
        self.assert_asking_any(co)

        self.wait_for(co.follow(make_message_with_text('20')))
        self._bot.declare_checkin.assert_called_once_with(USER_ID, mock.ANY, mock.ANY)
        self.assert_asking_none(co)
        self.assert_record_added()
        self.assertEqual(20, self.last_record().planned_minutes)
        self.assertEqual('Topic', self.last_record().topic)

    def test_close_ongoing(self):
        co1 = self.wait_for(
            bot.CheckinConversation.start(
                self._bot, self._store, make_message_with_text('/ci15 hello, world')))
        co2 = self.wait_for(
            bot.CheckinConversation.start(
                self._bot, self._store, make_message_with_text('/ci30 hello, world')))
        self.assertEqual(self._store.record_stats(USER_ID).minutes, 15)

    def test_wrong_minutes(self):
        co = self.wait_for(
            bot.CheckinConversation.start(
                self._bot, self._store, make_message_with_text('/ci')))
        self.wait_for(co.follow(make_message_with_text('Topic')))
        self.wait_for(co.follow(make_message_with_text('NotANumber')))
        self._bot.tell_error.assert_called_once_with(USER_ID, mock.ANY)

    def test_finish_with_group(self):
        self._store.upsert_user(make_test_user(USER_ID))
        self.wait_for(bot.CheckinConversation.start(
            self._bot, self._store, make_message_with_text('/ci15 Hello')))
        self.assertEqual(self._bot.declare_checkin.call_count, 2)


class ClosingTest(ConversationTest):
    def add_checkin_record(self):
        record = bot.Record.from_message(make_message_with_text('/ci15 hello, world'))
        self._store.add_record(record)

    def test_checkout(self):
        self.add_checkin_record()
        co = self.wait_for(
            bot.CheckoutConversation.start(
                self._bot, self._store, make_message_with_text('/co')))
        self.assertFalse(co.needs_more)
        self.assertEqual(bot.Record.CLOSED, self.last_record().state)
        self._bot.declare_checkout.assert_called_once_with(mock.ANY)

    def test_abort(self):
        self.add_checkin_record()
        co = self.wait_for(
            bot.AbortConversation.start(self._bot, self._store, make_message_with_text('/co')))
        self.assertFalse(co.needs_more)
        self.assertEqual(bot.Record.ABORTED, self.last_record().state)
        self._bot.declare_abort.assert_called_once_with(mock.ANY)

    def test_error(self):
        co = self.wait_for(bot.CheckoutConversation.start(
            self._bot, self._store, make_message_with_text('/co')))
        self.assertFalse(co.needs_more)
        self._bot.tell_error.assert_called_once_with(USER_ID, mock.ANY)


class StatConversationTest(ConversationTest):
    def test_hello(self):
        self._store.add_record(make_record_with_text('/ci15 REC1', user_id=1).with_closed())
        co = self.wait_for(bot.StatConversation.start(
            self._bot, self._store, make_message_with_text('/cstat')))
        self.assertFalse(co.needs_more)
        self._bot.tell_stats.assert_called_once_with(USER_ID, mock.ANY)


class LocatingConversationTest(ConversationTest):
    def test_hello(self):
        co = self.wait_for(bot.LocatingConversation.start(
            self._bot, self._store, make_chat_aimhere_message()))
        self.assertFalse(co.needs_more)
        self._bot.tell_where_you_are.assert_called_once_with(5678, 'foo', -6789, 'The Title')

        u =  self._store.find_user(5678)
        self.assertEqual(u.username, 'foo')

    def test_message_with_no_group(self):
        co = self.wait_for(bot.LocatingConversation.start(
            self._bot, self._store, make_message_with_text('/iamhere')))
        self.assertFalse(co.needs_more)
        self._bot.tell_error.assert_called_once_with(USER_ID, mock.ANY)
        self.assertEqual(self._store.find_user(USER_ID), None)


class QuitConversationTest(ConversationTest):
    def test_hello(self):
        co = self.wait_for(bot.QuitConversation.start(
            self._bot, self._store, make_message_with_text('/q')))
        self.assertFalse(co.needs_more)
        self._bot.ack_quit.assert_called_once_with(USER_ID)


class MongoStoreTest(unittest.TestCase):
    def setUp(self):
        self._store = make_clean_mongo_store()

    def test_add_and_find(self):
        rec1a = bot.Record.from_message(make_message_with_text('/ci15 REC1', user_id=1))
        rec2a = bot.Record.from_message(make_message_with_text('/ci15 REC2', user_id=2))
        for r in [rec1a, rec2a]:
            self._store.add_record(r)
        open1a = self._store.find_last_open_for(1)
        self.assertEqual(open1a.topic, 'REC1')
        open2a = self._store.find_last_open_for(2)
        self.assertEqual(open2a.topic, 'REC2')

        self._store.update_record(open1a.with_closed())
        open1b = self._store.find_last_open_for(1)
        self.assertEqual(open1b, None)

    def test_record_stats(self):
        self._store.add_record(make_record_with_text('/ci15 REC1', user_id=1).with_closed())
        self._store.add_record(make_record_with_text('/ci30 REC2', user_id=1).with_closed())
        self._store.add_record(make_record_with_text('/ci60 REC3', user_id=1).with_aborted())
        self._store.add_record(make_record_with_text('/ci20 REC4', user_id=2).with_closed())
        agg =self._store.record_stats(1)
        self.assertEqual(agg.minutes, 45)
        self.assertEqual(agg.close_count, 2)
        self.assertEqual(agg.abort_count, 1)
        zero =self._store.record_stats(1, dp.parse('2100-01-01 00:00:00'))
        self.assertEqual(zero.minutes, 0)
        self.assertEqual(zero.close_count, 0)
        self.assertEqual(zero.abort_count, 0)

    def test_upsert_user(self):
        self._store.upsert_user(make_test_user())
        self.assertEqual(self._store._users.count(), 1)
        self._store.upsert_user(make_test_user())
        self.assertEqual(self._store._users.count(), 1)

    def test_find_recent_record_topics(self):
        self._store.add_record(make_record_with_text('/ci15 REC1', user_id=1))
        time.sleep(0.001)
        self._store.add_record(make_record_with_text('/ci30 REC2', user_id=1))
        time.sleep(0.001)
        self._store.add_record(make_record_with_text('/ci60 REC3', user_id=1))
        self._store.add_record(make_record_with_text('/ci60 REC3', user_id=1))
        topics = self._store.find_recent_record_topics(1, 3)
        self.assertEqual(sorted(topics), ["REC2", "REC3"])


class AppTest(unittest.TestCase):
    def setUp(self):
        self._bot = make_mock_bot()
        self._store = make_clean_mongo_store()
        # http://stackoverflow.com/questions/23033939/how-to-test-python-3-4-asyncio-code
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(None)

    def tearDown(self):
        self.loop.close()

    def wait_for(self, future):
        return self.loop.run_until_complete(future)

    def test_handle(self):
        app = bot.DojoBotApp(self._bot, self._store)
        self.wait_for(
            app._handle(make_message_dict('/ci15 hello, world')))

    def test_checkin_checkout(self):
        app = bot.DojoBotApp(self._bot, self._store)
        self.wait_for(
            app._handle(make_message_dict('/ci15 hello, world')))
        self.wait_for(
            app._handle(make_message_dict('/co')))


if __name__ == '__main__':
    unittest.main()
