import asyncio
import aioredis

import sys
import uuid
import msgpack
import traceback


class RedisPubSubChannelLayer:
    """
    Channel Layer that uses Redis's pub/sub functionality.
    """

    def __init__(self, host, prefix):
        self.host = host
        self.prefix = prefix
        self._lock = None
        self._pub_conn = None   # connection to Redis used for publishing messages
        self._sub_conn = None   # connection to Redis used for subscriptions
        self._receiver = None
        self._receive_task = None
        self._keepalive_task = None
        self.channels = {}   # the set of specific channels that currently exist in this process; maps `channel_name` to a queue of messages for that channel
        self.groups = {}     # the groups which we listen to; maps `group_name` to set of channels who are subscribed to that group

    extensions = ["groups"]

    async def get_pub_conn(self):
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._pub_conn is not None and self._pub_conn.closed:
                self._pub_conn = None
            if self._pub_conn is None:
                self._pub_conn = await aioredis.create_redis(self.host)
            return self._pub_conn

    async def get_sub_conn(self):
        if self._keepalive_task is None:
            self._keepalive_task = asyncio.create_task(self._do_keepalive())
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._sub_conn is not None and self._sub_conn.closed:
                self._sub_conn = None
            if self._sub_conn is None:
                if self._receive_task is not None:
                    self._receive_task.cancel()
                    try:
                        await self._receive_task
                    except asyncio.CancelledError:
                        pass
                    except:
                        traceback.print_exc(file=sys.stderr)
                        # Don't re-raise here. We don't care that much why _receive_task didn't end cleanly.
                    self._receive_task = None
                self._sub_conn = await aioredis.create_redis(self.host)
                self._receiver = aioredis.pubsub.Receiver(on_close=on_close_noop)
                self._receive_task = asyncio.create_task(self._do_receiving())
                # Do our best to recover from a disconnect/reconnect to Redis by re-subscribing to the channels/groups:
                all_channels_and_groups = list(self.channels.keys()) + list(self.groups.keys())
                if all_channels_and_groups:
                    all_channels_and_groups = [self._receiver.channel(name) for name in all_channels_and_groups]
                    await self._sub_conn.subscribe(*all_channels_and_groups)
            return self._sub_conn

    async def _do_receiving(self):
        async for ch, message in self._receiver.iter():
            name = ch.name
            if isinstance(name, bytes):
                name = name.decode()   # reversing what happens here: https://github.com/aio-libs/aioredis-py/blob/8a207609b7f8a33e74c7c8130d97186e78cc0052/aioredis/util.py#L17
            if name in self.channels:
                self.channels[name].put_nowait(message)
            elif name in self.groups:
                for channel_name in self.groups[name]:
                    if channel_name in self.channels:
                        self.channels[channel_name].put_nowait(message)

    async def _do_keepalive(self):
        """
        This task's simple job is just to call `self.get_sub_conn()` periodically.

        Why? Well, calling `self.get_sub_conn()` has the nice side-affect that if
        that connection has died (because Redis was restarted, or there was a networking
        hiccup, for example), then calling `self.get_sub_conn()` will reconnect and
        restore our old subscriptions. Thus, we want to do this on a predictable schedule.
        This is kinda a sub-optimal way to achieve this, but I can't find a way in aioredis
        to get a notification when the connection dies.

        Note you wouldn't need this if you were *sure* that there would be a lot of subscribe/
        unsubscribe events on your site, because such events each call `self.get_sub_conn()`.
        Thus, on a site with heavy traffic this task may not be necessary, but also maybe it is.
        Why? Well, in a heavy traffic site you probably have more than one Django server replicas,
        so it might be the case that one of your replicas is under-utilized and this periodic
        connection check will be beneficial in the same way as it is for a low-traffic site.
        """
        while True:
            await asyncio.sleep(1)
            try:
                await self.get_sub_conn()
            except:
                traceback.print_exc(file=sys.stderr)

    # Channel layer API

    async def send(self, channel, message):
        """
        Send a message onto a (general or specific) channel.
        """
        conn = await self.get_pub_conn()
        await conn.publish(channel, msgpack.packb(message))

    async def receive(self, channel):
        """
        Receive the first message that arrives on the channel.
        If more than one coroutine waits on the same channel, a random one
        of the waiting coroutines will get the result.
        """
        if channel not in self.channels:
            raise RuntimeError(
                'You should only call receive() on channels that you "own" and that were created with `new_channel()`.'
            )

        q = self.channels[channel]

        try:
            message = await q.get()
        except asyncio.CancelledError:
            # We are cancelled. It's possible we are *not the only* task that is cancelled
            # that is waiting on this channel, in which case only *one* task should do the
            # following clean-up. The following 'if-then-del' ensures only one task does
            # the clean-up.
            # NOTE: We assume here that the reason we are cancelled is because the consumer
            #       is exiting, which is why we unsubscribe below. Indeed, currently the way
            #       that Django channels works, this is a safe assumption.
            if channel in self.channels:
                del self.channels[channel]
                try:
                    conn = await self.get_sub_conn()
                    await conn.unsubscribe(channel)
                except:
                    traceback.print_exc(file=sys.stderr)
                    # We don't re-raise here because we want to the CancelledError to be the one re-raised below.
            raise

        return msgpack.unpackb(message)

    async def new_channel(self, prefix="specific."):
        """
        Returns a new channel name that can be used by something in our
        process as a specific channel.
        """
        channel = f'{self.prefix}{prefix}{uuid.uuid4().hex}'
        conn = await self.get_sub_conn()
        self.channels[channel] = asyncio.Queue()
        await conn.subscribe(self._receiver.channel(channel))
        return channel

    # Groups extension

    async def group_add(self, group, channel):
        """
        Adds the channel name to a group.
        """
        group_channel = f'{self.prefix}__group__{group}'
        conn = await self.get_sub_conn()
        new = False
        if group_channel not in self.groups:
            self.groups[group_channel] = set()
            new = True
        group_channels = self.groups[group_channel]
        if channel not in group_channels:
            group_channels.add(channel)
        if new:
            await conn.subscribe(self._receiver.channel(group_channel))

    async def group_discard(self, group, channel):
        group_channel = f'{self.prefix}__group__{group}'
        conn = await self.get_sub_conn()
        assert group_channel in self.groups
        group_channels = self.groups[group_channel]
        assert channel in group_channels
        group_channels.remove(channel)
        if len(group_channels) == 0:
            del self.groups[group_channel]
            await conn.unsubscribe(group_channel)

    async def group_send(self, group, message):
        group_channel = f'{self.prefix}__group__{group}'
        conn = await self.get_pub_conn()
        await conn.publish(group_channel, msgpack.packb(message))


def on_close_noop(sender, exc=None):
    """
    If you don't pass an `on_close` function to the `Receiver`, then it
    defaults to one that closes the Receiver whenever the last subscriber
    unsubscribes. This isn't what we want; instead, we want the Receiver
    to continue even if no one is subscribed, because soon someone will
    subscribe and we want things to continue from there. Passing this
    empty function solves it.
    """
    pass

