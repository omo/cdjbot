import telepot
import telepot.async
import telepot.namedtuple as nt
import collections
import re
import datetime
import pymongo
import functools as ft
import asyncio
import dateutil.parser as dp

class RecordStats(collections.namedtuple(
        'RecordStatsBase', ['minutes', 'close_count', 'abort_count'])):
    pass

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

    @property
    def needs_more(self):
        return False

#
# Checkin
#
class CheckinConversation(Conversation):
    TOPIC = 'topic'
    MINUTES = 'minutes'

    @classmethod
    @asyncio.coroutine
    def start(cls, bot, store, init_message):
        ongoing = store.find_last_open_for(init_message.sender_id)
        if ongoing:
            store.update_record(ongoing.with_closed())
        c = cls(bot, store, init_message)
        yield from c._carry()
        return c

    def __init__(self, bot, store, init_message):
        super().__init__(bot, store)

        self._asking = None
        self._record = Record.from_message(init_message)

    @asyncio.coroutine
    def _finish(self):
        self._asking = None
        self._store.add_record(self._record)
        # XXX: Broadcast to the dojo channel as well.
        yield from self._bot.declare_checkin(self._record)

    @asyncio.coroutine
    def _ask(self):
        if not self._record.topic:
            yield from self._bot.ask_topic(self._record)
            self._asking = self.TOPIC
        elif not self._record.planned_minutes:
            yield from self._bot.ask_minutes(self._record)
            self._asking = self.MINUTES

    @asyncio.coroutine
    def _handle(self, message):
        if self._asking == self.TOPIC and message.text:
            self._record = self._record.with_topic(message.text)
        elif self._asking == self.MINUTES and message.text:
            try:
                self._record = self._record.with_planned_minutes(int(message.text))
            except ValueError:
                yield from self._bot.tell_error(self._record.owner_id, "Doesn't seem like a number :-(")
        else:
            yield from self._bot.tell_error(self._record.owner_id, "Something wrong happened :-(")
            self._record = None

    @asyncio.coroutine
    def _carry(self):
        if self.needs_more:
            yield from self._ask()
        else:
            yield from self._finish()

    @property
    def key(self):
        return self._record.owner_id

    @asyncio.coroutine
    def follow(self, update_message):
        yield from self._handle(update_message)
        yield from self._carry()

    @property
    def needs_more(self):
        return self._record and self._record.needs_resolution()

class ClosingConversation(Conversation):
    @classmethod
    @asyncio.coroutine
    def start(cls, bot, store, init_message):
        c = cls(bot, store, init_message)
        rec = c._store.find_last_open_for(init_message.sender_id)
        if not rec:
            yield from c._bot.tell_error(init_message.sender_id, "No ongoing checkin :-(")
        else:
            yield from c._close(rec)
        return c


    def __init__(self, bot, store, init_message):
        super().__init__(bot, store)

#
# Checkout
#
class CheckoutConversation(ClosingConversation):
    @asyncio.coroutine
    def _close(self, rec):
        self._store.update_record(rec.with_closed())
        yield from self._bot.declare_checkout(rec)
        # XXX: Broadcast
        # XXX: Include stats

#
# Abort
#
class AbortConversation(ClosingConversation):
    @asyncio.coroutine
    def _close(self, rec):
        self._store.update_record(rec.with_aborted())
        yield from self._bot.declare_abort(rec)
        # XXX: Broadcast
        # XXX: Include stats

#
# Quick Statistics
#
class StatConversation(Conversation):
    @classmethod
    def beginning_of_this_week(cls):
        now = datetime.datetime.utcnow()
        return now - datetime.timedelta(days=now.weekday())

    @classmethod
    def beginning_of_this_month(cls):
        now = datetime.datetime.utcnow()
        return now - datetime.timedelta(days=now.day)

    @classmethod
    @asyncio.coroutine
    def start(cls, bot, store, init_message):
        c = cls(bot, store)
        owner = init_message.sender_id
        wstats = store.record_stats(owner, cls.beginning_of_this_week())
        mstats = store.record_stats(owner, cls.beginning_of_this_month())
        yield from bot.tell_stats(owner, cls.format_weekly_monthly(wstats, mstats))
        return c

    @classmethod
    def format_weekly_monthly(cls, wstats, mstats):
        return """
Weekly: {} CI, {} Minutes.
Monthly: {} CI, {} Minutes.
""".format(wstats.close_count, wstats.minutes,
           mstats.close_count, mstats.minutes).strip()


