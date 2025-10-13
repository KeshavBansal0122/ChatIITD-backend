from sqlmodel import Session, select
from sqlalchemy import desc
from . import models
from typing import List, Optional

# Use the shared engine exposed by models
ENGINE = models.ENGINE


def get_or_create_user(user_info: dict) -> models.User:
    with Session(ENGINE) as sess:
        stmt = select(models.User).where(models.User.email == user_info.get("email"))
        res = sess.exec(stmt).first()
        if res:
            return res
        email = user_info.get("email")
        if not email:
            raise ValueError("user_info must contain an email")
        user = models.User(email=email, name=user_info.get("name"), picture=user_info.get("picture"))
        sess.add(user)
        sess.commit()
        sess.refresh(user)
        return user


def create_chat(user_id: int, title: str | None = None) -> models.Chat:
    with Session(ENGINE) as sess:
        chat = models.Chat(user_id=user_id, title=title)
        sess.add(chat)
        sess.commit()
        sess.refresh(chat)
        return chat


def list_chats(user_id: int) -> List[models.Chat]:
    with Session(ENGINE) as sess:
        stmt = select(models.Chat).where(models.Chat.user_id == user_id).order_by(desc(models.Chat.created_at))
        return list(sess.exec(stmt).all())


def get_chat(chat_id: int) -> Optional[models.Chat]:
    with Session(ENGINE) as sess:
        return sess.get(models.Chat, chat_id)


def create_message(chat_id: int, sender: str, content: str) -> models.Message:
    with Session(ENGINE) as sess:
        msg = models.Message(chat_id=chat_id, sender=sender, content=content)
        sess.add(msg)
        sess.commit()
        sess.refresh(msg)
        return msg


def list_messages(chat_id: int) -> List[models.Message]:
    with Session(ENGINE) as sess:
        stmt = select(models.Message).where(models.Message.chat_id == chat_id).order_by(models.Message.created_at)
        return list(sess.exec(stmt).all())
