
import cdjbot as bot
import unittest
import unittest.mock as mock
import dockerip

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


def make_message_with_text(text, **kwargs):
    return bot.Message(make_message_dict(text, **kwargs))


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


class ConversationTest(unittest.TestCase):
    def setUp(self):
        self._bot = mock.Mock()
        self._store = make_clean_mongo_store()

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


class CheckinTest(ConversationTest):
    def test_no_more(self):
        co = bot.CheckinConversation(
            self._bot, self._store, make_message_with_text('/ci15 hello, world'))
        self.assertEqual(1234, co.key)
        self.assertFalse(co.needs_more())
        self._bot.declare_checkin.assert_called_once_with(mock.ANY)
        self.assert_record_added()

    def test_needs_topics(self):
        co = bot.CheckinConversation(
            self._bot, self._store, make_message_with_text('/ci15'))
        self.assertTrue(co.needs_more())
        self.assert_record_not_added()
        self._bot.ask_topic.assert_called_once_with(mock.ANY)
        # Check state
        co.follow(make_message_with_text("Topic"))

    def test_needs_topic_minutes(self):
        co = bot.CheckinConversation(
            self._bot, self._store, make_message_with_text('/ci'))
        self._bot.ask_topic.assert_called_once_with(mock.ANY)
        self.assert_record_not_added()
        self.assert_asking_any(co)

        co.follow(make_message_with_text('Topic'))
        self._bot.ask_minutes.assert_called_once_with(mock.ANY)
        self.assert_record_not_added()
        self.assert_asking_any(co)

        co.follow(make_message_with_text('20'))
        self._bot.declare_checkin.assert_called_once_with(mock.ANY)
        self.assert_asking_none(co)
        self.assert_record_added()
        self.assertEqual(20, self.last_record().planned_minutes)
        self.assertEqual('Topic', self.last_record().topic)

    def test_wrong_minutes(self):
        co = bot.CheckinConversation(
            self._bot, self._store, make_message_with_text('/ci'))
        co.follow(make_message_with_text('Topic'))
        co.follow(make_message_with_text('NotANumber'))
        self._bot.tell_error.assert_called_once_with(USER_ID, mock.ANY)


class ClosingTest(ConversationTest):
    def add_checkin_record(self):
        record = bot.Record.from_message(make_message_with_text('/ci15 hello, world'))
        self._store.add_record(record)

    def test_checkout(self):
        self.add_checkin_record()
        co = bot.CheckoutConversation(
            self._bot, self._store, make_message_with_text('/co'))
        self.assertFalse(co.needs_more())
        self.assertEqual(bot.Record.CLOSED, self.last_record().state)
        self._bot.declare_checkout.assert_called_once_with(mock.ANY)

    def test_abort(self):
        self.add_checkin_record()
        co = bot.AbortConversation(
            self._bot, self._store, make_message_with_text('/co'))
        self.assertFalse(co.needs_more())
        self.assertEqual(bot.Record.ABORTED, self.last_record().state)
        self._bot.declare_abort.assert_called_once_with(mock.ANY)

    def test_error(self):
        co = bot.CheckoutConversation(
            self._bot, self._store, make_message_with_text('/co'))
        self.assertFalse(co.needs_more())
        self._bot.tell_error.assert_called_once_with(USER_ID, mock.ANY)


class StoreTestMixin(object):
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


class MongoStoreTest(unittest.TestCase, StoreTestMixin):
    def setUp(self):
        self._store = make_clean_mongo_store()


class AppTest(unittest.TestCase):
    def setUp(self):
        self._bot = mock.Mock()
        self._store = make_clean_mongo_store()

    def test_handle(self):
        app = bot.DojoBotApp(self._bot, self._store)
        app._handle(make_message_dict('/ci15 hello, world'))

    def test_checkin_checkout(self):
        app = bot.DojoBotApp(self._bot, self._store)
        app._handle(make_message_dict('/ci15 hello, world'))
        app._handle(make_message_dict('/co'))


if __name__ == '__main__':
    unittest.main()
