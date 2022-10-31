import datetime
import logging
import os
import sys
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import h11
import io
from contextlib import redirect_stdout

from models import User, Message, Comment, Chat, ChatUser

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(stream=sys.stdout))

basedir = os.path.abspath(os.path.dirname(__file__))
engine = create_engine('sqlite:///' + os.path.join(basedir, 'data.sqlite'), echo=True)


def test_connection(client_one):
    assert isinstance(client_one.conn.their_state, h11.IDLE)
    assert isinstance(client_one.conn.our_state, h11.IDLE)


def test_get_token(client_one):
    with open('client.txt') as file:
        for line in file:
            user_name, token = line.split()
            if user_name == client_one.user_name:
                break
    with Session(engine) as session:
        client_obj = session.query(User).filter_by(user_name=client_one.user_name).first()

    assert client_one._token.split()[1] == token
    assert client_obj.token == token


def test_get_status(client_one):
    time.sleep(1)
    client_one.get_status()
    result = client_one.last_status
    assert result.get('connected_as')
    assert result.get('connected_as') == client_one.user_name
    assert result.get('chats')


def test_send_message_to_public_chat(client_one):
    time.sleep(1)
    message_text = str(time.time())
    client_one.send_message(message=message_text)
    time.sleep(2)
    response, chat_info = client_one.response, client_one.last_chat_info
    with Session(engine) as session:
        message_obj = session.query(Message).filter_by(text=message_text).first()
    assert message_obj
    assert response['info'] == 'Message have sent!'
    for message in chat_info['messages']:
        print(message)
        if message['id'] == message_obj.id:
            assert message_obj.text == message['message_text']
            break


def test_message_limit(client_one):
    start_time = datetime.datetime.now()
    with Session(engine) as session:
        user_obj = session.query(User).filter_by(user_name=client_one.user_name).first()
        user_obj.messages_in_hour_in_public_chat = 20
        user_obj.start_chatting_in_public_chat = start_time
        session.commit()
    message_text = 'test_limit'
    client_one.send_message(message=message_text)
    response, chat_info = client_one.response, client_one.last_chat_info
    with Session(engine) as session:
        message_obj = session.query(Message).filter_by(text=message_text).first()
    finish_time = (start_time + datetime.timedelta(minutes=60)).strftime("%d.%m.%Y, %H:%M:%S")
    assert message_obj is None
    assert response['warning'].startswith('message limit has been reached')
    assert response['warning'].endswith(finish_time)
    with Session(engine) as session:
        user_obj = session.query(User).filter_by(user_name=client_one.user_name).first()
        user_obj.messages_in_hour_in_public_chat = 0
        user_obj.start_chatting_in_public_chat = start_time
        session.commit()


def test_comment(client_one, client_two):
    message_text = str(time.time())
    client_one.send_message(message=message_text)
    time.sleep(2)
    with Session(engine) as session:
        message_obj = session.query(Message).filter_by(text=message_text).first()
    comment_text = str(time.time())
    client_two.add_comment(message_obj.id, comment=comment_text)
    response, chat_info = client_two.response, client_two.last_chat_info
    with Session(engine) as session:
        comment_obj = session.query(Comment).filter_by(text=comment_text).first()
        assert comment_obj
        assert comment_obj.message_id == message_obj.id
        assert response['info'] == 'Comment have created!'
        assert comment_obj.author.user_name == client_two.user_name


def test_private_message(client_one, client_two):
    message_text = str(time.time())
    client_one.send_message(message=message_text, receiver=client_two.user_name)
    time.sleep(3)
    with Session(engine) as session:
        message_obj = session.query(Message).filter_by(text=message_text).first()
        chat_obj = session.query(Chat).filter_by(id=message_obj.chat_id).first()
        assert chat_obj
        assert message_obj
    time.sleep(1)
    client_two.connect_to_chat(chat_name=client_one.user_name)
    assert client_two.response.get('unread_messages')
    assert client_two.response['unread_messages'][0]['message_text'] == message_text


def test_report(client_one, client_two):
    with Session(engine) as session:
        user_obj = session.query(User).filter_by(user_name=client_one.user_name).first()
        chat_obj = session.query(Chat).filter_by(name='public_chat').first()
        chat_user_obj = session.query(ChatUser).filter_by(
            chat_id=chat_obj.id
        ).filter_by(
            user_id=user_obj.id
        ).first()
        chat_user_obj.cautions = 2
        session.commit()
    time.sleep(2)
    client_two.report(report_on=client_one.user_name)
    time.sleep(2)
    message_text = str(time.time())
    client_one.send_message(message=message_text)
    response, chat_info = client_one.response, client_one.last_chat_info
    with Session(engine) as session:
        message_obj = session.query(Message).filter_by(text=message_text).first()
    assert message_obj is None
    assert response['warning'].startswith('You are banned!')
    with Session(engine) as session:
        user_obj = session.query(User).filter_by(user_name=client_one.user_name).first()
        chat_obj = session.query(Chat).filter_by(name='public_chat').first()
        chat_user_obj = session.query(ChatUser).filter_by(
            chat_id=chat_obj.id
        ).filter_by(
            user_id=user_obj.id
        ).first()
        assert chat_user_obj.banned
        assert chat_user_obj.banned_till > datetime.datetime.now()
        chat_user_obj.cautions = 0
        chat_user_obj.banned = False
        chat_user_obj.banned_till = None
        session.commit()
    time.sleep(2)
