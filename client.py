from __future__ import annotations

import json
import logging.config
import socket
import time
from typing import Optional

import h11
import yaml


with open('logging_config.yaml', 'r') as f:
    config = yaml.safe_load(f.read())
    logging.config.dictConfig(config)

logger = logging.getLogger(__name__)


class Client:
    """Client for custom http-server."""
    def __init__(
            self,
            user_name: str,
            server_host='127.0.0.1',
            server_port=8000
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
        time.sleep(0.1)
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

    def _get_token(self) -> None:
        self._result = None
        with open('client.txt') as file:
            for line in file:
                user_name, token = line.split()
                if user_name == self.user_name:
                    self._token = f'Bearer {token}'
        body = json.dumps({'user_name': self.user_name}).encode('utf-8')
        self._send(h11.Request(method='POST', target='/get-token',
                               headers=[('Host', f'{self.server_host}'),
                                        ("Content-Length", str(len(body)))]))
        self._send(h11.Data(data=body))
        self._send(h11.EndOfMessage())
        while True:
            event = self.next_event()
            if isinstance(event, h11.EndOfMessage):
                self.conn.start_next_cycle()
                break
            elif isinstance(event, h11.Response):
                if event.status_code == 200:
                    continue
                else:
                    logger.error(f'Can not get token, for {self.user_name}')
            if isinstance(event, h11.Data):
                data = json.loads(event.data.decode('utf-8'))
                if token := data.get('token'):
                    with open('client.txt', 'a') as file:
                        print(f'{self.user_name} {token}', file=file)
                    self._token = f'Bearer {token}'
                elif error := data.get('error'):
                    logger.error(f'{error}')

    def connect_to_chat(
            self,
            chat_name: str = 'public_chat',
            redirect: bool = False
    ) -> None:
        body = json.dumps({'chat_with': chat_name}).encode('utf-8')
        self._send(h11.Request(method='POST', target='/connect',
                               headers=[('Authorization', f'{self._token}'),
                                        ('Host', f'{self.server_host}'),
                                        ("Content-Length", str(len(body)))]))
        self._send(h11.Data(data=body))
        self._send(h11.EndOfMessage())
        self._last_chat_info = None
        while True:
            event = self.next_event()
            if isinstance(event, h11.EndOfMessage):
                self.conn.start_next_cycle()
                break
            elif isinstance(event, h11.Response):
                if event.status_code == 200:
                    continue
                elif event.status_code == 401:
                    logger.error(f'Unauthorized')
                elif event.status_code == 404:
                    logger.error(f'Not Found')
            if isinstance(event, h11.Data):
                data = json.loads(event.data.decode('utf-8'))
                if data.get('messages'):
                    logger.info(f'Get messages: {data}')
                elif error := data.get('error'):
                    logger.error(f'{error}')
                self._last_chat_info = data
                if not redirect:
                    self._response = data

    def send_message(
            self,
            receiver: str = 'public_chat',
            message: str = ''
    ) -> None:
        if not message:
            logger.error('Enter message, please.')
            return
        body = json.dumps({
            'send_to': receiver,
            'message': message
        }).encode('utf-8')
        self._send(h11.Request(method='POST', target='/send',
                               headers=[('Authorization', f'{self._token}'),
                                        ('Host', f'{self.server_host}'),
                                        ("Content-Length", str(len(body)))]))
        self._send(h11.Data(data=body))
        self._send(h11.EndOfMessage())
        self._response = None
        redirect, response = self.even_cycle()
        if redirect:
            time.sleep(0.1)
            logger.info('Redirect to chat')
            self.connect_to_chat(receiver, redirect=True)
        if response:
            self._response = response[0]

    def add_comment(
            self,
            message_id: int,
            comment: str = ''
    ) -> None:
        if not comment:
            logger.error('Enter comment, please.')
            return
        body = json.dumps({
            'message_id': message_id,
            'comment': comment
        }).encode('utf-8')
        self._send(h11.Request(method='POST', target='/comment',
                               headers=[('Authorization', f'{self._token}'),
                                        ('Host', f'{self.server_host}'),
                                        ("Content-Length", str(len(body)))]))
        self._send(h11.Data(data=body))
        self._send(h11.EndOfMessage())
        self._response = None
        redirect, response = self.even_cycle()
        if redirect:
            time.sleep(0.1)
            logger.info('Redirect to chat')
            self.connect_to_chat(redirect=True)
        if response:
            self._response = response[0]

    def report(
            self,
            report_on: str,
            chat_type: str = ''
    ) -> None:
        if not chat_type:
            logger.error('Enter chat_type argument, please.')
            return
        if chat_type not in ['public', 'private']:
            logger.error('Enter public or private in chat_type field, please.')
            return
        body = json.dumps({
            'report_on': report_on,
            'chat_type': chat_type
        }).encode('utf-8')
        self._send(h11.Request(method='POST', target='/report',
                               headers=[('Authorization', f'{self._token}'),
                                        ('Host', f'{self.server_host}'),
                                        ("Content-Length", str(len(body)))]))
        self._send(h11.Data(data=body))
        self._send(h11.EndOfMessage())
        self._response = None
        redirect, response = self.even_cycle()
        if redirect:
            time.sleep(0.1)
            logger.info('Redirect to chat')
            if chat_type == 'public':
                self.connect_to_chat()
            else:
                self.connect_to_chat(report_on, redirect=True)
        if response:
            self._response = response[0]

    def even_cycle(self) -> tuple:
        redirect = 0
        response = []
        while True:
            event = self.next_event()
            if isinstance(event, h11.EndOfMessage):
                self.conn.start_next_cycle()
                break
            elif isinstance(event, h11.Response):
                if event.status_code == 201:
                    continue
                elif event.status_code == 401:
                    logger.error('Unauthorized')
                elif event.status_code == 404:
                    logger.error('Not Found')
                elif event.status_code == 400:
                    logger.error('BAD REQUEST')
            if isinstance(event, h11.Data):
                data = json.loads(event.data.decode('utf-8'))
                if data.get('info'):
                    redirect += 1
                    logger.info(f'Success: {data}')
                elif error := data.get('error'):
                    logger.error(f'{error}')
                elif warning := data.get('warning'):
                    logger.error(f'{warning}')
                response.append(data)
        return redirect, response

    def get_status(self) -> None:
        body = json.dumps({'user_name': self.user_name}).encode('utf-8')
        self._send(h11.Request(method='GET', target='/status',
                               headers=[('Authorization', f'{self._token}'),
                                        ('Host', f'{self.server_host}'),
                                        ("Content-Length", str(len(body)))]))
        self._send(h11.Data(data=body))
        self._send(h11.EndOfMessage())
        self._last_status = None
        while True:
            event = self.next_event()
            if isinstance(event, h11.EndOfMessage):
                self.conn.start_next_cycle()
                break
            elif isinstance(event, h11.Response):
                if event.status_code == 200:
                    continue
                elif event.status_code == 401:
                    logger.error('Unauthorized')
                elif event.status_code == 404:
                    logger.error('Not Found')
            if isinstance(event, h11.Data):
                data = json.loads(event.data.decode('utf-8'))
                if data.get('connected_as'):
                    logger.info(f'Get status: {data}')
                elif error := data.get('error'):
                    logger.error(f'{error}')
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
        self._send(h11.ConnectionClosed())
        self.sock.close()
