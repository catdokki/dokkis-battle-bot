from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from models import BattleRound, GifMessage, UserStats


class Base(DeclarativeBase):
    pass


class DbBattleRound(Base):
    __tablename__ = "battle_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_gif_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    gif_messages: Mapped[list["DbGifMessage"]] = relationship(
        back_populates="battle_round",
        cascade="all, delete-orphan",
    )


class DbGifMessage(Base):
    __tablename__ = "gif_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    battle_round_id: Mapped[int] = mapped_column(ForeignKey("battle_rounds.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    author_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    battle_round: Mapped[DbBattleRound] = relationship(back_populates="gif_messages")
    reactions: Mapped[list["DbGifReaction"]] = relationship(
        back_populates="gif_message",
        cascade="all, delete-orphan",
    )


class DbGifReaction(Base):
    __tablename__ = "gif_reactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gif_message_id: Mapped[int] = mapped_column(ForeignKey("gif_messages.id", ondelete="CASCADE"), nullable=False)
    emoji_key: Mapped[str] = mapped_column(String(255), nullable=False)
    reactor_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    gif_message: Mapped[DbGifMessage] = relationship(back_populates="reactions")


class DbUserStats(Base):
    __tablename__ = "user_stats"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    total_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_xp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rounds_joined: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rounds_won: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_win_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    best_win_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class DbMeta(Base):
    __tablename__ = "bot_meta"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class PostgresStorage:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url, future=True, pool_pre_ping=True)
        self._session_factory = sessionmaker(bind=self._engine, future=True, expire_on_commit=False)
        Base.metadata.create_all(self._engine)

    def _session(self) -> Session:
        return self._session_factory()

    def _get_active_db_round(self, session: Session) -> DbBattleRound | None:
        stmt = (
            select(DbBattleRound)
            .where(DbBattleRound.ended_at.is_(None))
            .order_by(DbBattleRound.id.desc())
        )
        return session.execute(stmt).scalar_one_or_none()

    def _next_round_number(self, session: Session, channel_id: int) -> int:
        stmt = select(func.max(DbBattleRound.round_number)).where(DbBattleRound.channel_id == channel_id)
        current = session.execute(stmt).scalar_one_or_none()
        return (current or 0) + 1

    def load_active_round(self) -> BattleRound | None:
        with self._session() as session:
            db_round = self._get_active_db_round(session)
            if db_round is None:
                return None

            participant_ids: set[int] = set()
            gif_messages: dict[int, GifMessage] = {}

            for db_gif in db_round.gif_messages:
                participant_ids.add(db_gif.author_id)
                emoji_reactors: dict[str, set[int]] = {}
                for reaction in db_gif.reactions:
                    emoji_reactors.setdefault(reaction.emoji_key, set()).add(reaction.reactor_user_id)

                gif_messages[db_gif.message_id] = GifMessage(
                    message_id=db_gif.message_id,
                    author_id=db_gif.author_id,
                    emoji_reactors=emoji_reactors,
                )

            return BattleRound(
                channel_id=db_round.channel_id,
                started_at=db_round.started_at,
                last_activity_at=db_round.last_activity_at,
                last_gif_user_id=db_round.last_gif_user_id,
                round_number=db_round.round_number,
                participant_ids=participant_ids,
                gif_messages=gif_messages,
                status_message_id=db_round.status_message_id,
            )

    def save_active_round(self, battle_round: BattleRound | None) -> None:
        with self._session() as session:
            db_round = self._get_active_db_round(session)

            if battle_round is None:
                if db_round is not None:
                    db_round.ended_at = datetime.now(timezone.utc)
                    session.commit()
                return

            if db_round is None:
                if battle_round.round_number <= 0:
                    battle_round.round_number = self._next_round_number(session, battle_round.channel_id)

                db_round = DbBattleRound(
                    channel_id=battle_round.channel_id,
                    round_number=battle_round.round_number,
                    started_at=battle_round.started_at,
                    last_activity_at=battle_round.last_activity_at,
                    last_gif_user_id=battle_round.last_gif_user_id,
                    status_message_id=battle_round.status_message_id,
                    ended_at=None,
                )
                session.add(db_round)
                session.flush()
            else:
                db_round.channel_id = battle_round.channel_id
                db_round.round_number = battle_round.round_number or db_round.round_number
                db_round.started_at = battle_round.started_at
                db_round.last_activity_at = battle_round.last_activity_at
                db_round.last_gif_user_id = battle_round.last_gif_user_id
                db_round.status_message_id = battle_round.status_message_id

                for existing in list(db_round.gif_messages):
                    session.delete(existing)
                session.flush()

            for gif_message in battle_round.gif_messages.values():
                db_gif = DbGifMessage(
                    battle_round_id=db_round.id,
                    message_id=gif_message.message_id,
                    author_id=gif_message.author_id,
                )
                session.add(db_gif)
                session.flush()

                for emoji_key, reactor_ids in gif_message.emoji_reactors.items():
                    for reactor_user_id in reactor_ids:
                        session.add(
                            DbGifReaction(
                                gif_message_id=db_gif.id,
                                emoji_key=emoji_key,
                                reactor_user_id=reactor_user_id,
                            )
                        )

            session.commit()

    def load_user_stats(self) -> dict[int, UserStats]:
        with self._session() as session:
            stmt = select(DbUserStats)
            rows = session.execute(stmt).scalars().all()
            return {
                row.user_id: UserStats(
                    user_id=row.user_id,
                    total_points=row.total_points,
                    total_xp=row.total_xp,
                    level=row.level,
                    rounds_joined=row.rounds_joined,
                    rounds_won=row.rounds_won,
                    current_win_streak=row.current_win_streak,
                    best_win_streak=row.best_win_streak,
                )
                for row in rows
            }

    def save_user_stats(self, stats_by_user_id: dict[int, UserStats]) -> None:
        with self._session() as session:
            for user_id, stats in stats_by_user_id.items():
                row = session.get(DbUserStats, user_id)
                if row is None:
                    row = DbUserStats(user_id=user_id)
                    session.add(row)

                row.total_points = stats.total_points
                row.total_xp = stats.total_xp
                row.level = stats.level
                row.rounds_joined = stats.rounds_joined
                row.rounds_won = stats.rounds_won
                row.current_win_streak = stats.current_win_streak
                row.best_win_streak = stats.best_win_streak

            session.commit()