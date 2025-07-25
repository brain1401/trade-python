"""
데이터베이스 CRUD(Create, Read, Update, Delete) 함수
"""

from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from datetime import datetime
from sqlalchemy import and_
from hashlib import sha256

# SQLAlchemy 모델과 Pydantic 스키마를 임포트합니다.
# 참고: 실제 프로젝트에서는 models.py 또는 유사한 파일에 SQLAlchemy 모델이 정의되어 있어야 합니다.
# 여기서는 해당 모델이 존재한다고 가정합니다.
from ..models import db_models
from ..models import schemas


class CRUDTradeNews:
    async def get(self, db: AsyncSession, id: int) -> db_models.TradeNews | None:
        result = await db.execute(
            select(db_models.TradeNews).filter(db_models.TradeNews.id == id)
        )
        return result.scalars().first()

    async def get_multi(
        self, db: AsyncSession, *, skip: int = 0, limit: int = 100
    ) -> list[db_models.TradeNews]:
        result = await db.execute(select(db_models.TradeNews).offset(skip).limit(limit))
        return list(result.scalars().all())

    async def get_recent_trade_news(
        self, db: AsyncSession, since: datetime
    ) -> list[db_models.TradeNews]:
        """
        주어진 시간 이후에 생성된 모든 무역 뉴스를 조회.

        Args:
            db (AsyncSession): 데이터베이스 세션.
            since (datetime): 조회할 시작 시점.

        Returns:
            list[db_models.TradeNews]: 조회된 무역 뉴스 목록.
        """
        result = await db.execute(
            select(db_models.TradeNews)
            .filter(db_models.TradeNews.published_at >= since)
            .order_by(db_models.TradeNews.published_at.desc())
        )
        return list(result.scalars().all())

    async def create_multi(
        self, db: AsyncSession, *, news_items: list[schemas.TradeNewsCreate]
    ) -> list[db_models.TradeNews]:
        """
        여러 개의 새로운 무역 뉴스 항목을 데이터베이스에 비동기적으로 생성.
        """
        if not news_items:
            return []

        # DB 컬럼은 timezone-naive이므로, 입력된 datetime의 timezone 정보를 제거
        processed_news_items = []
        for item in news_items:
            update_data = {}
            if item.published_at and item.published_at.tzinfo:
                update_data["published_at"] = item.published_at.replace(tzinfo=None)
            if (
                hasattr(item, "fetched_at")
                and item.fetched_at
                and item.fetched_at.tzinfo
            ):
                update_data["fetched_at"] = item.fetched_at.replace(tzinfo=None)

            if update_data:
                processed_news_items.append(item.model_copy(update=update_data))
            else:
                processed_news_items.append(item)

        db_news_list = []
        for item in processed_news_items:
            dumped_item = item.model_dump()

            # HttpUrl 타입은 명시적으로 str으로 변환
            if dumped_item.get("source_url") is not None:
                dumped_item["source_url"] = str(dumped_item["source_url"])

            db_news = db_models.TradeNews(**dumped_item)
            db_news_list.append(db_news)

        db.add_all(db_news_list)
        await db.flush()
        # flush 후에 db_news_list의 각 인스턴스를 refresh하여 DB의 최신 상태를 반영
        for db_news in db_news_list:
            await db.refresh(db_news)
        return db_news_list


trade_news = CRUDTradeNews()


class CRUDUpdateFeed:
    async def get_by_bookmark_and_content(
        self, db: AsyncSession, *, user_id: int, target_value: str, content: str
    ) -> Optional[db_models.UpdateFeed]:
        """
        사용자 ID, 대상 값, 콘텐츠 내용을 기반으로 기존 업데이트 피드가 있는지 조회.
        중복된 내용의 업데이트 생성을 방지하기 위해 사용.
        """
        query = select(db_models.UpdateFeed).where(
            and_(
                db_models.UpdateFeed.user_id == user_id,
                db_models.UpdateFeed.target_value == target_value,
                db_models.UpdateFeed.content == content,
            )
        )
        result = await db.execute(query)
        return result.scalars().first()

    async def create_from_bookmark(
        self, db: AsyncSession, *, bookmark: db_models.Bookmark, summary: str
    ) -> db_models.UpdateFeed:
        """
        북마크 정보와 요약 내용을 바탕으로 새로운 모니터링 업데이트 피드를 생성.
        """
        db_feed = db_models.UpdateFeed(
            user_id=bookmark.user_id,
            feed_type=db_models.FeedType.POLICY_UPDATE,  # 모니터링으로 인한 생성은 정책 업데이트로 분류
            target_type=db_models.TargetType(bookmark.type.value),
            target_value=bookmark.target_value,
            title=f"'{bookmark.display_name}'에 대한 새로운 업데이트",
            content=summary,
            importance=db_models.ImportanceLevel.MEDIUM,
        )
        db.add(db_feed)
        await db.flush()
        await db.refresh(db_feed)
        return db_feed


update_feed = CRUDUpdateFeed()


