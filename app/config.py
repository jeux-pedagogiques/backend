import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# AI Model API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GITHUB_MODELS_API_KEY = os.getenv("GITHUB_MODELS_API_KEY")

# Email / Mailing Configuration
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "benelhaj.oussema@gmail.com")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "ekyx vbqx akrh hjzs")
MAIL_FROM = os.getenv("MAIL_FROM", "benelhaj.oussema@gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", "ESPRIT AI")

