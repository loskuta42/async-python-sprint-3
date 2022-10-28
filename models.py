import os

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, SmallInteger, Boolean, ForeignKey, Table
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.sql import func
from sqlalchemy_utils.types.choice import ChoiceType

basedir = os.path.abspath(os.path.dirname(__file__))
engine = create_engine('sqlite:///' + os.path.join(basedir, 'data.sqlite'), echo=True)

Base = declarative_base()


class Message(Base):
    __tablename__ = 'massages'
    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text(length=255), nullable=False)
    pub_date = Column(DateTime(timezone=True), server_default=func.now())
    author_id = Column(Integer, ForeignKey('users.id'))
    chat_id = Column(Integer, ForeignKey('chats.id'))
    comments = relationship('Comment', backref='massage', cascade="all, delete")

    def __str__(self):
        return self.text[:15]


class Comment(Base):
    __tablename__ = 'comments'
    id = Column(Integer, primary_key=True, autoincrement=True)
    massage_id = Column(Integer, ForeignKey('massages.id'))
    author_id = Column(Integer, ForeignKey('users.id'))
    text = Column(Text(length=255), nullable=False)
    created = Column(DateTime(timezone=True), server_default=func.now())

    def __str__(self):
        return self.text[:15]


class ChatUser(Base):
    __tablename__ = 'chats_users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    last_connect = Column(DateTime(timezone=True))
    user_id = Column(Integer, ForeignKey('users.id'))
    chat_id = Column(Integer, ForeignKey('chats.id'))


# users_chats = Table(
#     'users_chats',
#     Base.metadata,
#     Column('chat_id', ForeignKey('chats.id'), primary_key=True),
#     Column('user_id', ForeignKey('users.id'), primary_key=True)
# )


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_name = Column(String, unique=True, nullable=False)
    token = Column(String, unique=True, nullable=False)
    comments = relationship('Comment', backref='author', lazy='dynamic', cascade="all, delete")
    messages = relationship('Message', backref='author', lazy='dynamic', cascade="all, delete")
    chats = relationship('Chat', secondary='chats_users', back_populates='users')
    warnings = Column(SmallInteger, default=0)
    banned = Column(Boolean, default=False)
    banned_till = Column(DateTime(timezone=True), nullable=True)

    def __str__(self):
        return self.user_name


class Chat(Base):
    TYPES = [
        ('private', 'Private'),
        ('chanel', 'Chanel'),
        ('public', 'Public')
    ]
    __tablename__ = 'chats'
    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(ChoiceType(TYPES))
    name = Column(String, nullable=False)
    messages = relationship('Message', backref='chat', lazy='dynamic', cascade='all, delete')
    users = relationship('User', secondary='chats_users', back_populates='chats', lazy='dynamic')


Base.metadata.create_all(engine)
