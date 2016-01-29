import telepot
import telepot.namedtuple as nt
import collections
import re
import datetime
import pymongo
import functools as ft

#
# Checkin record to persist.
#
class Record(collections.namedtuple(
        'RecordBase',
        ['id', 'owner_id', 'owner_name', 'started_at', 'finished_at', 'planned_minutes',
         'topic', 'state'])):

    OPEN = 'open'
    CLOSED = 'closed'
    ABORTED = 'aborted'

    @classmethod
    def _minutes_from_command(cls, command):
        m = re.search("/ci(\\d+)", command)
        return int(m.group(1)) if m else None

    @classmethod
    def _minutes_from_args(cls, args):
        if len(args) < 2:
            return None
        try:
            return int(args[1])
        except ValueError:
            return None

    @classmethod
    def _topic_from_message(cls, message):
        if message.command == "/ci":
            if 3 <= len(message.args):
                return re.sub("/ci\\s+\\d+\\s+", '', message.text)
        elif 2 <= len(message.args):
            return re.sub("/ci\\d+\\s+", '', message.text)
        else:
            return None

    @classmethod
    def from_message(cls, message):
        minutes = cls._minutes_from_command(message.command)
        if not minutes:
            minutes = cls._minutes_from_args(message.args)
        topic = cls._topic_from_message(message)
        return Record(id=None,
                      owner_id=message.sender_id,
                      owner_name=message.sender_name,
                      started_at=datetime.datetime.utcnow(),
                      finished_at=None,
                      planned_minutes=minutes,
                      topic=topic,
                      state=cls.OPEN)

    def needs_resolution(self):
        return self.planned_minutes == None or self.topic == None

    def with_id(self, id):
        return self._replace(id=id)

    def with_topic(self, topic):
        return self._replace(topic=topic)

    def with_planned_minutes(self, minutes):
        if minutes <= 0:
            raise ValueError("Negative Number")
        return self._replace(planned_minutes=minutes)

    def with_closed(self):
        return self._replace(
            finished_at=datetime.datetime.utcnow(),
            state=self.CLOSED)

    def with_aborted(self):
        return self._replace(
            finished_at=datetime.datetime.utcnow(),
            state=self.ABORTED)

    @classmethod
    def from_dict(cls, d):
        # Has side effect here. Shouldn't we do this or don't we care?
        if d['_id']:
            d['id'] = d['_id']
            del d['_id']
        return Record(**d)

    def to_dict(self):
        # http://stackoverflow.com/questions/26180528/python-named-tuple-to-dictionary
        d = vars(super()) or super()._asdict()
        # Omit 'id' - This value comes from _id and we'll have it anyway.
        del d['id']
        return d

#
# Handling per-user, short-term chat continuation
#
class Conversation(object):
    def __init__(self, bot, store):
        self._bot = bot
        self._store = store

    def follow(self, update_message):
        raise Exception("Should never be called.")

    def needs_more(self):
        return False

#
# Checkin
#
class CheckinConversation(Conversation):
    TOPIC = 'topic'
    MINUTES = 'minutes'

    def __init__(self, bot, store, init_message):
        super().__init__(bot, store)
        self._asking = None
        self._record = Record.from_message(init_message)
        self._carry()


    def _finish(self):
        self._asking = None
        self._store.add_record(self._record)
        # XXX: Broadcast to the dojo channel as well.
        self._bot.declare_checkin(self._record)

    def _ask(self):
        if not self._record.topic:
            self._bot.ask_topic(self._record)
            self._asking = self.TOPIC
        elif not self._record.planned_minutes:
            self._bot.ask_minutes(self._record)
            self._asking = self.MINUTES

    def _handle(self, message):
        if self._asking == self.TOPIC and message.text:
            self._record = self._record.with_topic(message.text)
        elif self._asking == self.MINUTES and message.text:
            try:
                self._record = self._record.with_planned_minutes(int(message.text))
            except ValueError:
                self._bot.tell_error(self._record.owner_id, "Doesn't seem like a number :-(")
        else:
            self._bot.tell_error(self._record.owner_id, "Something wrong happened :-(")
            self._record = None

    def _carry(self):
        if self.needs_more():
            self._ask()
        else:
            self._finish()

    @property
    def key(self):
        return self._record.owner_id

    def follow(self, update_message):
        self._handle(update_message)
        self._carry()

    def needs_more(self):
        return self._record and self._record.needs_resolution()


class ClosingConversation(Conversation):
    def __init__(self, bot, store, init_message, closer):
        super().__init__(bot, store)
        rec = self._store.find_last_open_for(init_message.sender_id)
        if not rec:
            self._bot.tell_error(init_message.sender_id, "No ongoing checkin :-(")
            return
        closer(rec)

#
# Checkout
#
class CheckoutConversation(ClosingConversation):
    def __init__(self, bot, store, init_message):
        super().__init__(bot, store, init_message, self.close)

    def close(self, rec):
        self._store.update_record(rec.with_closed())
        self._bot.declare_checkout(rec)
        # XXX: Broadcast
        # XXX: Include stats

