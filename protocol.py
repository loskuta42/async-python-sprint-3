import asyncio
import datetime
import json
import os
import secrets
import time
from http import HTTPStatus
from typing import Optional

import h11
from sqlalchemy import create_engine, desc
from sqlalchemy.orm import Session

from enums import ChatType
from models import Chat, ChatUser, Comment, Message, User
from utils import get_logger_for_module


logger = get_logger_for_module(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))
engine = create_engine('sqlite:///' + os.path.join(basedir, 'data.sqlite'), echo=True)

ERROR_CODE_TO_MESSAGES = {
    HTTPStatus.UNAUTHORIZED: 'Unauthorized. Please name yourself, add "user_name" '
                             'to request body (not empty)'
                             'and/or enter/check/recheck your Bearer Token in '
                             '"Authorization" header. If you have not have token yet, '
                             'get it by POST request to endpoint "get_token"',
    HTTPStatus.BAD_REQUEST: 'BAD REQUEST',
    HTTPStatus.NOT_FOUND: 'Not found message/user_name/chat',
    HTTPStatus.METHOD_NOT_ALLOWED: 'Not allowed http method'
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
    """
    Custom HTTP protocol.
    For more info see README.md
    """

    def __init__(self):
        self.connection = h11.Connection(h11.SERVER)

    def connection_made(self, transport: asyncio.Transport) -> None:
        self._transport = transport
        logger.info('Start serving %s', transport.get_extra_info('peername'))

    def eof_received(self) -> bool:
        self.connection.receive_data(b"")
        self._deliver_events()
        return True

    def _deliver_events(self) -> None:
        while True:
            event = self.connection.next_event()
            try:
                if isinstance(event, h11.Request):
                    self._request_processing(self.connection, event)
                elif (
                        event is h11.NEED_DATA or event is h11.PAUSED
                ):
                    break
            except RuntimeError:
                self._send_error(HTTPStatus.METHOD_NOT_ALLOWED)
            if self.connection.our_state is h11.MUST_CLOSE:
                logger.info('Close connection %s', self._transport.get_extra_info('peername'))
                self._transport.close()
                break

    def data_received(self, data: bytes) -> None:
        self.connection.receive_data(data)
        self._deliver_events()

        if self.connection.our_state is h11.DONE:
            self.connection.start_next_cycle()
            self._deliver_events()

    def _token_endpoint_processing(self, data: dict) -> None:
        user_name = data.get('user_name', None)
        if not user_name:
            self._send_error(HTTPStatus.UNAUTHORIZED)
        else:
            self._send_token(user_name)

    def _connect_endpoint_processing(
            self,
            data: dict,
            request_event: h11.Request
    ) -> None:
        if user_obj := self._check_auth(request_event):
            chat_with = data.get('chat_with', 'public_chat')
            messages_number = data.get('messages_number', 20)
            self._send_response_for_connect_endpoint(
                user_obj,
                chat_with,
                messages_number

            )
        else:
            self._send_error(HTTPStatus.UNAUTHORIZED)

    def _send_endpoint_processing(
            self,
            data: dict,
            request_event: h11.Request
    ) -> None:
        if user_obj := self._check_auth(request_event):
            message = data.get('message')
            if not message:
                self._send_error(HTTPStatus.BAD_REQUEST)
            else:
                chat_name = data.get('send_to', 'public_chat')
                self._send_response_for_send_message(user_obj, message, chat_name)

    def _comment_endpoint_processing(
            self,
            data: dict,
            request_event: h11.Request
    ) -> None:
        if user_obj := self._check_auth(request_event):
            message_id = data.get('message_id')
            comment = data.get('comment')
            if not message_id or not comment:
                self._send_error(HTTPStatus.BAD_REQUEST)
            else:
                self._send_response_for_comment(message_id, comment, user_obj)

    def _report_endpoint_processing(
            self,
            data: dict,
            request_event: h11.Request
    ) -> None:
        if user_obj := self._check_auth(request_event):
            report_on = data.get('report_on')
            chat_type = data.get('chat_type')
            if not report_on or not chat_type or chat_type not in [
                item.value
                for item in ChatType
            ]:
                self._send_error(HTTPStatus.BAD_REQUEST)
            else:
                if chat_type == ChatType.PUBLIC.value:
                    chat_type = ChatType.PUBLIC
                elif chat_type == ChatType.PRIVATE.value:
                    chat_type = ChatType.PRIVATE
                self._send_response_for_report(user_obj, chat_type, report_on)

    def _status_endpoint_processing(
            self,
            request_event: h11.Request
    ) -> None:
        if user_obj := self._check_auth(request_event):
            self._send_response_status_endpoint(user_obj)

    def _process_post_request(self, data: dict, request_event: h11.Request) -> None:
        if request_event.target == b'/get-token':
            self._token_endpoint_processing(data)
        elif request_event.target == b'/connect':
            self._connect_endpoint_processing(data, request_event)
        elif request_event.target == b'/send':
            self._send_endpoint_processing(data, request_event)
        elif request_event.target == b'/comment':
            self._comment_endpoint_processing(data, request_event)
        elif request_event.target == b'/report':
            self._report_endpoint_processing(data, request_event)

    def _process_get_request(self, request_event: h11.Request) -> None:
        if request_event.target == b'/status':
            self._status_endpoint_processing(request_event)

    def _request_processing(self, connection: h11.Connection, request_event: h11.Request) -> None:
        if request_event.method not in [b'GET', b'POST']:
            logger.error('unsupported HTTP method')
            raise RuntimeError('unsupported method')
        while True:
            event = connection.next_event()
            if isinstance(event, h11.EndOfMessage):
                break
            elif isinstance(event, h11.Data):
                if request_event.method == b'POST':
                    data = json.loads(event.data.decode('utf-8'))
                    self._process_post_request(data, request_event)
                else:
                    self._process_get_request(request_event)

    @staticmethod
    def _get_chat_name(chat: Chat, user_obj: User) -> str:
        if chat.type == ChatType.PUBLIC:
            return chat.name
        if chat.users[0].user_name != user_obj.user_name:
            return chat.users[0].user_name
        return chat.users[1].user_name

    def _send_response_status_endpoint(self, user: User) -> None:
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
                        'name': self._get_chat_name(chat=chat, user_obj=user_obj),
                        'chat_type': str(chat.type.value),
                        'created': chat.created.strftime('%d.%m.%Y, %H:%M:%S'),
                        'messages_number': chat.messages.count(),
                        'users_number': chat.users.count()
                    }
                )
            body = self._get_encode_body_from_data(result)
            headers = self._get_headers_for_json_body(body)
            self._send_response_with_ok_code(body, headers)

    def _check_auth(self, request_event: h11.Request) -> Optional[User]:
        token = None
        for name, value in request_event.headers:
            if name.lower() == b'authorization':
                decode_token = value.decode('utf-8')
                try:
                    _, token = decode_token.split()
                except IndexError:
                    self._send_error(HTTPStatus.UNAUTHORIZED)
                    return
        if not token:
            self._send_error(HTTPStatus.UNAUTHORIZED)
            return
        with Session(engine) as session:
            if user_obj := session.query(User).filter_by(token=token).first():
                return user_obj
        self._send_error(HTTPStatus.UNAUTHORIZED)

    def _send_response_with_ok_code(self, body: bytes, headers: list) -> None:
        response = h11.Response(status_code=HTTPStatus.OK, headers=headers)
        self.send(response)
        self.send(h11.Data(data=body))
        self.send(h11.EndOfMessage())

    def send(self, event: h11.Event) -> None:
        data = self.connection.send(event)
        self._transport.write(data)

    @staticmethod
    def _get_message_info(message: Message) -> dict:
        return {
            'id': message.id,
            'pub_date': message.pub_date.strftime('%d.%m.%Y, %H:%M:%S'),
            'author': message.author.user_name,
            'message_text': message.text,
            'message_comments': str(message.comments)
        }

    def _messages_from_chat_to_body(
            self,
            session: Session,
            user_caller: User,
            chat: Chat,
            messages_number: int
    ) -> bytes:
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
        unread_messages = session.query(
            Message
        ).filter(Message.chat == chat,
                 Message.pub_date > last_connect).all()
        for message in last_messages:
            temp_dict['messages'].append(
                self._get_message_info(message)
            )
        for message in unread_messages:
            temp_dict['unread_messages'].append(
                self._get_message_info(message)
            )
        chat_user_obj.last_connect = datetime.datetime.utcnow()
        session.commit()
        return self._get_encode_body_from_data(temp_dict)

    def _get_public_messages(
            self,
            session: Session,
            user_caller: User,
            messages_number: int
    ) -> bytes:
        public_chat = session.query(Chat).filter(
            Chat.type == ChatType.PUBLIC
        ).filter_by(
            name='public_chat'
        ).first()
        return self._messages_from_chat_to_body(session, user_caller, public_chat, messages_number)

    def _get_private_messages(
            self,
            session: Session,
            user_caller: User,
            with_user: User,
            messages_number: int
    ) -> bytes:
        chat_obj = session.query(Chat).filter(
            Chat.type == ChatType.PRIVATE
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

    def _send_response_for_connect_endpoint(
            self,
            user_caller: User,
            chat_with: str,
            message_number: int
    ) -> None:
        with Session(engine) as session:
            user_obj = session.query(User).filter_by(user_name=user_caller.user_name).first()
            if chat_with == 'public_chat':
                body = self._get_public_messages(session, user_obj, message_number)
            else:
                user_with = session.query(User).filter_by(user_name=chat_with).first()
                if not user_with:
                    self._send_error(HTTPStatus.NOT_FOUND)
                    return
                body = self._get_private_messages(session, user_obj, user_with, message_number)
        headers = self._get_headers_for_json_body(body)
        self._send_response_with_ok_code(body=body, headers=headers)
        logger.info('Sent chat info.')

    def _send_response_for_comment(
            self,
            message_id: int,
            comment: str,
            user: User
    ) -> None:
        with Session(engine) as session:
            user_obj = session.query(User).filter_by(user_name=user.user_name).first()
            message = session.query(Message).filter_by(id=message_id).first()
            if message:
                Comment(author=user_obj, message=message, text=comment)
                session.commit()
                self._send_created_code('Comment have created!')
                logger.info('Comment have created')
            else:
                self._send_error(HTTPStatus.BAD_REQUEST)

    def _add_message_to_db_and_sent_response(
            self,
            session: Session,
            message_text: str,
            chat: Chat,
            user: User
    ) -> None:
        self._add_message_to_db(session, message_text, chat, user)
        self._send_created_code('Message have sent!')
        logger.info('Message have sent.')

    def _send_message_to_public_chat(
            self,
            session: Session,
            user_obj: User,
            message: str,
            public_mes_limit: int,
            send_to: str,
            minutes_limit: int
    ) -> None:
        public_chat = session.query(Chat).filter_by(name=send_to).first()
        if self._is_banned(session, user_obj, public_chat):
            return
        start_chatting_time = user_obj.start_chatting_in_public_chat
        messages_in_hour = user_obj.messages_in_hour_in_public_chat
        finish_time = start_chatting_time + datetime.timedelta(minutes=minutes_limit)
        if messages_in_hour >= public_mes_limit:
            if finish_time > datetime.datetime.utcnow():
                self._send_warning(
                    'message limit has been reached, '
                    f'please wait until {finish_time.strftime("%d.%m.%Y, %H:%M:%S")}'
                )
                return
            else:
                user_obj.messages_in_hour_in_public_chat = 1
                user_obj.start_chatting_in_public_chat = datetime.datetime.utcnow()
                session.commit()
        else:
            user_obj.messages_in_hour_in_public_chat += 1
            session.commit()
        self._add_message_to_db_and_sent_response(
            session=session,
            message_text=message,
            chat=public_chat,
            user=user_obj
        )

    def _send_message_to_private_chat(
            self,
            session: Session,
            user_obj: User,
            send_to: str,
            message: str
    ) -> None:
        send_to_user_obj = session.query(User).filter_by(user_name=send_to).first()
        if not send_to_user_obj:
            self._send_error(HTTPStatus.NOT_FOUND)
            return
        chat_obj = session.query(Chat).filter(
            Chat.type == ChatType.PRIVATE,
            Chat.users.any(user_name=user_obj.user_name),
            Chat.users.any(user_name=send_to)
        ).first()
        if not chat_obj:
            new_chat = Chat(name=f'private-{int(time.time())}', type=ChatType.PRIVATE)
            new_chat.users = [user_obj, send_to_user_obj]
            session.add(new_chat)
            session.commit()
            self._add_message_to_db(session, message, new_chat, user_obj)
        else:
            if self._is_banned(session, user_obj, chat_obj):
                return
            self._add_message_to_db_and_sent_response(
                session=session,
                message_text=message,
                chat=chat_obj,
                user=user_obj
            )

    def _send_response_for_send_message(
            self,
            user_caller: User,
            message: str,
            send_to: str,
            public_mes_limit: int = 20,
            minutes_limit: int = 60
    ) -> None:
        with Session(engine) as session:
            user_obj = session.query(User).filter_by(user_name=user_caller.user_name).first()
            if send_to == 'public_chat':
                self._send_message_to_public_chat(
                    session=session,
                    user_obj=user_obj,
                    message=message,
                    public_mes_limit=public_mes_limit,
                    send_to=send_to,
                    minutes_limit=minutes_limit
                )
            else:
                self._send_message_to_private_chat(
                    session=session,
                    user_obj=user_obj,
                    send_to=send_to,
                    message=message
                )

    def _is_banned(
            self,
            session: Session,
            user_obj: User,
            chat_obj: Chat
    ) -> Optional[bool]:
        chat_user_obj = session.query(ChatUser).filter_by(
            chat_id=chat_obj.id
        ).filter_by(
            user_id=user_obj.id
        ).first()
        if chat_user_obj.banned:
            if chat_user_obj.banned_till > datetime.datetime.utcnow():
                self._send_warning('You are banned!')
                return chat_user_obj.banned
            chat_user_obj.banned = False
            chat_user_obj.cautions = 0
            session.commit()

    @staticmethod
    def _add_message_to_db(
            session: Session,
            message_text: str,
            chat: Chat,
            user: User
    ) -> None:
        message = Message(text=message_text, author=user, chat=chat)
        session.add(message)
        session.commit()
        chat_user_obj = session.query(ChatUser).filter_by(
            chat_id=chat.id
        ).filter_by(
            user_id=user.id
        ).first()
        chat_user_obj.last_connect = datetime.datetime.utcnow()
        session.commit()
        logger.info('Message add to database.')

    def _send_error(
            self,
            error_code: int
    ) -> None:
        body = self._get_encode_body_from_data({'error': ERROR_CODE_TO_MESSAGES[error_code]})
        headers = self._get_headers_for_json_body(body)
        response = h11.Response(status_code=error_code, headers=headers)
        self.send(response)
        self.send(h11.Data(data=body))
        self.send(h11.EndOfMessage())
        logger.error(f'Send error with code {error_code}')

    def _send_info(
            self,
            message: str
    ) -> None:
        body = self._get_encode_body_from_data({'info': message})
        headers = self._get_headers_for_json_body(body)
        self._send_response_with_ok_code(body, headers)
        logger.info('Send info.')

    def _send_warning(
            self,
            message: str
    ) -> None:
        body = self._get_encode_body_from_data({'warning': message})
        headers = self._get_headers_for_json_body(body)
        self._send_response_with_ok_code(body, headers)
        logger.warning('Send warning.')

    def _send_token(
            self,
            user_name: str
    ) -> None:
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
                    Chat.type == ChatType.PUBLIC
                ).filter_by(
                    name='public_chat'
                ).first()
                public_chat.users.append(new_user)
                session.add(new_user)
                session.commit()
                body = self._get_encode_body_from_data({'token': token[0]})
                headers = self._get_headers_for_json_body(body)
                self._send_response_with_ok_code(body, headers)
                logger.info('Token send.')

    def _get_chat_obj(
            self,
            session: Session,
            user: User,
            chat_type: ChatType,
            report_on: str,
    ) -> Optional[Chat]:
        if chat_type == ChatType.PUBLIC:
            return session.query(Chat).filter(
                Chat.type == ChatType.PUBLIC,
                Chat.name == 'public_chat'
            ).first()
        elif chat_type == ChatType.PRIVATE:
            chat_obj = session.query(Chat).filter(
                Chat.type == ChatType.PRIVATE,
                Chat.users.any(user_name=report_on),
                Chat.users.any(user_name=user.user_name)
            ).first()
            if not chat_obj:
                self._send_warning('You can not report a user you have not chat to.')
                return
            return chat_obj
        else:
            self._send_error(HTTPStatus.BAD_REQUEST)
            return

    def _set_caution(
            self,
            session: Session,
            report_on_obj: User,
            chat_obj: Chat,
            ban_hours: int
    ) -> None:
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
                    datetime.datetime.utcnow() + datetime.timedelta(hours=ban_hours)
            )
            session.commit()
        else:
            chat_user_obj.cautions += 1
            session.commit()
        self._send_created_code('Report sent success.')
        logger.info('Add caution/report.')

    def _send_response_for_report(
            self,
            user: User,
            chat_type: ChatType,
            report_on: str,
            ban_hours: int = 4
    ) -> None:
        with Session(engine) as session:
            report_on_obj = session.query(User).filter_by(user_name=report_on).first()
            if not report_on_obj:
                self._send_error(HTTPStatus.BAD_REQUEST)
                return
            chat_obj = self._get_chat_obj(
                session=session,
                user=user,
                chat_type=chat_type,
                report_on=report_on
            )
            if not chat_obj:
                return
            self._set_caution(
                session=session,
                report_on_obj=report_on_obj,
                chat_obj=chat_obj,
                ban_hours=ban_hours
            )

    @staticmethod
    def _get_headers_for_json_body(body: bytes) -> list[tuple]:
        return [
            ('Content-Type', 'application/json'),
            ('Content-Length', str(len(body))),
        ]

    def _send_created_code(
            self,
            message: str
    ) -> None:
        body = self._get_encode_body_from_data({'info': message})
        headers = self._get_headers_for_json_body(body)
        response = h11.Response(status_code=HTTPStatus.CREATED, headers=headers)
        self.send(response)
        self.send(h11.Data(data=body))
        self.send(h11.EndOfMessage())
        logger.info(f'Send {HTTPStatus.CREATED} code')

    @staticmethod
    def _get_encode_body_from_data(data: dict) -> bytes:
        return json.dumps(
            data, indent=4, separators=(',', ': ')
        ).encode('utf-8')
