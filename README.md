# Channels Issue [#1683](https://github.com/django/channels/issues/1683)

### What is this?

It's a small (as minimal as I can make it) repository to demonstrate a bug in Django Channels where messages are rarely (but reproducibly!) **dropped from active connections** when passed through Channels with the Redis channel layer (via the `group_send()` method).

### But did you set the channel capacity high enough?

Yes, it's set at 1,000. That should be high enough. You'll see in the demo below, we are creating ~7 clients and each client sends 10 messages per second. Thus, if everything gets clogged-up, it would take a solid 14 seconds to fill the 1,000 message capacity. When you run it, you'll see things flow smoothly and we aren't getting clogged up at all. This is not a hard task at this message rate.

### What system are you running on?

Linux, Python 3.7, and [this requirements.txt](requirements.txt).

### Is it a problem with the ASGI server or a reverse proxy in the middle?

No, there is no reverse proxy in this case. Also, the ASGI server is not the issue: You can see the bug surface when using either Daphne or Uvicorn.

### How to run?

If you like Docker and don't have a localhost Redis server, do this:

```
make docker_build
make docker_run
```

If you want to run without Docker, and if you have a localhost Redis server already, do this:

```
pip3 install requirements.txt
make run
 # or
make run_uvicorn
```

### How to produce the bug?

The section above just shows you how to run the server. Next we will run ~7 clients to send a bunch of messages through the server.

Here is how each client works: You start the client and specify the "room name" on the command line (you'll see this soon). That client connects to that "room" (like, a chat room sort of). The client then sends 10 messages per second to the server. If you have just one client, it's not interesting because this is a chat-room-sort-of-thing, as you know. So start another client, and be sure you set the same "room name" for it. Now you'll see the clients receive each other's messages (and those messages are printed to the terminal by each client).

How do we know messages are dropped? Each client generates its own UUID and sends messages with a "count" field which begins at zero and increments by one on each message. Thus a client knows if a message is dropped if it receives a gap in the count for one of its peers. Note: There is no auto-reconnect, so the only way to see a gap is if the server drops a message.

How many clients should you start? I do 7 ... where 3 are in the same room ("room_a") and 4 are in a different room ("room_b"). That allows me to reproduce the error in a few minutes. You'll see a client print out a message like "ERROR: SERVER DROPPED A MESSAGE!" and it will exit.

The bug seems to happen only if you have at least one client connect-disconnect-reconnect in a loop. Again, the issue isn't that messages are dropped when a client disconnects; rather, we see a **gap** in the messages that are received by other clients.

Also, the bug does *not* seem to surface if you have only *two* clients (one persistent and one that connect-disconnect-reconnects in a loop). Maybe it would if I waited longer, but I haven't seen it in this case. I have seen it with *three* clients in a room though.

Okay, finally, how to run clients? Like this (if you want to do the 7 clients that I recommended above). Use a bunch of terminal windows. Notice the last client in each room will do the connect-disconnect-reconnect thing:

```
python tester.py room_a
python tester.py room_a
while :; do timeout 1 python tester.py room_a; done

python tester.py room_b
python tester.py room_b
python tester.py room_b
while :; do timeout 1 python tester.py room_b; done
```

### Observations

1. You will often see clients error out at the same time (even clients that are in different groups!). This suggests the issue somehow spans across groups... a larger hiccup in the channel layer.

2. I cannot reproduce the bug unless there are clients that connect-disconnect-reconnect in a loop. Before anyone says "oh, well of course messages are lost when a client disconnects". Yes, but no. I'm looking here at gaps in the sequence number of messages that **are delivered** to the peers. If there is a gap, there must have been a message dropped by the server, which is what happens in this case. Why do you need clients that connect-disconnect-reconnect in a loop? I don't know, but for some reason that is what it takes for gaps to appear in the sequence numbers. More specifically: I've narrowed it down to it happens when a client **disconnects**. And as indicated in #1, it can cause *different* groups to drop a message as well (i.e. a client disconnecting can affect groups that it doesn't even belong to!)

3. (corollary of #2 above) I thought for a while maybe it was due to the connection to Redis that were being "refreshed" or something, that is, I though maybe there were momentary times that Redis was disconnected from Channels. But... my observation in #2 is that this issue **does not happen** when you have a set of stable clients connected (I've run it for hours like this, no issue), whereas if you have even *one* client that does the connect-disconnect-reconnect loop, then you see the bug occur in a matter of minutes. Unless, does a client disconnecting cause the underlying Redis connection to reset, or something like that?

4. I cannot reproduce it when using `InMemoryChannelLayer`... at all, no matter what I try, _suggesting_ (but not _proving_) that the issue is with the [Redis Channel Layer](https://github.com/django/channels_redis/).