async def get_active_bookmarks(db: AsyncSession) -> List[db_models.Bookmark]:
    """
    알림이 활성화된 모든 북마크를 데이터베이스에서 비동기적으로 조회.
    'monitoring_active' Computed 필드를 사용하도록 수정됨.
    """
    query = select(db_models.Bookmark).where(
        db_models.Bookmark.monitoring_active == True
    )
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_update_feed(
    db: AsyncSession, feed_data: schemas.UpdateFeedCreate
) -> db_models.UpdateFeed:
    """
    새로운 업데이트 피드를 데이터베이스에 비동기적으로 생성.
    `구현계획.md` v6.3 및 SQLAlchemy 2.0 비동기 모범 사례에 맞게 수정됨.
    """
    db_feed = db_models.UpdateFeed(
        user_id=feed_data.user_id,  # 스키마에 user_id를 포함하는 것이 더 일관성 있음
        feed_type=feed_data.feed_type,
        target_type=feed_data.target_type,
        target_value=feed_data.target_value,
        title=feed_data.title,
        content=feed_data.content,
        source_url=str(feed_data.source_url) if feed_data.source_url else None,
        importance=feed_data.importance,
    )
    db.add(db_feed)
    await db.flush()
    await db.refresh(db_feed)  # 서버에서 생성된 created_at 같은 필드까지 모두 로드
    return db_feed


class CRUDChat:
    async def get_session_by_uuid(
        self, db: AsyncSession, user_id: int, session_uuid_str: str
    ) -> db_models.ChatSession:
        """
        주어진 user_id와 session_uuid로 채팅 세션을 조회합니다.
        세션은 Spring Boot에 의해 생성되므로, 항상 존재한다고 가정합니다.
        세션이 존재하지 않으면 오류를 발생시킵니다.
        """
        if not session_uuid_str:
            raise ValueError("session_uuid는 필수입니다.")

        try:
            session_uuid = UUID(session_uuid_str)
        except (ValueError, TypeError):
            raise ValueError(f"유효하지 않은 UUID 형식입니다: {session_uuid_str}")

        # 기존 세션이 있는지 확인
        query = (
            select(db_models.ChatSession)
            .where(
                db_models.ChatSession.session_uuid == session_uuid,
                db_models.ChatSession.user_id == user_id,
            )
            .options(selectinload(db_models.ChatSession.messages))
        )
        result = await db.execute(query)
        session = result.scalars().first()

        if not session:
            # Spring Boot에서 세션을 생성하므로, 존재하지 않는 경우는 예외적인 상황
            raise ValueError(
                f"세션을 찾을 수 없습니다: user_id={user_id}, session_uuid={session_uuid_str}"
            )

        return session

    async def get_messages_by_session(
        self, db: AsyncSession, session_uuid: UUID
    ) -> List[db_models.ChatMessage]:
        """특정 세션의 모든 메시지를 생성 시간순으로 조회"""
        query = (
            select(db_models.ChatMessage)
            .where(db_models.ChatMessage.session_uuid == session_uuid)
            .order_by(db_models.ChatMessage.created_at)
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def create_message(
        self, db: AsyncSession, message_in: schemas.ChatMessageCreate
    ) -> db_models.ChatMessage:
        """새로운 채팅 메시지를 생성"""
        db_message = db_models.ChatMessage(**message_in.model_dump())
        db.add(db_message)
        await db.flush()
        await db.refresh(db_message)
        return db_message

    async def delete_messages_by_session_uuid(
        self, db: AsyncSession, session_uuid: UUID
    ) -> None:
        """특정 세션의 모든 메시지를 삭제"""
        from sqlalchemy import delete

        stmt = delete(db_models.ChatMessage).where(
            db_models.ChatMessage.session_uuid == session_uuid
        )
        await db.execute(stmt)


chat = CRUDChat()


class CRUDHscode:
    async def get_or_create(
        self, db: AsyncSession, code: str, description: str = ""
    ) -> db_models.Hscode:
        """
        주어진 코드로 Hscode를 찾거나, 없으면 새로 생성.
        """
        # 먼저 코드로 Hscode를 찾아봄
        result = await db.execute(
            select(db_models.Hscode).filter(db_models.Hscode.code == code)
        )
        instance = result.scalars().first()

        if instance:
            return instance

        # 없으면 새로 생성
        new_instance = db_models.Hscode(code=code, description=description)
        db.add(new_instance)
        await db.flush()
        await db.refresh(new_instance)
        return new_instance


hscode = CRUDHscode()


class CRUDDocumentV2:
    async def create_v2(
        self, db: AsyncSession, *, hscode_id: int, content: str, metadata: dict
    ) -> db_models.DocumentV2:
        """
        새로운 DocumentV2 객체를 생성.
        """
        # 내용 기반으로 고유 해시 생성
        content_hash = sha256(content.encode("utf-8")).hexdigest()

        # 동일한 해시를 가진 문서가 이미 있는지 확인
        result = await db.execute(
            select(db_models.DocumentV2).filter(
                db_models.DocumentV2.content_hash == content_hash
            )
        )
        existing_doc = result.scalars().first()
        if existing_doc:
            # 이미 존재하면 생성하지 않고 기존 객체 반환 또는 예외 처리
            # 여기서는 로깅 후 기존 객체 반환을 선택
            # logger.info(f"Document with hash {content_hash} already exists.")
            return existing_doc

        db_doc = db_models.DocumentV2(
            hscode_id=hscode_id,
            content=content,
            metadata=metadata,
            content_hash=content_hash,
        )
        db.add(db_doc)
        await db.flush()
        await db.refresh(db_doc)
        return db_doc


document = CRUDDocumentV2()
