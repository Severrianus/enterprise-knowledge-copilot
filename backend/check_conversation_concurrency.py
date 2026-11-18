from concurrent.futures import ThreadPoolExecutor
from getpass import getpass
from threading import Barrier

import httpx


BASE_URL = "http://127.0.0.1:8000"


def main():
    tenant_slug = input("企业标识：").strip()
    email = input("登录邮箱：").strip()
    password = getpass("登录密码：")

    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        response = client.post(
            "/auth/login",
            json={
                "tenant_slug": tenant_slug,
                "email": email,
                "password": password,
            },
        )
        response.raise_for_status()
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = client.get(
            "/knowledge-bases",
            headers=headers,
        )
        response.raise_for_status()
        knowledge_bases = response.json()

        if not knowledge_bases:
            raise SystemExit("当前账号没有可访问的知识库")

        print("\n当前账号可访问的知识库：")
        for kb in knowledge_bases:
            print(f"{kb['id']}  {kb['name']}")

        kb_id = input(
            "\n请从上面复制一个知识库 UUID："
        ).strip()

        visible_ids = {kb["id"] for kb in knowledge_bases}
        if kb_id not in visible_ids:
            raise SystemExit("输入的 UUID 不在上面的知识库列表中")

        # 创建独立会话，避免影响之前的测试记录。
        response = client.post(
            "/conversations",
            headers=headers,
            json={
                "knowledge_base_id": kb_id,
                "title": "并发消息序号验证",
            },
        )
        print("创建会话状态码：", response.status_code)
        print("创建会话响应：", response.text)
        response.raise_for_status()
        conversation_id = response.json()["id"]

        barrier = Barrier(2)

        def ask(question):
            # 每个线程使用独立客户端，同时开始请求。
            with httpx.Client(
                base_url=BASE_URL,
                headers=headers,
                timeout=120.0,
            ) as worker_client:
                barrier.wait(timeout=10)
                result = worker_client.post(
                    f"/conversations/{conversation_id}/ask",
                    json={"question": question, "limit": 5},
                )
                if result.is_error:
                    raise RuntimeError(
                        f"问题：{question}\n"
                        f"HTTP 状态码：{result.status_code}\n"
                        f"错误响应：{result.text}"
                    )

                return result.json()

        questions = [
            "员工申请年假需要提前多久？",
            "公司是否提供员工的一日三餐？",
        ]

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(ask, question)
                for question in questions
            ]
            for future in futures:
                result = future.result()
                print("问答状态：", result["status"])

        response = client.get(
            f"/conversations/{conversation_id}/messages",
            headers=headers,
            params={"after_sequence": 0, "limit": 100},
        )
        response.raise_for_status()
        messages = response.json()

        assert len(messages) == 4, (
            f"预期4条消息，实际为{len(messages)}条"
        )

        sequences = [message["sequence_no"] for message in messages]
        assert sequences == [1, 2, 3, 4], (
            f"消息序号异常：{sequences}"
        )

        roles = [message["role"] for message in messages]
        assert roles == ["user", "assistant", "user", "assistant"], (
            f"消息角色顺序异常：{roles}"
        )

        saved_questions = [
            message["content"]
            for message in messages
            if message["role"] == "user"
        ]
        assert sorted(saved_questions) == sorted(questions), (
            "保存的问题与提交的问题不一致"
        )

        for message in messages:
            print(
                message["sequence_no"],
                message["role"],
                message["content"],
            )

        print(f"验证会话 ID：{conversation_id}")
        print("并发消息序号检查通过")


if __name__ == "__main__":
    main()