from cardinal.decorators import event
from twisted.internet import reactor, task
import logging
import requests

def nick(user):
    return user.group(1)

def marketLink(itemID):
    return "http://www.torn.com/imarket.php#/p=shop&step=shop&type=&searchname={itemID}".format(
        itemID=itemID)

class TornNotifierPlugin(object):
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # Documents which notification classes belong to which text commands.
        # This should probably be a factory.
        self.notification_types = {
            "price_below": PriceBelowNotification,
            "price_above": PriceAboveNotification
        }
        # Contains notification storage for each user
        # This should probably be a factory, too.
        self.notification_storage = {}


    def _notify_types(self):
        return ', '.join(self.notification_types.keys())

    # Pauses notificatons for a nick
    def _pause(self, nick):
        if nick not in self.notification_storage:
            return
        ns = self.notification_storage[nick].all()
        for n in ns:
            n.stop()

    # Resumes notifications for a nick
    def _resume(self, nick):
        if nick not in self.notification_storage:
            return
        ns = self.notification_storage[nick].all()
        for n in ns:
            n.start()

    @event('irc.nick')
    def change_nick(self, cardinal, changer, new_nick):
        self.logger.debug("changer: {changer}, new_nick: {new_nick}".format(
            changer=changer, new_nick=new_nick))
        # self._pause(nick(changer))
        # self._resume(new_nick)

    @event('irc.part')
    def part_nick(self, cardinal, leaver, channel, msg):
        self._pause(nick(leaver))

    @event('irc.kick')
    def kick_nick(self, cardinal, kicker, channel, kicked, msg):
        self.logger.debug("kicker: {kicker}, kicked: {kicked}".format(
            kicker=kicker, kicked=kicked))
        # self._pause(kicked)

    @event('irc.quit')
    def quit_nick(self, cardinal, quitter, msg):
        self.logger.debug("{quitter} quit".format(quitter=quitter))
        self._pause(nick(quitter))

    # Adds a notification of the specified type
    def notify(self, cardinal, user, channel, msg):
        try:
            args = msg.split(' ')
            notify_type = args[1]
        except IndexError:
            cardinal.sendMsg(channel, "Syntax: .notify <notify_type> [arguments...]")
            return

        # Handle unrecognized notify_type
        if notify_type not in self.notification_types:
            cardinal.sendMsg(channel, "Recognized notify_types are {types}".format(
                types=self._notify_types()))
            return

        # Store notification in user's storage.
        try:
            notification = self.notification_types[notify_type](cardinal, channel, args)
        except (ValueError, IndexError):
            return

        user_nick = nick(user)
        if user_nick not in self.notification_storage:
            self.notification_storage[user_nick] = NotificationStorage()
        storage = self.notification_storage[user_nick]
        try:
            storage.store(notification)
        except ValueError:
            cardinal.sendMsg(channel,
                             'Notification of type {notify_type} and name {name} already exists.'.format(
                                 notify_type = notification.notify_type,
                                 name = notification.name))
            return
        notification.start()

    notify.commands = ['notify']
    notify.help = ["Notify of events using torn API",
                   "Syntax: .notify <notify_type>"]

    # Removes a notification with the given name
    def remove(self, cardinal, user, channel, msg):
        try:
            args = msg.split(' ')
            notify_type = args[1]
            notify_name = args[2]

        except IndexError:
            cardinal.sendMsg(channel, "Syntax: .remove <notify_type> <item_name>")
            return

        if notify_type not in self.notification_types:
            cardinal.sendMsg(channel, "Recognized notify_types are {types}".format(
                types=self._notify_types()))
            return

        user_nick = nick(user)
        if user_nick not in self.notification_storage:
            cardinal.sendMsg(channel, "You do not have any stored notifications!")
            return

        storage = self.notification_storage[user_nick]
        try:
            notification = storage.remove(notify_type, notify_name)
        except ValueError as e:
            cardinal.sendMsg(channel,
                             'Notification of type {notify_type} and name {name} does not exist.'.format(
                                 notify_type=notify_type, name=notify_name))
            return

        notification.stop()
        cardinal.sendMsg(channel, "Notification removed: [{notify_type} {name}]".format(
            notify_type=notify_type, name=notify_name))

    remove.commands = ['remove']
    remove.help = ["Remove an existing notification",
                   "Syntax: .remove <notify_type> <item_name>"]

    # Pauses notifications for a user
    def pause(self, cardinal, user, channel, msg):
        cardinal.sendMsg(channel, "Pausing notifications.")
        self._pause(nick(user))

    pause.commands = ['pause']
    pause.help = ["Pause a user's notifications",
                  "Syntax: .pause"]

    # Resumes notifications for a user
    def resume(self, cardinal, user, channel, msg):
        cardinal.sendMsg(channel, "Resuming notifications.")
        self._resume(nick(user))

    resume.commands = ['resume']
    resume.help = ["Resume a user's notifications",
                   "Syntax: .resume"]


    # Lists existing notifications for the user
    def show(self, cardinal, user, channel, msg):
        if nick(user) not in self.notification_storage:
            cardinal.sendMsg(channel, "You currently have zero notifications.")
            return
        notifications = self.notification_storage[nick(user)].all()
        for n in notifications:
            cardinal.sendMsg(channel, "[{n_type} {n_name}]: {desc}".format(
                n_type = n.notify_type, n_name = n.name, desc=str(n)))

    show.commands = ['list']
    show.help = ["List a user's notifications",
                 "Syntax: .list"]






