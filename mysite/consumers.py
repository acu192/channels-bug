from channels.generic.websocket import AsyncWebsocketConsumer

import json


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        room_name = self.scope['url_route']['kwargs']['room_name']
        self.group_name = f'channels_group_{room_name}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        event = {
            'type': 'chat_send',
            'text_data': json.dumps({'connect': self.channel_name}),
            'bytes_data': None,
            'sender_channel_name': self.channel_name,
        }
        await self.channel_layer.group_send(self.group_name, event)

    async def receive(self, text_data=None, bytes_data=None):
        print('GOT MESSAGE:', text_data)
        event = {
            'type': 'chat_send',
            'text_data': text_data,
            'bytes_data': bytes_data,
            'sender_channel_name': self.channel_name,
        }
        await self.channel_layer.group_send(self.group_name, event)

    async def chat_send(self, event):
        text_data = event['text_data']
        bytes_data = event['bytes_data']
        sender_channel_name = event['sender_channel_name']
        if sender_channel_name != self.channel_name:  # <-- We don't echo messages to the sender.
            await self.send(text_data=text_data, bytes_data=bytes_data)

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        event = {
            'type': 'chat_send',
            'text_data': json.dumps({'disconnect': self.channel_name}),
            'bytes_data': None,
            'sender_channel_name': self.channel_name,
        }
        await self.channel_layer.group_send(self.group_name, event)

