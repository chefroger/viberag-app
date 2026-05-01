"""
VibeRAG Pydantic Schemas

统一管理所有请求/响应模型
"""
from app.schemas.common import (
    BaseResponse,
    PaginatedResponse,
    ErrorResponse,
    HealthResponse,
    ScanProgressResponse,
)
from app.schemas.library import (
    CreateLibraryRequest,
    LibraryResponse,
    FileResponse,
    ChunkResponse,
    FileDetailResponse,
)
from app.schemas.customer import (
    CustomerCreate,
    CustomerUpdate,
    CustomerResponse,
    CustomerListItem,
    DuplicateCheckRequest,
    DuplicateMatch,
    LibraryRef,
    ProfileSuggestion,
    ProfileSuggestionReview,
    ProspectCreate,
    ProspectUpdate,
    StageUpgradeRequest,
)
from app.schemas.session import (
    StartSessionRequest,
    TurnRequest,
    TurnItem,
    SummaryDetail,
)
from app.schemas.ask import (
    AskRequest,
    SourceItem,
    LetterRequest,
    ScriptRequest,
    QuoteRequest,
    FollowupRequest,
)

__all__ = [
    # common
    "BaseResponse",
    "PaginatedResponse",
    "ErrorResponse",
    "HealthResponse",
    "ScanProgressResponse",
    # library
    "CreateLibraryRequest",
    "LibraryResponse",
    "FileResponse",
    "ChunkResponse",
    "FileDetailResponse",
    # customer
    "CustomerCreate",
    "CustomerUpdate",
    "CustomerResponse",
    "CustomerListItem",
    "DuplicateCheckRequest",
    "DuplicateMatch",
    "LibraryRef",
    "ProfileSuggestion",
    "ProfileSuggestionReview",
    "ProspectCreate",
    "ProspectUpdate",
    "StageUpgradeRequest",
    # session
    "StartSessionRequest",
    "TurnRequest",
    "TurnItem",
    "SummaryDetail",
    # ask
    "AskRequest",
    "SourceItem",
    "LetterRequest",
    "ScriptRequest",
    "QuoteRequest",
    "FollowupRequest",
]
