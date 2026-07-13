# Import all models here so they are registered with SQLModel.metadata.
from app.models.user import User  # noqa: F401
from app.models.module_analysis import ModuleAnalysis  # noqa: F401
from app.models.live_session import LiveSession, LiveSessionParticipant, ScheduledMeeting  # noqa: F401


