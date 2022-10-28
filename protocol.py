import asyncio
import csv
import datetime
import json
import logging
import os
import secrets
import sys
import time

import h11
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from models import User, Chat, Message, Comment, ChoiceType, ChatUser

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(stream=sys.stdout))

basedir = os.path.abspath(os.path.dirname(__file__))
engine = create_engine('sqlite:///' + os.path.join(basedir, 'data.sqlite'), echo=True)

ERROR_CODE_TO_MESSAGES = {
    401: 'Unauthorized. Please name yourself, add "user_name" to request body (not empty)'
         'and/or enter/check/recheck your Bearer Token in "Authorization" header. '
         'If you have not have token yet, get it by POST request to endpoint '
         '"get_token"',
    400: 'User with this name is already exists',
    404: 'Not found'
}

MESSAGES_FOR_USER = {
    'type': {
        'warning': {
            'had_token': 'You have already got token .',
            'no_data': 'no request body',
            'mo_message': 'Please, enter message'
        }
    }
}


class HTTPProtocol(asyncio.Protocol):
    def __init__(self):
        self.connection = h11.Connection(h11.SERVER)
        self.active_clients = {}

    def connection_made(self, transport):
        self.transport = transport
        logger.info('Start serving %s', transport.get_extra_info('peername'))

    def data_received(self, data):
        self.connection.receive_data(data)
        while True:
            event = self.connection.next_event()
            try:
                if isinstance(event, h11.Request):
                    self._request_processing(self.connection, event)
                elif (
                        isinstance(event, h11.ConnectionClosed)
                        or event is h11.NEED_DATA or event is h11.PAUSED
                ):
                    break
            except RuntimeError:
                logger.exception('exception in data_received')

        if self.connection.our_state is h11.DONE:  # TODO возможно понадобиться h11.MUST_CLOSE
            logger.info('Close connection %s', self.transport.get_extra_info('peername'))
            self.transport.close()

    def _request_processing(self, connection, request_event):
        if request_event.method not in [b'GET', b'POST']:
            logger.error('runtime_error')
            raise RuntimeError('unsupported method')
        while True:
            event = connection.next_event()
            if isinstance(event, h11.EndOfMessage):
                break
            try:
                assert isinstance(event, h11.Data)
            except AssertionError:
                logger.error('AssertionError')
                logger.exception('exception in sending response')
                break
            if request_event.method == b'POST':
                data = json.loads(event.data.decode('utf-8'))
                user_name = data.get('user_name', None)
                if not user_name:
                    self._send_error(401)
                elif request_event.target == b'/get-token':
                    self._send_token(user_name)
                elif request_event.target == b'/connect':
                    if self._check_auth(request_event, user_name):
                        chat_name = data.get('send_to', 'public_chat')
                        self._send_response_for_connect_endpoint(chat_name)
                elif request_event.target == b'/send':
                    if self._check_auth(request_event, user_name):
                        message = data.get('message', None)
                        if not message:
                            self._send_info(
                                MESSAGES_FOR_USER['type']['warning']['mo_message']
                            )
                        else:
                            chat_name = data.get('send_to', 'public_chat')
                            self._send_response_for_send_message(user_name, message, chat_name)

    def _check_auth(self, request_event, user_name):
        token = []
        for name, value in request_event.headers:
            if name == b'Authorization':
                decode_token = value.decode('utf-8')
                try:
                    token.append(decode_token.split()[1])
                except IndexError:
                    self._send_error(401)
                    return
        if not token:
            self._send_error(401)
            return
        with Session(engine) as session:
            user_obj = session.query(User).filter_by(user_name=user_name).first()
            if user_obj:
                return user_obj.token == token[0]
            self._send_error(401)

    def _send_response_with_OK_code(self, body: bytes, headers: list):
        response = h11.Response(status_code=200, headers=headers)
        self.send(response)
        self.send(h11.Data(data=body))
        self.send(h11.EndOfMessage())

    # def send_response_for_post(self, data_event, request_event):
    #     body = data_event.data
    #     d_body = body.decode('utf-8')
    #     print(json.loads(d_body))
    #     headers = self._get_headers_for_json_body(body)
    #     self._send_response_with_OK_code(body, headers)

    def send(self, event):
        data = self.connection.send(event)
        self.transport.write(data)

    @staticmethod
    def _get_public_massages(messages_number=20):
        temp_dict = {'massages': []}
        with Session(engine) as session:
            public_chat = session.query(Chat).filter(
                type=Chat.type.code == 'public'
            ).filter_by(
                name='public_chat'
            ).first()
            messages = session.query(Message).filter_by(chat=public_chat).limit(messages_number).all()
            for message in messages:
                temp_dict['massages'].append(
                    {
                        'datetime': message.pub_date,
                        'username': message.author,
                        'massage_text': message.text
                    }
                )
        # with open('datafiles/public_chat.csv') as file:
        #     temp_dict = {'massages': []}
        #     reader = csv.reader(file, delimiter=',')
        #     messages_number -= 1
        #     for ind, row in enumerate(reader):
        #         if ind == messages_number:
        #             break
        #         when, user_name, massage = row
        #         temp_dict['massages'].append(
        #             {
        #                 'datetime': when,
        #                 'username': user_name,
        #                 'massage': massage
        #             }
        #         )
        response_body_unicode = json.dumps(
            temp_dict, sort_keys=True, indent=4, separators=(',', ': ')
        )
        response_body_bytes = response_body_unicode.encode('utf-8')
        return response_body_bytes

     def _get_private_massages(self):
         pass # TODO ачать с этого

    def _send_response_for_connect_endpoint(self, chat_name):
        if not chat_name:
            body = self._get_public_massages()
        else:
            body = self._get_private_massages(user_name)
        headers = self._get_headers_for_json_body(body)
        self._send_response_with_OK_code(body, headers)

    def _send_response_for_send_message(self, user_name, message, send_to):
        with Session(engine) as session:
            user_obj = session.query(User).filter_by(user_name=user_name)
            if send_to == 'public_chat':
                public_chat = session.query(Chat).filter_by(name=send_to)
                self._add_message_to_DB(session, message, public_chat, user_obj)
            else:
                send_to_user_obj = session.query(User).filter_by(user_name=send_to).first()
                if not send_to_user_obj:
                    self._send_error(404)
                chat_obj = session.query(Chat).filter(
                    Chat.users.any(user_obj)
                ).filter(
                    Chat.users.any(send_to_user_obj)
                ).first()
                if not chat_obj:
                    new_chat = Chat(name=f'private-{int(time.time())}', type='private')
                    new_chat.users.append(send_to_user_obj)
                    new_chat.user_obj.append(user_obj)
                    self._add_message_to_DB(session, message, new_chat, user_obj)
                else:
                    self._add_message_to_DB(session, message, chat_obj, user_obj)

    @staticmethod
    def _add_message_to_DB(session, message_text, chat, user):
        message = Message(text=message_text, author=user, chat=chat)
        session.add(chat)
        session.add(message)
        session.commit()
        chat_user_obj = session.query(ChatUser).filter_by(
            chat_id=chat.id
        ).filter_by(
            user_id=user.id
        ).first()
        chat_user_obj.last_connect = datetime.datetime.now()
        session.commit()

    def _send_error(self, error_code):
        body = self._get_one_key_strbody('error', ERROR_CODE_TO_MESSAGES[error_code])
        headers = self._get_headers_for_json_body(body)
        response = h11.Response(status_code=error_code, headers=headers)
        self.send(response)
        self.send(h11.Data(data=body))
        self.send(h11.EndOfMessage())

    def _send_info(self, message):
        body = self._get_one_key_strbody('info', message)
        headers = self._get_headers_for_json_body(body)
        self._send_response_with_OK_code(body, headers)

    def _send_token(self, user_name):
        # users = []  # TODO добавить хранилище с пользователями
        # tokens = []  # TODO поставить в соответствие пользователям токены
        with Session(engine) as session:
            user = session.query(User).filter_by(user_name=user_name).first()
            if user:
                self._send_info(MESSAGES_FOR_USER['type']['warning']['had_token'])
            else:
                token = [secrets.token_hex(16)]
                while session.query(User).filter_by(token=token[0]).first():
                    token[0] = secrets.token_hex(16)
                new_user = User(
                    user_name=user_name,
                    token=token[0]
                )
                session.add(new_user)
                session.commit()
                body = self._get_one_key_strbody('token', token[0])
                headers = self._get_headers_for_json_body(body)
                self._send_response_with_OK_code(body, headers)

    @staticmethod
    def _get_one_key_strbody(key: str, value: str):
        return json.dumps(
            {
                key: value
            },
            sort_keys=True,
            indent=4,
            separators=(',', ': ')
        ).encode('utf-8')

    @staticmethod
    def _get_headers_for_json_body(body):
        return [
            ('content-type', 'application/json'),
            ('content-length', str(len(body))),
        ]


async def main(host, port):
    loop = asyncio.get_running_loop()
    server = await loop.create_server(HTTPProtocol, host, port)
    await server.serve_forever()


# with Session(engine) as session:
#     public_chat = Chat(
#         name='public_chat',
#         type='public'
#     )
#     session.add(public_chat)
#     session.commit()

asyncio.run(main('127.0.0.1', 5000))
