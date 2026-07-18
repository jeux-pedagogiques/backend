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

# Import models to ensure they are registered in metadata
from app.models.quiz_session import QuizSession, QuizParticipant, QuizAttempt
from app.models.escape_room import EscapeRoom
from app.models.pitching import PitchingSession, PitchingTeam, PitchingVote, PitchingFeedback
from app.models.flashcard import FlashcardSet, Flashcard, FlashcardReview




@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(title="Artisan Jeux Pédagogiques API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4200"],
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

# Mount Socket.io ASGI application
from app.services.socket_service import socket_app
app.mount("/", socket_app)


@app.get("/")
def root():
    return {"status": "API is running"}
