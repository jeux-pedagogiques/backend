from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import create_db_and_tables
from app.routers.auth_router import router as auth_router
from app.routers.module_router import router as module_router
from app.routers.websocket_router import router as websocket_router
from app.routers.quiz_session_router import router as quiz_session_router
from app.routers.escape_room_router import router as escape_room_router
from app.routers.dashboard_router import router as dashboard_router
from app.routers.pitching_router import router as pitching_router
from app.routers.flashcard_router import router as flashcard_router
from app.routers.library_router import router as library_router
from app.routers.share_router import router as share_router
from app.routers.cas_etude_router import router as cas_etude_router
from app.routers.mindmap_router import router as mindmap_router
from app.routers.debat_router import router as debat_router
from app.routers.negociation_router import router as negociation_router
from app.routers.atelier_feedback_router import router as atelier_feedback_router
from app.routers.storytelling_router import router as storytelling_router
from app.services.socket_service import socket_app

# Import models to ensure they are registered in metadata


@asynccontextmanager
async def lifespan(app: FastAPI):
    from fastapi.concurrency import run_in_threadpool
    try:
        await run_in_threadpool(create_db_and_tables)
    except Exception as e:
        print(f"Warning: DB startup initialization error: {e}")
    yield


app = FastAPI(title="Artisan Jeux Pédagogiques API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(module_router)
app.include_router(websocket_router)
app.include_router(quiz_session_router)
app.include_router(escape_room_router)
app.include_router(dashboard_router)
app.include_router(pitching_router)
app.include_router(flashcard_router)
app.include_router(library_router)
app.include_router(share_router)
app.include_router(cas_etude_router)
app.include_router(mindmap_router)
app.include_router(debat_router)
app.include_router(negociation_router)
app.include_router(atelier_feedback_router)
app.include_router(storytelling_router)


# Mount Socket.io ASGI application
app.mount("/", socket_app)


@app.get("/")
def root():
    return {"status": "API is running"}
