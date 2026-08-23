"""
Pydantic 数据验证模型（Request / Response Schema）
"""
from typing import Optional, List, Dict, Any, Generic, TypeVar
from datetime import datetime
from pydantic import BaseModel, Field

T = TypeVar("T")


# ==========================================================
# 简历相关 Schema
# ==========================================================
class EducationBase(BaseModel):
    school: str = Field(..., max_length=200, description="学校名称")
    degree: Optional[str] = Field(None, max_length=100, description="学位")
    major: Optional[str] = Field(None, max_length=200, description="专业")
    start_date: Optional[str] = Field(None, max_length=50)
    end_date: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, description="描述")


class EducationCreate(EducationBase):
    pass


class Education(EducationBase):
    id: int
    resume_id: int

    class Config:
        from_attributes = True


class InternshipBase(BaseModel):
    company: str = Field(..., max_length=200, description="公司名称")
    position: Optional[str] = Field(None, max_length=200)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    location: Optional[str] = None
    highlights: Optional[List[str]] = Field(None, description="工作亮点列表")


class InternshipCreate(InternshipBase):
    pass


class Internship(InternshipBase):
    id: int
    resume_id: int

    class Config:
        from_attributes = True


class ProjectBase(BaseModel):
    name: str = Field(..., max_length=200, description="项目名称")
    role: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None
    highlights: Optional[List[str]] = None
    tech_stack: Optional[List[str]] = None
    link: Optional[str] = None


class ProjectCreate(ProjectBase):
    pass


class Project(ProjectBase):
    id: int
    resume_id: int

    class Config:
        from_attributes = True


class SkillBase(BaseModel):
    category: Optional[str] = Field(None, max_length=100)
    items: List[str] = Field(..., description="技能项列表")


class SkillCreate(SkillBase):
    pass


class Skill(SkillBase):
    id: int
    resume_id: int

    class Config:
        from_attributes = True


class ResumeBase(BaseModel):
    name: str = Field(..., max_length=100, description="姓名")
    title: Optional[str] = Field(None, max_length=200)
    avatar: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    github: Optional[str] = None
    blog: Optional[str] = None
    summary: Optional[str] = None


class ResumeCreate(ResumeBase):
    educations: Optional[List[EducationCreate]] = []
    internships: Optional[List[InternshipCreate]] = []
    projects: Optional[List[ProjectCreate]] = []
    skills: Optional[List[SkillCreate]] = []


class ResumeUpdate(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    avatar: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    github: Optional[str] = None
    blog: Optional[str] = None
    summary: Optional[str] = None


class Resume(ResumeBase):
    id: int
    educations: List[Education] = []
    internships: List[Internship] = []
    projects: List[Project] = []
    skills: List[Skill] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==========================================================
# 对话相关 Schema
# ==========================================================
class MessageBase(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str


class Message(MessageBase):
    id: int
    tokens_used: int = 0
    meta: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationBase(BaseModel):
    session_id: Optional[str] = None
    visitor_id: Optional[str] = None
    title: Optional[str] = None


class ConversationCreate(ConversationBase):
    pass


class Conversation(BaseModel):
    id: int
    session_id: str
    visitor_id: Optional[str] = None
    title: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    messages: List[Message] = []

    class Config:
        from_attributes = True


class ConversationBrief(BaseModel):
    """会话简要信息（用于会话列表）"""
    id: int
    session_id: str
    title: Optional[str]
    last_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ==========================================================
# 聊天请求 / 响应 Schema
# ==========================================================
class ChatRequest(BaseModel):
    """聊天请求体"""
    message: str = Field(..., min_length=1, description="用户消息")
    session_id: Optional[str] = Field(None, description="会话ID，不传则新建会话")
    visitor_id: Optional[str] = Field(None, description="访客标识")
    stream: bool = Field(False, description="是否流式响应")


class ChatResponse(BaseModel):
    """聊天响应（非流式）"""
    reply: str
    session_id: str
    conversation_id: int
    tokens_used: int = 0
    citations: Optional[List[str]] = Field(None, description="引用的简历片段标签")


class MemoryChunkBase(BaseModel):
    category: str
    key: Optional[str] = None
    content: str
    source: Optional[str] = None
    importance: int = 5


class MemoryChunkCreate(MemoryChunkBase):
    pass


class MemoryChunk(MemoryChunkBase):
    id: int
    access_count: int
    created_at: datetime

    class Config:
        from_attributes = True


# ==========================================================
# 通用响应
# ==========================================================
class ApiResponse(BaseModel, Generic[T]):
    """统一API响应封装（支持泛型）"""
    success: bool = True
    message: str = "ok"
    data: Optional[T] = None
    code: int = 0
