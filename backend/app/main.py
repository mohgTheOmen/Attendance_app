import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db import SessionLocal
from app.models import Role, User
from app.routers import admin, attendances, auth, events, ocr
from app.security import hash_password

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("attendance")


def seed_admin() -> None:
    """Create the first admin from settings if no admin exists yet."""
    s = get_settings()
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.role == Role.admin).limit(1)):
            return
        db.add(User(
            email=s.admin_email.lower(), full_name=s.admin_full_name,
            password_hash=hash_password(s.admin_password), role=Role.admin,
        ))
        db.commit()
        log.info("Seeded admin account %s", s.admin_email)


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings().upload_dir.mkdir(parents=True, exist_ok=True)
    try:
        seed_admin()
    except SQLAlchemyError as exc:
        log.error("Could not seed admin (did you run `alembic upgrade head`?): %s", exc)
    yield


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

for r in (auth.router, events.router, attendances.router, admin.router, ocr.router):
    app.include_router(r, prefix="/api")

Instrumentator(excluded_handlers=["/metrics", "/health"]).instrument(app).expose(
    app, include_in_schema=False
)


@app.get("/health", tags=["meta"])
def health():
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}
    except SQLAlchemyError:
        return {"status": "degraded", "database": "unreachable"}
