from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Conversation, Message
from app.db.session import engine


def main():
    source_id = UUID(input("已有测试会话 UUID：").strip())

    # 创建独立测试会话，不修改原会话的消息。
    with Session(engine) as session, session.begin():
        source = session.get(Conversation, source_id)
        if source is None:
            raise SystemExit("会话不存在")

        conversation = Conversation(
            tenant_id=source.tenant_id,
            owner_user_id=source.owner_user_id,
            knowledge_base_id=source.knowledge_base_id,
            title="数据库并发锁验证",
        )
        session.add(conversation)
        session.flush()

        conversation_id = conversation.id
        tenant_id = conversation.tenant_id

    barrier = Barrier(2)

    def save_pair(label):
        with Session(engine) as session, session.begin():
            # 两个事务准备好以后，一起尝试获取会话锁。
            barrier.wait(timeout=10)

            session.execute(
                select(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == tenant_id,
                )
                .with_for_update()
            ).scalar_one()

            last_sequence = session.scalar(
                select(func.coalesce(func.max(Message.sequence_no), 0))
                .where(
                    Message.tenant_id == tenant_id,
                    Message.conversation_id == conversation_id,
                )
            )

            session.add_all(
                [
                    Message(
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        sequence_no=last_sequence + 1,
                        role="user",
                        content=f"测试问题 {label}",
                        answer_status=None,
                        citations=[],
                    ),
                    Message(
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        sequence_no=last_sequence + 2,
                        role="assistant",
                        content=f"测试拒答 {label}",
                        answer_status="insufficient_evidence",
                        citations=[],
                    ),
                ]
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(save_pair, label)
            for label in ("A", "B")
        ]
        for future in futures:
            future.result()

    with Session(engine) as session:
        messages = session.scalars(
            select(Message)
            .where(
                Message.tenant_id == tenant_id,
                Message.conversation_id == conversation_id,
            )
            .order_by(Message.sequence_no)
        ).all()

        assert [m.sequence_no for m in messages] == [1, 2, 3, 4]
        assert [m.role for m in messages] == [
            "user", "assistant", "user", "assistant"
        ]

        for start in (0, 2):
            question = messages[start]
            answer = messages[start + 1]
            assert question.content[-1] == answer.content[-1], (
                "同一轮的问题和回答没有保持相邻"
            )

        for message in messages:
            print(
                message.sequence_no,
                message.role,
                message.content,
            )

    print(f"数据库测试会话 ID：{conversation_id}")
    print("数据库并发锁检查通过")


if __name__ == "__main__":
    main()