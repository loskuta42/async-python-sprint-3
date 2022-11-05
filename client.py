from __future__ import annotations

import json
import os.path
import socket
from http import HTTPStatus
from typing import Optional

import h11

from enums import ChatType
from utils import get_logger_for_module


logger = get_logger_for_module(__name__)


class Client:
    """
    Client for custom http-server.
    When the object is created, it automatically connects to the server,
    authenticates, and requests general chat information.
    """

    def __init__(
            self,
            user_name: str,
            server_host: str = '127.0.0.1',
            server_port: int = 8000
    ) -> None:
        """

        :param user_name: client user name;
        :param server_host: server host;
        :param server_port: server port.
        """
        self.user_name = user_name
        self.server_host = server_host
        self.server_port = server_port
        self.sock = socket.create_connection((server_host, server_port))
        self.conn = h11.Connection(our_role=h11.CLIENT)
        self._token = None
        self._get_token()
        self.connect_to_chat()
        self._response = None
        self._last_chat_info = None
        self._last_status = None

    def _send(self, *events: h11.Event) -> None:
        for event in events:
            data = self.conn.send(event)
            if data is None:
                self.sock.shutdown(socket.SHUT_WR)
            else:
                self.sock.sendall(data)

    def next_event(self, max_bytes_per_recv: int = 10240) -> h11.Event:
        while True:
            event = self.conn.next_event()
            if event is h11.NEED_DATA:
                self.conn.receive_data(self.sock.recv(max_bytes_per_recv))
                continue
            return event

    def _is_can_get_token_from_file(self, file_name: str) -> Optional[bool]:
        """
        In client, token is equal to password, and server send token only once.
        For this reason, this method write token in local file for restore, when
        user recreate client object with the same user_name.
        """
        with open(file_name) as file:
            for line in file:
                user_name, token = line.split()
                if user_name == self.user_name:
                    self._token = f'Bearer {token}'
                    return True

    def _get_headers(self, auth: bool, body: bytes) -> list[tuple]:
        if auth:
            return [
                ('Authorization', f'{self._token}'),
                ('Host', f'{self.server_host}'),
                ("Content-Length", str(len(body)))
            ]
        return [
            ('Host', f'{self.server_host}'),
            ("Content-Length", str(len(body)))
        ]

    def _send_request_to_endpoint(
            self,
            endpoint: str,
            method: str,
            body: bytes,
            auth: bool = False
    ) -> Optional[bool]:
        if not endpoint.startswith('/') and endpoint.endswith('/') and method not in ['POST', 'GET']:
            logger.error('Enter correct endpoint("/example") and/or method')
            return
        self._send(h11.Request(
            method=method,
            target=endpoint,
            headers=self._get_headers(body=body, auth=auth))
        )
        self._send(h11.Data(data=body))
        self._send(h11.EndOfMessage())
        return True

    def _get_token_from_server(self, data: dict, file_name: str) -> None:
        if token := data.get('token'):
            with open(file_name, 'a') as file:
                print(f'{self.user_name} {token}', file=file)
            self._token = f'Bearer {token}'
        elif error := data.get('error'):
            logger.error(
                f'Can not get token, for {self.user_name}, error message: {error}'
            )

    def _get_token(self, file_name: str = 'client.txt') -> None:
        self._result = None
        if os.path.exists(file_name) and self._is_can_get_token_from_file(file_name):
            return
        body = json.dumps({'user_name': self.user_name}).encode('utf-8')
        if not self._send_request_to_endpoint(
                endpoint='/get-token',
                method='POST',
                body=body
        ):
            return
        while True:
            event = self.next_event()
            if isinstance(event, h11.EndOfMessage):
                self.conn.start_next_cycle()
                break
            elif isinstance(event, h11.Response):
                if event.status_code == HTTPStatus.OK:
                    continue
            if isinstance(event, h11.Data):
                data = json.loads(event.data.decode('utf-8'))
                self._get_token_from_server(data=data, file_name=file_name)

    def connect_to_chat(
            self,
            chat_name: str = 'public_chat',
            redirect: bool = False
    ) -> None:
        """
        Makes a request to chat.
        :param chat_name: name of chat/user.
        :param redirect: redirect mode.
        """
        body = json.dumps({'chat_with': chat_name}).encode('utf-8')
        if not self._send_request_to_endpoint(
                endpoint='/connect',
                method='POST',
                body=body,
                auth=True
        ):
            return
        self._last_chat_info = None
        while True:
            event = self.next_event()
            error_code = 0
            if isinstance(event, h11.EndOfMessage):
                self.conn.start_next_cycle()
                break
            elif isinstance(event, h11.Response):
                if event.status_code == HTTPStatus.OK:
                    continue
                elif event.status_code in (
                        HTTPStatus.UNAUTHORIZED,
                        HTTPStatus.NOT_FOUND
                ):
                    error_code += event.status_code
            if isinstance(event, h11.Data):
                data = json.loads(event.data.decode('utf-8'))
                if data.get('messages'):
                    logger.info(f'Get messages: {data}')
                elif error := data.get('error'):
                    logger.error(
                        f'Error in connection to chat {chat_name}.'
                        f'Error code: {error_code}. Error message: {error}'
                    )
                self._last_chat_info = data
                if not redirect:
                    self._response = data

    def _get_response_and_redirect(
            self,
            receiver: str = 'public_chat',
            report: bool = False,
            chat_type: Optional[ChatType] = None
    ) -> None:
        self._response = None
        redirect, response = self.even_cycle()
        if redirect:
            logger.info('Redirect to chat')
            if not report:
                self.connect_to_chat(receiver, redirect=True)
            else:
                if chat_type == ChatType.PUBLIC:
                    self.connect_to_chat()
                else:
                    self.connect_to_chat(receiver, redirect=True)
        if response:
            self._response = response[0]

    def send_message(
            self,
            receiver: str = 'public_chat',
            message: str = ''
    ) -> None:
        """
        Send message to chat, and redirect back to chat.
        :param receiver: receiver of message.
        :param message:  text of the message.
        """
        if not message:
            logger.error('Enter message, please.')
            return
        body = json.dumps({
            'send_to': receiver,
            'message': message
        }).encode('utf-8')
        if not self._send_request_to_endpoint(
                endpoint='/send',
                method='POST',
                body=body,
                auth=True
        ):
            return
        self._get_response_and_redirect(receiver=receiver)

    def add_comment(
            self,
            message_id: int,
            comment: str = ''
    ) -> None:
        """
        add comment to message, and redirect to chat.
        :param message_id: id of the commenting message.
        :param comment: text of the comment
        """
        if not comment:
            logger.error('Enter comment, please.')
            return
        body = json.dumps({
            'message_id': message_id,
            'comment': comment
        }).encode('utf-8')
        if not self._send_request_to_endpoint(
                endpoint='/comment',
                method='POST',
                body=body,
                auth=True
        ):
            return
        self._get_response_and_redirect()

    def report(
            self,
            report_on: str,
            chat_type: Optional[ChatType] = None
    ) -> None:
        """
        retort about user.
        :param report_on: user for report.
        :param chat_type: type of the chat where you want report about user.
        """
        if not chat_type:
            logger.error('Enter chat_type argument, please.')
            return
        body = json.dumps({
            'report_on': report_on,
            'chat_type': chat_type.value
        }).encode('utf-8')
        if not self._send_request_to_endpoint(
                endpoint='/report',
                method='POST',
                body=body,
                auth=True
        ):
            return
        self._get_response_and_redirect(
            receiver=report_on,
            report=True,
            chat_type=chat_type
        )

    def even_cycle(self) -> tuple[int, list]:
        """
        event cycle of getting response from server.
        """
        redirect = 0
        response = []
        while True:
            event = self.next_event()
            error_code = 0
            if isinstance(event, h11.EndOfMessage):
                self.conn.start_next_cycle()
                break
            elif isinstance(event, h11.Response):
                if event.status_code == HTTPStatus.CREATED:
                    continue
                elif event.status_code in (
                        HTTPStatus.UNAUTHORIZED,
                        HTTPStatus.NOT_FOUND,
                        HTTPStatus.BAD_REQUEST
                ):
                    error_code += event.status_code
            if isinstance(event, h11.Data):
                data = json.loads(event.data.decode('utf-8'))
                if data.get('info'):
                    redirect += 1
                    logger.info(f'Success: {data}')
                elif error := data.get('error'):
                    logger.error(
                        'Error in event cycle method.'
                        f'Error code: {error_code}. Error message: {error}'
                    )
                elif warning := data.get('warning'):
                    logger.error(f'Warning in event cycle method: {warning}')
                response.append(data)
        return redirect, response

    def get_status(self) -> None:
        """
        get status of client and chats.
        """
        body = json.dumps({'user_name': self.user_name}).encode('utf-8')
        if not self._send_request_to_endpoint(
                endpoint='/status',
                method='GET',
                body=body,
                auth=True
        ):
            return
        self._last_status = None
        while True:
            event = self.next_event()
            error_code = 0
            if isinstance(event, h11.EndOfMessage):
                self.conn.start_next_cycle()
                break
            elif isinstance(event, h11.Response):
                if event.status_code == HTTPStatus.OK:
                    continue
                elif event.status_code in (
                        HTTPStatus.UNAUTHORIZED,
                        HTTPStatus.NOT_FOUND
                ):
                    error_code += event.status_code
            if isinstance(event, h11.Data):
                data = json.loads(event.data.decode('utf-8'))
                if data.get('connected_as'):
                    logger.info(f'Get status: {data}')
                elif error := data.get('error'):
                    logger.error(
                        'Error in get status.'
                        f'Error code: {error_code}. Error message: {error}'
                    )
                self._last_status = data

    @property
    def response(self) -> Optional[dict]:
        return self._response

    @property
    def last_chat_info(self) -> Optional[dict]:
        return self._last_chat_info

    @property
    def last_status(self) -> Optional[dict]:
        return self._last_status

    def close_connection(self) -> None:
        """
        close connection between client and server.
        """
        self._send(h11.ConnectionClosed())
        self.sock.close()