#
# Abort
#
class AbortConversation(ClosingConversation):
    def __init__(self, bot, store, init_message):
        super().__init__(bot, store, init_message, self.close)

    def close(self, rec):
        self._store.update_record(rec.with_aborted())
        self._bot.declare_abort(rec)
        # XXX: Broadcast
        # XXX: Include stats

#
# Mongo-backed Data Storage
#
class MongoStore(object):
    COL_RECORD = 'records'

    def __init__(self, url):
        self._client = pymongo.MongoClient(url)
        self._db = self._client.get_default_database()
        self._records = self._db[self.COL_RECORD]

    def print_description(self):
        print("DB Name: {}".format(self._db.name))

    # This is MongoStore specific, used from unit tests.
    def drop_all_collections(self):
        self._db.drop_collection(self.COL_RECORD)

    def add_record(self, rec):
        self._records.insert_one(rec.to_dict())

    def find_last_open_for(self, owner_id):
        cursor = self._records.find({ 'owner_id': owner_id, 'state': Record.OPEN })
        found = ft.reduce(lambda a,i: i, cursor, None)
        return Record.from_dict(found) if found else None

    def update_record(self, rec):
        self._records.update_one({"_id": rec.id }, { "$set": rec.to_dict() })

    def last_record(self):
        # XXX: Super inefficient. Use it only for testing.
        f = ft.reduce(lambda a,i: i, self._records.find(), None)
        return Record.from_dict(f)

    def record_count(self):
        # XXX: Super inefficient. Use it only for testing.
        return self._records.count()


#
# Wrapping message JSON dict
#
class Message(object):
    def __init__(self, data):
        self._data = data
        self._args = re.split("\\s+", self._data['text'])

    @property
    def args(self):
        return self._args

    @property
    def text(self):
        return self._data['text']

    @property
    def command(self):
        c = self._args[0]
        if c.startswith("/"):
            return c
        else:
            return None

    @property
    def sender_id(self):
        return self._data['from']['id']

    @property
    def sender_name(self):
        return self._data['from']['username'] or self._data['from']['firstname']

    @property
    def text(self):
        return self._data['text']


class DojoBot(telepot.Bot):
    def print_description(self):
        print("Bot:" + str(self.getMe()))

    def tell_error(self, chat_id, text):
        self.sendMessage(chat_id, text, reply_markup=nt.ReplyKeyboardHide())

    def declare_checkin(self, record):
        text = """
{} Checked in!
{}minutes for {}
""".format(record.owner_name, record.planned_minutes, record.topic).strip()
        self.sendMessage(record.owner_id, text, reply_markup=nt.ReplyKeyboardHide())

    def declare_checkout(self, record):
        text = """
{} Checked out from {} minute session!
""".format(record.owner_name, record.planned_minutes).strip()
        self.sendMessage(record.owner_id, text, reply_markup=nt.ReplyKeyboardHide())

    def declare_abort(self, record):
        text = """
{} Aborted the session :-(
""".format(record.owner_name, record.planned_minutes).strip()
        self.sendMessage(record.owner_id, text, reply_markup=nt.ReplyKeyboardHide())

    def ask_topic(self, record):
        text = "Whatcha gonna do?"
        self.sendMessage(record.owner_id, text, reply_markup=nt.ReplyKeyboardHide())

    def ask_minutes(self, record):
        text = "How long?"
        kb = [
            ["10", "15", "20"],
            ["30", "45", "60"],
            ["90", "120"]
        ]
        self.sendMessage(record.owner_id, text, reply_markup=nt.ReplyKeyboardMarkup(
            keyboard=kb))

#
# God class.
#
class DojoBotApp(object):
    def __init__(self, bot, store):
        self._bot = bot
        self._store = store
        self._conversations = {}

    def start(self):
        self._bot.notifyOnMessage(self._handle, run_forever=True)

    def _start_checkin(self, message):
        print("Got ci command")
        # XXX: Look for ongoing checkin. Ask close or abort if any.
        if not conv.needs_more():
            return None
        return conv

    def _start_command_conversation(self, message):
        # XXX: We probably need "/quit" to  clear the state.
        if message.command in ["/ci", "/ci15", "/ci30", "/ci60"]:
            print("Got checkin command")
            return CheckinConversation(self._bot, self._store, message)
        if message.command == "/co":
            print("Got checkout command")
            return CheckoutConversation(self._bot, self._store, message)
        if message.command == "/abort":
            print("Got abort command")
            return AbortConversation(self._bot, self._store, message)
        if message.command == "/cstat":
            print("Got cstat command")
            return None
        print("Got unknown command")
        return None

    def _handle(self, data):
        message = Message(data)
        conv = self._conversations.get(message.sender_id, None)
        if message.command:
            # XXX: Look for ongoing conversation. Quit it if any.
            next_conv = self._start_command_conversation(message)
            if not next_conv:
                self._bot.tell_error(message.sender_id, "Unknown command {} :-(".format(message.command))
            elif next_conv.needs_more():
                self._conversations[message.sender_id] = next_conv
            else:
                self._conversations[message.sender_id] = None
        else:
            if not conv:
                print("No ongoing conversation...")
                # XXX: Probably she wants to say something
                return
            print("Keep conversation...")
            conv.follow(message)
            if not conv.needs_more:
                self._conversations[message.sender_id] = None
