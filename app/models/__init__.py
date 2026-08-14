# Import all models here so they are registered with SQLModel.metadata.
from app.models.user import User  # noqa: F401
from app.models.module_analysis import ModuleAnalysis  # noqa: F401
from app.models.live_session import LiveSession, LiveSessionParticipant, ScheduledMeeting  # noqa: F401
from app.models.escape_room import EscapeRoom  # noqa: F401
from app.models.pitching import PitchingSession, PitchingTeam, PitchingVote, PitchingFeedback  # noqa: F401
from app.models.flashcard import FlashcardSet, Flashcard, FlashcardReview  # noqa: F401
from app.models.quiz import Quiz  # noqa: F401
from app.models.library_item import LibraryItem  # noqa: F401
from app.models.game_share import GameShare, GameResult  # noqa: F401
from app.models.cas_etude import CasEtude, EquipeCasEtude, RoleAssignment, DecisionEquipe  # noqa: F401
from app.models.mindmap import MindMap, MindMapNode  # noqa: F401
from app.models.debat import Debat, ParticipantDebat, PriseDeParole, NoteObservateur  # noqa: F401
from app.models.negociation import Negociation, GroupeNegociation, AssignationPersonnage, AccordFinal  # noqa: F401
from app.models.atelier_feedback import AtelierFeedback, PresentationAtelier, FeedbackRecu  # noqa: F401