#
# Mongo-backed Data Storage
#
class MongoStore(object):
    COL_RECORD = 'records'
    BEGINNING = dp.parse('2000-01-01 00:00:00')

    def __init__(self, url):
        self._client = pymongo.MongoClient(url)
        self._db = self._client.get_default_database()
        self._records = self._db[self.COL_RECORD]

    @asyncio.coroutine
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

    def record_stats(self, owner_id, since=BEGINNING):
        closed_cond = { '$eq': [ '$state', Record.CLOSED ] }
        aborted_cond = { '$eq': [ '$state', Record.ABORTED ] }
        found = self._records.aggregate([
            { '$match': {
                'owner_id': owner_id,
                'started_at': { '$gt': since }
            } },
            { '$project': {
                '_id': 0,
                'minutes': { '$cond': { 'if': closed_cond, 'then': '$planned_minutes', 'else': 0 } },
                'close_count': { '$cond': { 'if': closed_cond, 'then': 1, 'else': 0 } },
                'abort_count': { '$cond': { 'if': aborted_cond, 'then': 1, 'else': 0 } },
            } },
            { '$group': {
                '_id': None,
                'minutes':  { '$sum' : '$minutes' },
                'close_count': { '$sum' : '$close_count' },
                'abort_count': { '$sum' : '$abort_count' }
            } }
        ])

        agg = [ f for f in found ]
        if not len(agg):
            return RecordStats(0, 0, 0)
        return RecordStats(agg[0]['minutes'], agg[0]['close_count'], agg[0]['abort_count'])

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


class DojoBot(telepot.async.Bot):
    @asyncio.coroutine
    def print_description(self):
        me =  yield from self.getMe()
        print("Bot:" + str(me))

    @asyncio.coroutine
    def tell_error(self, chat_id, text):
        return self.sendMessage(chat_id, text, reply_markup=nt.ReplyKeyboardHide())

    @asyncio.coroutine
    def tell_stats(self, chat_id, text):
        return self.sendMessage(chat_id, text, reply_markup=nt.ReplyKeyboardHide())

    def declare_checkin(self, record):
        text = """
{} Checked in!
{}minutes for {}
""".format(record.owner_name, record.planned_minutes, record.topic).strip()
        return self.sendMessage(record.owner_id, text, reply_markup=nt.ReplyKeyboardHide())

    def declare_checkout(self, record):
        text = """
{} Checked out from {} minute session!
""".format(record.owner_name, record.planned_minutes).strip()
        return self.sendMessage(record.owner_id, text, reply_markup=nt.ReplyKeyboardHide())

    def declare_abort(self, record):
        text = """
{} Aborted the session :-(
""".format(record.owner_name, record.planned_minutes).strip()
        return self.sendMessage(record.owner_id, text, reply_markup=nt.ReplyKeyboardHide())

    def ask_topic(self, record):
        text = "Whatcha gonna do?"
        return self.sendMessage(record.owner_id, text, reply_markup=nt.ReplyKeyboardHide())

    def ask_minutes(self, record):
        text = "How long?"
        kb = [
            ["10", "15", "20"],
            ["30", "45", "60"],
            ["90", "120"]
        ]
        return self.sendMessage(record.owner_id, text, reply_markup=nt.ReplyKeyboardMarkup(
            keyboard=kb))

#
# God class.
#
class DojoBotApp(object):
    def __init__(self, bot, store):
        self._bot = bot
        self._store = store
        self._conversations = {}

    @asyncio.coroutine
    def run(self):
        yield from self._bot.messageLoop(self._handle)

    @asyncio.coroutine
    def _start_command_conversation(self, message):
        # XXX: We probably need "/quit" to  clear the state.
        if message.command in ["/ci", "/ci15", "/ci30", "/ci60"]:
            print("Got checkin command")
            return CheckinConversation.start(self._bot, self._store, message)
        if message.command == "/co":
            print("Got checkout command")
            return CheckoutConversation.start(self._bot, self._store, message)
        if message.command == "/abort":
            print("Got abort command")
            return AbortConversation.start(self._bot, self._store, message)
        if message.command == "/cstat":
            print("Got cstat command")
            return StatConversation.start(self._bot, self._store, message)
        print("Got unknown command")
        return None

    @asyncio.coroutine
    def _handle(self, data):
        message = Message(data)
        if message.command:
            next_conv = yield from self._start_command_conversation(message)
            if not next_conv:
                yield from self._bot.tell_error(
                    message.sender_id,
                    "Unknown command {} :-(".format(message.command))
            elif next_conv.needs_more:
                self._conversations[message.sender_id] = next_conv
            else:
                self._conversations[message.sender_id] = None
        else:
            conv = self._conversations.get(message.sender_id, None)
            if not conv:
                print("No ongoing conversation...")
                # XXX: Probably she wants to say something
                return
            print("Keep conversation...")
            yield from conv.follow(message)
            if not conv.needs_more:
                self._conversations[message.sender_id] = None
