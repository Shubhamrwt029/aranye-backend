"""
Seed the first admin user.
Usage: uv run python scripts/seed_admin.py
"""

import asyncio
import sys

from app.core.database import AsyncSessionLocal
from app.services.auth_service import AuthService


async def seed_admin(email: str, password: str, name: str = "Admin") -> None:
    async with AsyncSessionLocal() as session:
        admin = await AuthService.create_admin_user(session, email, password, name)
        await session.commit()
        print(f"Admin created: {admin.email} (id: {admin.id})")


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "admin@aranye.com"
    password = sys.argv[2] if len(sys.argv) > 2 else "Admin@12345"
    asyncio.run(seed_admin(email, password))
