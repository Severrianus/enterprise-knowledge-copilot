from getpass import getpass

from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Tenant, User
from app.db.session import engine


def main():
    tenant_slug = input("当前用户的企业标识：").strip().lower()
    source_email = input("当前用户的邮箱：").strip().lower()
    test_email = input("新测试账号邮箱：").strip().lower()

    if not test_email or test_email == source_email:
        raise SystemExit("请为测试账号填写不同的邮箱")

    password = getpass("新测试账号密码（至少12位）：")
    if len(password) < 12:
        raise SystemExit("密码至少需要12位")

    password_hash = PasswordHash.recommended().hash(password)

    with Session(engine) as session, session.begin():
        source_user = session.scalar(
            select(User)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(
                Tenant.slug == tenant_slug,
                Tenant.status == "ACTIVE",
                User.email == source_email,
                User.status == "ACTIVE",
            )
        )
        if source_user is None:
            raise SystemExit("没有找到当前用户，请检查企业标识和邮箱")

        existing_user = session.scalar(
            select(User.id).where(
                User.tenant_id == source_user.tenant_id,
                User.email == test_email,
            )
        )
        if existing_user is not None:
            raise SystemExit("测试账号已存在，本次没有修改其密码")

        test_user = User(
            tenant_id=source_user.tenant_id,
            department_id=source_user.department_id,
            email=test_email,
            display_name="会话隔离测试用户",
            password_hash=password_hash,
            can_upload_documents=False,
            status="ACTIVE",
        )
        session.add(test_user)
        session.flush()

        print(f"测试用户 ID：{test_user.id}")

    print("测试账号创建成功")


if __name__ == "__main__":
    main()