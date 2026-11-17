from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "http://localhost:3000"

    # LLM (Groq — free tier)
    GROQ_API_KEY: str = ""
    GROQ_LLM_MODEL: str = "openai/gpt-oss-20b"

    # Embeddings (local, free — runs on this machine, no API key needed)
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384

    TOP_K: int = 5
    SIMILARITY_THRESHOLD: float = 0.8

    # Reranking (local cross-encoder, free)
    RERANK_ENABLED: bool = True
    RERANK_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    RERANK_CANDIDATES: int = 20

    # Query transformation (costs ONE extra LLM call per question when enabled).
    # Comma-separated default for /query. Empty = off (Phase 6 behavior).
    # Allowed: rewrite, expand, multi_query, hyde
    QUERY_TRANSFORMS: str = ""
    MULTI_QUERY_COUNT: int = 3
    
    # Multimodal ingestion (Phase 10)
    OCR_ENABLED: bool = True
    OCR_MIN_CONFIDENCE: float = 0.5      # OCR lines below this are discarded
    OCR_RENDER_DPI: int = 150            # resolution used to render scanned PDF pages for OCR
    OCR_MAX_PAGES: int = 20              # scanned pages OCR'd per document (OCR is slow on CPU)
    OCR_MAX_IMAGES: int = 15             # embedded images OCR'd per document
    TABLES_ENABLED: bool = True
    MAX_UPLOAD_MB: int = 25

    # Authentication & access control (Phase 15). Off by default so local
    # single-user development keeps working; production refuses to start without it.
    AUTH_REQUIRED: bool = False
    JWT_SECRET: str = ""                 # >= 32 random chars when auth is on
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    REGISTRATION_OPEN: bool = True       # the very first user can always register
    PASSWORD_MIN_LENGTH: int = 10
    PASSWORD_HASH_TIME_COST: int = 3     # Argon2id iterations
    PASSWORD_HASH_MEMORY_KIB: int = 65536

    # Rate limits (requests per minute, in-memory per process)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10
    RATE_LIMIT_LLM_PER_MINUTE: int = 30
    RATE_LIMIT_DEFAULT_PER_MINUTE: int = 300

    # Production runtime (Phase 16)
    INGEST_ASYNC: bool = False           # true: uploads are queued and a worker ingests them
    RUN_EMBEDDED_WORKER: bool = False    # true: the API process also runs one worker thread
    JOB_MAX_ATTEMPTS: int = 3
    JOB_RETRY_BASE_SECONDS: int = 10     # backoff = base * 2^(attempt-1)
    JOB_STALE_AFTER_SECONDS: int = 900   # a "running" job older than this is requeued
    WORKER_POLL_SECONDS: float = 2.0
    EMBED_CACHE_SIZE: int = 1024         # query embeddings kept in memory; 0 = off
    LOG_FORMAT: str = "text"             # "text" | "json"
    METRICS_TOKEN: str = ""              # Bearer token for /metrics; empty = open only when auth is off

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() in {"production", "prod"}

    @property
    def default_transforms(self) -> list[str]:
        return [t.strip().lower() for t in self.QUERY_TRANSFORMS.split(",") if t.strip()]


settings = Settings()