import os

from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer,
                        SmallInteger, String, Text, create_engine)
from sqlalchemy.orm import Session, declarative_base, relationship
from sqlalchemy.sql import func
from sqlalchemy_utils.types.choice import ChoiceType

from enums import ChatType


basedir = os.path.abspath(os.path.dirname(__file__))
engine = create_engine('sqlite:///' + os.path.join(basedir, 'data.sqlite'), echo=True)

Base = declarative_base()


class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text(length=255), nullable=False)
    pub_date = Column(DateTime(timezone=True), server_default=func.now())
    author_id = Column(Integer, ForeignKey('users.id'))
    chat_id = Column(Integer, ForeignKey('chats.id'))
    comments = relationship('Comment', backref='message', cascade="all, delete")

    def __str__(self):
        return self.text[:15]


class Comment(Base):
    __tablename__ = 'comments'
    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey('messages.id'))
    author_id = Column(Integer, ForeignKey('users.id'))
    text = Column(Text(length=255), nullable=False)
    created = Column(DateTime(timezone=True), server_default=func.now())

    def __str__(self):
        return self.text[:15]


class ChatUser(Base):
    __tablename__ = 'chats_users'
    chat_id = Column(Integer, ForeignKey('chats.id'), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    last_connect = Column(DateTime(timezone=True))
    cautions = Column(SmallInteger, default=0)
    banned = Column(Boolean, default=False)
    banned_till = Column(DateTime(timezone=True), nullable=True)


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_name = Column(String, unique=True, nullable=False)
    token = Column(String, unique=True, nullable=False)
    comments = relationship('Comment', backref='author', lazy='dynamic', cascade="all, delete")
    messages = relationship('Message', backref='author', lazy='dynamic', cascade="all, delete")
    chats = relationship('Chat', secondary='chats_users', back_populates='users')
    messages_in_hour_in_public_chat = Column(Integer, default=0)
    start_chatting_in_public_chat = Column(DateTime(timezone=True), server_default=func.now())

    def __str__(self):
        return self.user_name


class Chat(Base):
    __tablename__ = 'chats'
    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(ChoiceType(ChatType, impl=String()))
    name = Column(String, nullable=False)
    messages = relationship('Message', backref='chat', lazy='dynamic', cascade='all, delete')
    users = relationship('User', secondary='chats_users', back_populates='chats', lazy='dynamic')
    created = Column(DateTime(timezone=True), server_default=func.now())

    def __str__(self):
        return self.name


if __name__ == '__main__':
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        public_chat = Chat(
            name='public_chat',
            type=ChatType.PUBLIC
        )
        session.add(public_chat)
        session.commit()
