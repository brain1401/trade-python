from typing import List

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict
from sqlalchemy.ext.asyncio import AsyncSession


from app.db.crud import chat as crud_chat
from app.models import schemas
from app.models.db_models import ChatMessage


def _langchain_type_to_db_type(langchain_type: str) -> str:
    """LangChain 메시지 타입을 DB 메시지 타입으로 변환"""
    mapping = {
        "human": "USER",
        "ai": "AI",
        "system": "AI",  # 시스템 메시지도 AI로 취급
        "assistant": "AI",  # assistant는 ai와 동일
    }
    db_type = mapping.get(langchain_type.lower())
    if db_type is None:
        raise ValueError(f"지원되지 않는 LangChain 메시지 타입: {langchain_type}")
    return db_type


def _db_type_to_langchain_type(db_type: str) -> str:
    """DB 메시지 타입을 LangChain 메시지 타입으로 변환"""
    mapping = {"USER": "human", "AI": "ai"}
    langchain_type = mapping.get(db_type.upper())
    if langchain_type is None:
        raise ValueError(f"지원되지 않는 DB 메시지 타입: {db_type}")
    return langchain_type


async def _db_messages_to_langchain_messages(
    db_messages: List[ChatMessage],
) -> List[BaseMessage]:
    """SQLAlchemy 모델 리스트를 LangChain 메시지 객체 리스트로 변환"""
    dict_messages = []
    for msg in db_messages:
        dict_messages.append(
            {
                "type": _db_type_to_langchain_type(str(msg.message_type)),
                "data": {"content": str(msg.content)},
            }
        )
    return messages_from_dict(dict_messages)


class PostgresChatMessageHistory(BaseChatMessageHistory):
    """
    PostgreSQL 데이터베이스를 백엔드로 사용하는 LangChain의 채팅 기록 클래스.
    SQLAlchemy 비동기 세션을 사용하여 DB와 상호작용하도록 수정됨.
    """

    def __init__(self, db: AsyncSession, user_id: int, session: schemas.ChatSession):
        """
        초기화 시 DB 세션, 사용자 ID, 그리고 이미 생성/조회된 ChatSession 객체를 받음.
        """
        self.db = db
        self.user_id = user_id
        # 외부에서 주입된, DB와 동기화된 세션 객체를 사용
        self.session_uuid = session.session_uuid

    @property
    def messages(self) -> List[BaseMessage]:
        """[사용주의] 동기적인 메시지 조회. LangChain의 async 흐름에서는 사용되지 않아야 함."""
        raise NotImplementedError(
            "동기 `messages` 속성은 지원되지 않습니다. "
            "대신 `aget_messages`를 사용하십시오."
        )

    @messages.setter
    def messages(self, messages: List[BaseMessage]) -> None:
        """[사용주의] 동기적인 메시지 설정. LangChain의 async 흐름에서는 사용되지 않아야 함."""
        raise NotImplementedError(
            "동기 `messages` 속성 설정은 지원되지 않습니다. "
            "대신 `aadd_messages`를 사용하십시오."
        )

    async def aget_messages(self) -> List[BaseMessage]:
        """DB에서 비동기적으로 메시지를 조회."""
        db_messages = await crud_chat.get_messages_by_session(
            db=self.db, session_uuid=self.session_uuid
        )
        return await _db_messages_to_langchain_messages(db_messages)

    async def aadd_message(self, message: BaseMessage) -> None:
        """메시지 하나를 DB에 비동기적으로 추가"""
        message_data = message_to_dict(message)
        message_create = schemas.ChatMessageCreate(
            session_uuid=self.session_uuid,
            message_type=_langchain_type_to_db_type(message_data["type"]),
            content=message_data["data"]["content"],
        )
        await crud_chat.create_message(db=self.db, message_in=message_create)

    async def aadd_messages(self, messages: List[BaseMessage]) -> None:
        """여러 메시지를 DB에 비동기적으로 추가"""
        for message in messages:
            await self.aadd_message(message)

    async def aclear(self) -> None:
        """DB에서 해당 세션의 메시지를 비동기적으로 삭제."""
        # LangChain의 RunnableWithMessageHistory는 clear를 직접 호출하지 않지만,
        # 일관성을 위해 비동기 버전으로 구현
        await crud_chat.delete_messages_by_session_uuid(
            db=self.db, session_uuid=self.session_uuid
        )

    # ----------------------------------------------------------------
    # 기존 동기 메서드들은 에러를 발생시키도록 남겨두거나, 삭제합니다.
    # 여기서는 명시적으로 Not ImplementdError를 발생시켜 잘못된 사용을 방지합니다.
    # ----------------------------------------------------------------
    def add_message(self, message: BaseMessage) -> None:
        raise NotImplementedError(
            "동기 `add_message`는 지원되지 않습니다. "
            "대신 `aadd_message`를 사용하십시오."
        )

    def clear(self) -> None:
        raise NotImplementedError(
            "동기 `clear`는 지원되지 않습니다. " "대신 `aclear`를 사용하십시오."
        )
