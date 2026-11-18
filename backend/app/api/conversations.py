from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, select

from app.api.auth import CurrentUser, get_current_user
from app.api.knowledge_bases import knowledge_base_visibility
from app.db.models import Conversation, KnowledgeBase, User
from app.db.session import engine

from app.api.knowledge_bases import (KnowledgeAnswerResponse, KnowledgeSearchRequest, ask_knowledge_base,)
from app.db.models import Message

router  = APIRouter(
    prefix="/conversations",
    tags=["conversations"],
)

class CreateConversationRequest(BaseModel):
    knowledge_base_id: UUID
    title: str = Field(
        default="新会话",
        min_length=1,
        max_length=200,
    )

class ConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    knowledge_base_id: UUID
    title: str
    created_at: datetime


@router.post("", status_code=201)
def create_conversation(
        body: CreateConversationRequest,
        current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ConversationSummary:
    title = body.title.strip()
    if not title:
        raise HTTPException(422, "Title must not be blank")

    with Session(engine) as session, session.begin():
        kb_id = session.scalar(
            select(KnowledgeBase.id).where(
                KnowledgeBase.id == body.knowledge_base_id,
                *knowledge_base_visibility(current_user),
            )
        )

        if kb_id is None:
            raise HTTPException(404, "KnowledgeBase not found")

        conversation = Conversation(
            tenant_id = current_user.tenant_id,
            owner_user_id = current_user.id,
            knowledge_base_id = kb_id,
            title = title,
        )

        session.add(conversation)
        session.flush()

        result = ConversationSummary.model_validate(conversation)

    return result

@router.get("")
def list_conversations(
        current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[ConversationSummary]:
    statement = (
        select(Conversation)
        .where(
            Conversation.tenant_id == current_user.tenant_id,
            Conversation.owner_user_id == current_user.id,
        )
        .order_by(
            Conversation.created_at.desc(),
            Conversation.id.desc()
        )
        .limit(100)
    )

    with Session(engine) as session:
        return [
            ConversationSummary.model_validate(conversation)
            for conversation in session.scalars(statement)
        ]


def require_owned_conversation(
        session: Session,
        conversation_id: UUID,
        current_user: CurrentUser,
        *,
        lock: bool=False,
):
    statement = (
        select(Conversation)
        .join(
            KnowledgeBase,
            (KnowledgeBase.id == Conversation.knowledge_base_id)
            & (KnowledgeBase.tenant_id == Conversation.tenant_id),
        )
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == current_user.tenant_id,
            Conversation.owner_user_id == current_user.id,
            *knowledge_base_visibility(current_user),
        )
    )

    if lock:
        statement = statement.with_for_update(of=Conversation)

    conversation = session.scalar(statement)

    if conversation is None:
        raise HTTPException(404, "Conversation not found")

    return conversation


@router.post("/{conversation_id}/ask")
def ask_conversation(
    conversation_id: UUID,
    body: KnowledgeSearchRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> KnowledgeAnswerResponse:
    with Session(engine) as session:
        conversation = require_owned_conversation(
            session,
            conversation_id,
            current_user,
        )
        kb_id = conversation.knowledge_base_id

    result = ask_knowledge_base(
        kb_id=kb_id,
        body=body,
        current_user=current_user,
    )

    with Session(engine) as session, session.begin():
        conversation = require_owned_conversation(
            session,
            conversation_id,
            current_user,
            lock=True,
        )
        if conversation.knowledge_base_id != kb_id:
            raise HTTPException(409, "Conversation knowledge base changed")

        last_sequence = session.scalar(
            select(func.coalesce(func.max(Message.sequence_no), 0))
            .where(
                Message.tenant_id == current_user.tenant_id,
                Message.conversation_id == conversation_id,
            )
        )

        session.add_all(
            [
                Message(
                    tenant_id=current_user.tenant_id,
                    conversation_id=conversation_id,
                    sequence_no=last_sequence + 1,
                    role="user",
                    content=body.question.strip(),
                    answer_status=None,
                    citations=[],
                ),
                Message(
                    tenant_id=current_user.tenant_id,
                    conversation_id=conversation_id,
                    sequence_no=last_sequence + 2,
                    role="assistant",
                    content=result.answer,
                    answer_status=result.status,
                    citations=[
                        citation.model_dump(mode="json")
                        for citation in result.citations
                    ],
                ),
            ]
        )

    return result


class MessageSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    answer_status: str | None
    citations: list[dict]
    created_at: datetime
    sequence_no: int


@router.get("/{conversation_id}/messages")
def list_messages(
    conversation_id: UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[MessageSummary]:
    with Session(engine) as session:
        require_owned_conversation(
            session,
            conversation_id,
            current_user,
        )

        statement = (
            select(Message)
            .where(
                Message.tenant_id == current_user.tenant_id,
                Message.conversation_id == conversation_id,
                Message.sequence_no > after_sequence,
            )
            .order_by(Message.sequence_no)
            .limit(limit)
        )

        return [
            MessageSummary.model_validate(message)
            for message in session.scalars(statement)
        ]