class NotificationStorage:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._notifications = {}

    # Stores the notification. Throws an exception if a notification with the
    # same type and name is already stored.
    def store(self, notification):
        try:
            self.get(notification.notify_type, notification.name)
        except ValueError:
            # Notification with same notify_type and name is not stored.
            if notification.notify_type not in self._notifications:
                self._notifications[notification.notify_type] = {}
            self._notifications[notification.notify_type][notification.name] = notification
            return
        # Notification with same notify_type and name is stored.
        raise ValueError('Notification of type {notify_type} and name {name} already exists.'.format(
            notify_type=notification.notify_type, name=notification.name))


    # Removes a notification with the given type and name. If none exists,
    # throws an exception. Returns the removed notification.
    def remove(self, notify_type, name):
        n = self.get(notify_type, name)
        del self._notifications[notify_type][name]
        return n

    # Returns a stored notification with the given type and name. If none
    # exists, throws an exception.
    def get(self, notify_type, name):
        if name in self._notifications.get(notify_type, {}):
            return self._notifications[notify_type][name]
        raise ValueError('Notification of type {notify_type} and name {name} does not exist.'.format(
                notify_type=notify_type, name=name))

    def all(self):
        notifications = []
        for t in self._notifications:
            for n in self._notifications[t]:
                notifications.append(self._notifications[t][n])
        return notifications






class PriceBelowNotification:

    def __init__(self, cardinal, channel, args):
        self.syntax = "Syntax: .notify price_below <item_id>" \
                        " <item_name> <price> <poll_interval> <api_key>"
        self.notify_type = "price_below"
        self._cardinal = cardinal
        self._channel = channel
        try:
            self._item_id = int(args[2])
            self._item_name = args[3]
            self._min_price = int(args[4])
            self._interval = float(args[5])
            self._api_key = args[6]
            self.name = self._item_name
        except IndexError:
            cardinal.sendMsg(channel, self.syntax)
            raise IndexError
        except ValueError:
            cardinal.sendMsg(channel, self.syntax)
            raise ValueError

    def __str__(self):
        return "Notification in {channel} for {item_name} (ID {id}) price below {price}".format(
            channel=self._channel, item_name=self._item_name, id=self._item_id, price=self._min_price)

    def start(self):
        self._poller = StandardPoller('http://api.torn.com/market/{item_id}?selections=&key={api_key}'.format(
            item_id=self._item_id, api_key=self._api_key), self._interval)
        self._filter = LowPriceFilter(self._min_price, self._item_name, self._item_id,
                                      Notifier(self._cardinal, self._channel))
        self._cardinal.sendMsg(self._channel, "Notification started: [{notify_type} {name}]".format(
            name=self.name, notify_type=self.notify_type))
        self._poller.startPolling(self._filter)

    def stop(self):
        self._cardinal.sendMsg(self._channel, "Notification stopped: [{notify_type} {name}]".format(
            name=self.name, notify_type=self.notify_type))
        self._poller.stopPolling()

