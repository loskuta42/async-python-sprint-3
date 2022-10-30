import asyncio
import datetime
import json
import logging
import os
import secrets
import sys
import time

import h11
from sqlalchemy import create_engine, desc
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
    400: 'BAD REQUEST',
    404: 'Not found message/user_name/chat',
    405: 'Not allowed http method'
}

MESSAGES_FOR_USER = {
    'type': {
        'warning': {
            'had_token': 'You have already got token .',
            'no_data': 'no request body',
            'mo_message': 'Please, enter message',
            'mo_message_id': 'Please, enter message id for comment',
            'no_comment': 'Please, enter comment'
        }
    }
}


class HTTPProtocol(asyncio.Protocol):
    def __init__(self):
        self.connection = h11.Connection(h11.SERVER)

    def connection_made(self, transport):
        self._transport = transport
        logger.info('Start serving %s', transport.get_extra_info('peername'))

    def _deliver_events(self):
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
                self._send_error(405)
            if self.connection.our_state is h11.MUST_CLOSE:
                logger.info('Close connection %s', self._transport.get_extra_info('peername'))
                self._transport.close()
                break

    def data_received(self, data):
        self.connection.receive_data(data)
        self._deliver_events()

        if self.connection.our_state is h11.DONE:
            self.connection.start_next_cycle()
            self._deliver_events()

    def _request_processing(self, connection, request_event):
        if request_event.method not in [b'GET', b'POST']:
            logger.error('unsupported HTTP method')
            raise RuntimeError('unsupported method')
        while True:
            time.sleep(0.1)
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
                if request_event.target == b'/get-token':
                    user_name = data.get('user_name', None)
                    if not user_name:
                        self._send_error(401)
                    else:
                        self._send_token(user_name)
                elif request_event.target == b'/connect':
                    if user_obj := self._check_auth(request_event):
                        chat_with = data.get('chat_with', 'public_chat')
                        messages_number = data.get('messages_number', 20)
                        self._send_response_for_connect_endpoint(
                            user_obj,
                            chat_with,
                            messages_number

                        )
                    else:
                        self._send_error(401)
                elif request_event.target == b'/send':
                    if user_obj := self._check_auth(request_event):
                        message = data.get('message', None)
                        if not message:
                            self._send_error(400)
                        else:
                            chat_name = data.get('send_to', 'public_chat')
                            self._send_response_for_send_message(user_obj, message, chat_name)
                elif request_event.target == b'/comment':
                    if user_obj := self._check_auth(request_event):
                        message_id = data.get('message_id')
                        comment = data.get('comment')
                        if not message_id or not comment:
                            self._send_error(400)
                        else:
                            self._send_response_for_comment(message_id, comment, user_obj)
                elif request_event.target == b'/report':
                    if user_obj := self._check_auth(request_event):
                        report_on = data.get('report_on')
                        chat_type = data.get('chat_type')
                        if not report_on or not chat_type:
                            self._send_error(400)
                        else:
                            self._send_response_for_report(user_obj, chat_type, report_on)
            else:
                if request_event.target == b'/status':
                    if user_obj := self._check_auth(request_event):
                        self._send_response_status_endpoint(user_obj)

    def _send_response_status_endpoint(self, user):
        with Session(engine) as session:
            user_obj = session.query(User).filter_by(user_name=user.user_name).first()
            result = {
                'connected_as': user_obj.user_name,
                'chats': []
            }
            chats = user_obj.chats
            for chat in chats:
                result['chats'].append(
                    {
                        'name': chat.name
                        if chat.type == 'public'
                        else chat.users[0].user_name
                        if chat.users[0].user_name != user_obj.user_name
                        else chat.users[1].user_name,
                        'chat_type': str(chat.type),
                        'created': chat.created.strftime('%d.%m.%Y, %H:%M:%S'),
                        'messages_number': chat.messages.count(),
                        'users_number': chat.users.count()
                    }
                )
            body = self._get_encode_body_from_data(result)
            headers = self._get_headers_for_json_body(body)
            self._send_response_with_ok_code(body, headers)

    def _check_auth(self, request_event):
        token = []
        for name, value in request_event.headers:
            if name.lower() == b'authorization':
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
            if user_obj := session.query(User).filter_by(token=token[0]).first():
                return user_obj
        self._send_error(401)

    def _send_response_with_ok_code(self, body: bytes, headers: list):
        response = h11.Response(status_code=200, headers=headers)
        self.send(response)
        self.send(h11.Data(data=body))
        self.send(h11.EndOfMessage())

    def send(self, event):
        data = self.connection.send(event)
        self._transport.write(data)

    def _messages_from_chat_to_body(self, session, user_caller, chat, messages_number):
        chat_user_obj = session.query(ChatUser).filter_by(
            chat_id=chat.id
        ).filter_by(
            user_id=user_caller.id
        ).first()
        last_connect = chat_user_obj.last_connect
        if not last_connect:
            last_connect = chat.created
        temp_dict = {
            'messages': [],
            'unread_messages': []
        }
        last_messages = session.query(Message).filter(
            Message.chat == chat,
            Message.pub_date < last_connect
        ).order_by(
            desc(Message.pub_date)
        ).limit(
            messages_number
        ).all()
        unread_messages = session.query(Message).filter(Message.chat == chat, Message.pub_date > last_connect).all()
        for message in last_messages:
            temp_dict['messages'].append(
                {
                    'id': message.id,
                    'pub_date': message.pub_date.strftime('%d.%m.%Y, %H:%M:%S'),
                    'author': message.author.user_name,
                    'message_text': message.text,
                    'message_comments': str(message.comments)
                }
            )
        for message in unread_messages:
            temp_dict['unread_messages'].append(
                {
                    'id': message.id,
                    'pub_date': message.pub_date.strftime('%d.%m.%Y, %H:%M:%S'),
                    'author': message.author.user_name,
                    'message_text': message.text,
                    'message_comments': str(message.comments)
                }
            )
        chat_user_obj.last_connect = datetime.datetime.now()
        session.commit()
        return self._get_encode_body_from_data(temp_dict)

    def _get_public_messages(self, session, user_caller, messages_number):
        public_chat = session.query(Chat).filter(
            Chat.type == 'public'
        ).filter_by(
            name='public_chat'
        ).first()
        return self._messages_from_chat_to_body(session, user_caller, public_chat, messages_number)

    def _get_private_messages(self, session, user_caller, with_user, messages_number):
        chat_obj = session.query(Chat).filter(
            Chat.type == 'private'
        ).filter(
            Chat.users.any(user_name=user_caller.user_name)
        ).filter(
            Chat.users.any(user_name=with_user.user_name)
        ).first()
        if not chat_obj:
            temp_dict = {'messages': []}
            return self._get_encode_body_from_data(temp_dict)
        else:
            return self._messages_from_chat_to_body(session, user_caller, chat_obj, messages_number)

    def _send_response_for_connect_endpoint(self, user_caller, chat_with, message_number):
        with Session(engine) as session:
            user_obj = session.query(User).filter_by(user_name=user_caller.user_name).first()
            if chat_with == 'public_chat':
                body = self._get_public_messages(session, user_obj, message_number)
            else:
                user_with = session.query(User).filter_by(user_name=chat_with).first()
                if not user_with:
                    self._send_error(404)
                    return
                body = self._get_private_messages(session, user_obj, user_with, message_number)
        headers = self._get_headers_for_json_body(body)
        self._send_response_with_ok_code(body=body, headers=headers)

    # def _get_body_for_comment_response(self, session, message_id):
    #     message = session.query(Message).filter_by(id=message_id).first()
    #     comments = message.comments
    #     result = {
    #         'message': {
    #             'id': message.id,
    #             'pub_date': message.pub_date.strftime('%d.%m.%Y, %H:%M:%S'),
    #             'author': message.author.user_name,
    #             'message_text': message.text,
    #             'message_comments': []
    #         }
    #     }
    #     for comment in comments:
    #         result['message']['message_comments'].append({
    #             'id': comment.id,
    #             'created': comment.created.strftime('%d.%m.%Y, %H:%M:%S'),
    #             'author': message.author.user_name,
    #             'comment_text': comment.text
    #         })
    #     return self._get_encode_body_from_data(result)

    def _send_response_for_comment(self, message_id, comment, user):
        with Session(engine) as session:
            user_obj = session.query(User).filter_by(user_name=user.user_name).first()
            message = session.query(Message).filter_by(id=message_id).first()
            if message:
                Comment(author=user_obj, message=message, text=comment)
                session.commit()
                # self._get_body_for_comment_response(session, message_id)
                self._send_created_code('Comment have created!')
            else:
                self._send_error(400)

    def _send_response_for_send_message(
            self,
            user_caller,
            message,
            send_to,
            public_mes_limit: int = 20,
            minutes_limit: int = 60
    ):
        with Session(engine) as session:
            user_obj = session.query(User).filter_by(user_name=user_caller.user_name).first()
            if send_to == 'public_chat':
                public_chat = session.query(Chat).filter_by(name=send_to).first()
                if self._is_banned(session, user_obj, public_chat):
                    return
                start_chatting_time = user_obj.start_chatting_in_public_chat
                messages_in_hour = user_obj.messages_in_hour_in_public_chat
                finish_time = start_chatting_time + datetime.timedelta(minutes=minutes_limit)
                if messages_in_hour >= public_mes_limit:
                    if finish_time > datetime.datetime.now():
                        self._send_warning(
                            f'message limit has been reached, '
                            f'please wait until {finish_time.strftime("%d.%m.%Y, %H:%M:%S")}'
                        )
                        return
                    else:
                        user_obj.messages_in_hour_in_public_chat = 1
                        user_obj.start_chatting_in_public_chat = datetime.datetime.now()
                        session.commit()
                else:
                    user_obj.messages_in_hour_in_public_chat += 1
                    session.commit()
                self._add_message_to_db(session, message, public_chat, user_obj)
            else:
                send_to_user_obj = session.query(User).filter_by(user_name=send_to).first()
                if not send_to_user_obj:
                    self._send_error(404)
                    return
                chat_obj = session.query(Chat).filter(
                    Chat.type == 'private',
                    Chat.users.any(user_name=user_obj.user_name),
                    Chat.users.any(user_name=send_to)
                ).first()
                if not chat_obj:
                    new_chat = Chat(name=f'private-{int(time.time())}', type='private')
                    new_chat.users = [user_obj, send_to_user_obj]
                    session.add(new_chat)
                    session.commit()
                    self._add_message_to_db(session, message, new_chat, user_obj)
                else:
                    if self._is_banned(session, user_obj, chat_obj):
                        return
                    self._add_message_to_db(session, message, chat_obj, user_obj)
            self._send_created_code('Message have sent!')

    def _is_banned(self, session, user_obj, chat_obj):
        chat_user_obj = session.query(ChatUser).filter_by(
            chat_id=chat_obj.id
        ).filter_by(
            user_id=user_obj.id
        ).first()
        if chat_user_obj.banned:
            if chat_user_obj.banned_till > datetime.datetime.now():
                self._send_warning('You are banned!')
                return chat_user_obj.banned
            chat_user_obj.banned = False
            chat_user_obj.cautions = 0
            session.commit()

    @staticmethod
    def _add_message_to_db(session, message_text, chat, user):
        message = Message(text=message_text, author=user, chat=chat)
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
        body = self._get_encode_body_from_data({'error': ERROR_CODE_TO_MESSAGES[error_code]})
        headers = self._get_headers_for_json_body(body)
        response = h11.Response(status_code=error_code, headers=headers)
        self.send(response)
        self.send(h11.Data(data=body))
        self.send(h11.EndOfMessage())

    def _send_info(self, message):
        body = self._get_encode_body_from_data({'info': message})
        headers = self._get_headers_for_json_body(body)
        self._send_response_with_ok_code(body, headers)

    def _send_warning(self, message):
        body = self._get_encode_body_from_data({'warning': message})
        headers = self._get_headers_for_json_body(body)
        self._send_response_with_ok_code(body, headers)

    def _send_token(self, user_name):
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
                public_chat = session.query(Chat).filter(
                    Chat.type == 'public'
                ).filter_by(
                    name='public_chat'
                ).first()
                public_chat.users.append(new_user)
                session.add(new_user)
                session.commit()
                body = self._get_encode_body_from_data({'token': token[0]})
                headers = self._get_headers_for_json_body(body)
                self._send_response_with_ok_code(body, headers)

    def _send_response_for_report(self, user, chat_type, report_on, ban_hours: int = 4):
        with Session(engine) as session:
            report_on_obj = session.query(User).filter_by(user_name=report_on).first()
            if not report_on_obj:
                self._send_error(400)
                return
            if chat_type == 'public':
                chat_obj = session.query(Chat).filter(
                    Chat.type == 'public',
                    Chat.name == 'public_chat'
                ).first()
            elif chat_type == 'private':
                chat_obj = session.query(Chat).filter(
                    Chat.type == 'private',
                    Chat.users.any(user_name=report_on),
                    Chat.users.any(user_name=user.user_name)
                ).first()
                if not chat_obj:
                    self._send_warning('You can not report a user you have not chat to.')
                    return
            else:
                self._send_error(400)
                return
            chat_user_obj = session.query(ChatUser).filter_by(
                chat_id=chat_obj.id
            ).filter_by(
                user_id=report_on_obj.id
            ).first()
            if chat_user_obj.banned:
                self._send_created_code('User is currently banned.')
                return
            if chat_user_obj.cautions == 2:
                chat_user_obj.banned = True
                chat_user_obj.banned_till = (
                        datetime.datetime.now() + datetime.timedelta(hours=ban_hours)
                )
                session.commit()
            else:
                chat_user_obj.cautions += 1
                session.commit()
            self._send_created_code('Report sent success.')

    @staticmethod
    def _get_headers_for_json_body(body):
        return [
            ('Content-Type', 'application/json'),
            ('Content-Length', str(len(body))),
        ]

    def _send_created_code(self, message):
        body = self._get_encode_body_from_data({'info': message})
        headers = self._get_headers_for_json_body(body)
        response = h11.Response(status_code=201, headers=headers)
        self.send(response)
        self.send(h11.Data(data=body))
        self.send(h11.EndOfMessage())

    @staticmethod
    def _get_encode_body_from_data(data: dict):
        return json.dumps(
            data, indent=4, separators=(',', ': ')
        ).encode('utf-8')


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

# asyncio.run(main('127.0.0.1', 5000))
