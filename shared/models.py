from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("source_type", "external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)  # 'telegram', 'website_x'
    external_id: Mapped[str] = mapped_column(Text, nullable=False)  # tg_channel_id or url
    title: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    added_by: Mapped[Optional[int]] = mapped_column(BigInteger)     # tg_user_id
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    raw_messages: Mapped[list["RawMessage"]] = relationship(back_populates="source")


class RawMessage(Base):
    __tablename__ = "raw_messages"
    __table_args__ = (
        UniqueConstraint("source_id", "external_msg_id"),
        Index("idx_raw_messages_unparsed", "source_type", "received_at",
              postgresql_where="parsed_at IS NULL"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    external_msg_id: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    parsed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    source: Mapped["Source"] = relationship(back_populates="raw_messages")
    casting: Mapped[Optional["Casting"]] = relationship(back_populates="raw_message")


class Casting(Base):
    __tablename__ = "castings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    raw_message_id: Mapped[int] = mapped_column(ForeignKey("raw_messages.id"), nullable=False)
    text_hash: Mapped[Optional[str]] = mapped_column(Text, unique=True)  # dedup reposts
    location: Mapped[Optional[str]] = mapped_column(Text)
    project_type: Mapped[Optional[str]] = mapped_column(Text)            # 'film','theatre','ad','series'
    deadline: Mapped[Optional[date]] = mapped_column(Date)
    media_file_ids: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    classified_by: Mapped[Optional[str]] = mapped_column(Text)           # 'regex', 'llm'
    confidence: Mapped[Optional[int]] = mapped_column(SmallInteger)      # 0-100
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    raw_message: Mapped["RawMessage"] = relationship(back_populates="casting")
    vacancies: Mapped[list["Vacancy"]] = relationship(back_populates="casting")


class Vacancy(Base):
    __tablename__ = "vacancies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    casting_id: Mapped[int] = mapped_column(ForeignKey("castings.id", ondelete="CASCADE"), nullable=False)
    gender: Mapped[Optional[str]] = mapped_column(Text)                  # 'male', 'female', 'any'
    age_min: Mapped[Optional[int]] = mapped_column(SmallInteger)
    age_max: Mapped[Optional[int]] = mapped_column(SmallInteger)
    fee_max: Mapped[Optional[int]] = mapped_column(Integer)              # max fee in RUB
    fee_type: Mapped[Optional[str]] = mapped_column(Text)                # 'paid', 'free', 'unknown'
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    casting: Mapped["Casting"] = relationship(back_populates="vacancies")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    filters: Mapped[Optional["UserFilter"]] = relationship(back_populates="user", uselist=False)
    sent_log: Mapped[list["SentLog"]] = relationship(back_populates="user")


class UserFilter(Base):
    __tablename__ = "user_filters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    gender: Mapped[Optional[str]] = mapped_column(Text)
    age: Mapped[Optional[int]] = mapped_column(SmallInteger)
    location: Mapped[Optional[str]] = mapped_column(Text)
    project_types: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text))
    fee_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notify_immediately: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped["User"] = relationship(back_populates="filters")


class SentLog(Base):
    __tablename__ = "sent_log"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    casting_id: Mapped[int] = mapped_column(
        ForeignKey("castings.id", ondelete="CASCADE"), primary_key=True
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="sent_log")