class PriceAboveNotification:

    def __init__(self, cardinal, channel, args):
        self.syntax = "Syntax: .notify price_above <item_id>" \
                        " <item_name> <price> <poll_interval> <api_key>"
        self.notify_type = "price_above"
        self._cardinal = cardinal
        self._channel = channel
        try:
            self._item_id = int(args[2])
            self._item_name = args[3]
            self._min_price = int(args[4])
            self._interval = float(args[5])
            self._api_key = args[6]
            self.name = self._item_name
        except IndexError:
            cardinal.sendMsg(channel, self.syntax)
            raise IndexError
        except ValueError:
            cardinal.sendMsg(channel, self.syntax)
            raise ValueError

    def __str__(self):
        return "Notification in {channel} for {item_name} (ID {id}) price above {price}".format(
            channel=self._channel, item_name=self._item_name, id=self._item_id, price=self._min_price)

    def start(self):
        self._poller = StandardPoller('http://api.torn.com/market/{item_id}?selections=&key={api_key}'.format(
            item_id=self._item_id, api_key=self._api_key), self._interval)
        self._filter = HighPriceFilter(self._min_price, self._item_name,
                                       Notifier(self._cardinal, self._channel))
        self._cardinal.sendMsg(self._channel, "Notification started: [{notify_type} {name}]".format(
            name=self.name, notify_type=self.notify_type))
        self._poller.startPolling(self._filter)

    def stop(self):
        self._cardinal.sendMsg(self._channel, "Notification stopped: [{notify_type} {name}]".format(
            name=self.name, notify_type=self.notify_type))
        self._poller.stopPolling()

class Notifier:
    def __init__(self, cardinal, channel):
        self._cardinal = cardinal
        self._channel = channel

    def consume(self, msg):
        self._cardinal.sendMsg(self._channel, msg)



class Poller:
    def __init__(self, url, interval):
        self.logger = logging.getLogger(__name__)
        self._url = url
        self._interval = interval

    def _call(self):
        raise NotImplementedError

    def _finish_success(self, result):
        self.logger.info("Finished polling {url}".format(url=self._url))

    def _finish_error(self, result):
        self.logger.error("Error polling {url}".format(url=self._url))
        self.logger.error("Traceback: {trace}".format(trace=result.getBriefTraceback()))

    def startPolling(self, consumer):
        self._consumer = consumer
        self._loop = task.LoopingCall(self._call)
        self._deferred = self._loop.start(self._interval*60)
        self.logger.info("Starting to poll {url}".format(url=self._url))
        self._deferred.addCallback(self._finish_success)
        self._deferred.addErrback(self._finish_error)

    def stopPolling(self):
        self._consumer = None
        self._loop.stop()

class ChangePoller(Poller):
    def _call(self):
        r = requests.get(self._url)
        if self._last_request is not None:
            self._consumer.consume(self._last_request, r)
        self._last_request = r

class StandardPoller(Poller):
    def _call(self):
        self._consumer.consume(requests.get(self._url))

class LowPriceFilter(object):
    def __init__(self, price, itemName, itemID, consumer):
        self.logger = logging.getLogger(__name__)
        self.price = price
        self.itemName = itemName
        self.itemID = itemID
        self._consumer = consumer


    def consume(self, response):
        price_list = response.json()['bazaar'].values()
        price_list.sort(key=lambda v: v['cost'])
        if price_list[0]['cost'] < self.price:
            self._consumer.consume("{itemName} is selling for {price}. Buy it from {market}.".format(
                itemName=self.itemName, price="{:,}".format(price_list[0]['cost']), market=marketLink(self.itemID)))
        return

class HighPriceFilter(object):
    def __init__(self, price, itemName, consumer):
        self.logger = logging.getLogger(__name__)
        self.price = price
        self.itemName = itemName
        self._consumer = consumer

    def _marketLink(self, itemID):
        return "http://www.torn.com/imarket.php#/p=shop&step=shop&type=&searchname={itemID}".format(
            itemID=itemID)

    def consume(self, response):
        price_list = response.json()['bazaar'].values()
        price_list.sort(key=lambda v: v['cost'])
        if price_list[0]['cost'] > self.price:
            self._consumer.consume("{itemName} is selling for {price}. Time to sell!".format(
                itemName=self.itemName, price="{:,}".format(price_list[0]['cost'])))
        return

def setup():
    return TornNotifierPlugin()
