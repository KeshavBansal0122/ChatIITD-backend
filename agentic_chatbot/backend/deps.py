from sqlmodel import create_engine, Session
from . import models

ENGINE = create_engine(models.DATABASE_URL, echo=False)


def get_session():
    with Session(ENGINE) as sess:
        yield sess
