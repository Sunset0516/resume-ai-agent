"""
数据库模型定义
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, JSON
from sqlalchemy.orm import relationship
from datetime import datetime

from .database import Base


class Resume(Base):
    """个人简历主表"""
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="姓名")
    title = Column(String(200), comment="求职目标 / 头衔")
    avatar = Column(String(500), comment="头像URL")
    email = Column(String(200), comment="邮箱")
    phone = Column(String(50), comment="电话")
    location = Column(String(200), comment="所在地")
    github = Column(String(500), comment="GitHub链接")
    blog = Column(String(500), comment="个人博客")
    summary = Column(Text, comment="个人简介 / 自我评价")
    owner_key = Column(String(100), index=True, comment="所有者标识（浏览器隔离用）")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    educations = relationship("Education", back_populates="resume", cascade="all, delete-orphan")
    internships = relationship("Internship", back_populates="resume", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="resume", cascade="all, delete-orphan")
    skills = relationship("Skill", back_populates="resume", cascade="all, delete-orphan")


class Education(Base):
    """教育经历"""
    __tablename__ = "educations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"), nullable=False)
    school = Column(String(200), nullable=False, comment="学校名称")
    degree = Column(String(100), comment="学位")
    major = Column(String(200), comment="专业")
    start_date = Column(String(50), comment="开始时间")
    end_date = Column(String(50), comment="结束时间")
    description = Column(Text, comment="描述（GPA、奖学金、课程等）")

    resume = relationship("Resume", back_populates="educations")


class Internship(Base):
    """实习经历"""
    __tablename__ = "internships"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"), nullable=False)
    company = Column(String(200), nullable=False, comment="公司名称")
    position = Column(String(200), comment="职位")
    start_date = Column(String(50), comment="开始时间")
    end_date = Column(String(50), comment="结束时间")
    location = Column(String(200), comment="工作地点")
    highlights = Column(JSON, comment="工作亮点/成就列表")

    resume = relationship("Resume", back_populates="internships")


class Project(Base):
    """项目经验"""
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"), nullable=False)
    name = Column(String(200), nullable=False, comment="项目名称")
    role = Column(String(100), comment="担任角色")
    start_date = Column(String(50), comment="开始时间")
    end_date = Column(String(50), comment="结束时间")
    description = Column(Text, comment="项目描述")
    highlights = Column(JSON, comment="项目亮点/成果")
    tech_stack = Column(JSON, comment="技术栈")
    link = Column(String(500), comment="项目链接")

    resume = relationship("Resume", back_populates="projects")


class Skill(Base):
    """技能"""
    __tablename__ = "skills"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"), nullable=False)
    category = Column(String(100), comment="技能分类（编程语言、框架、工具等）")
    items = Column(JSON, comment="技能项列表")

    resume = relationship("Resume", back_populates="skills")


class Conversation(Base):
    """对话会话表（持久记忆核心）"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String(100), unique=True, index=True, nullable=False, comment="会话ID")
    owner_key = Column(String(100), index=True, comment="简历所有者key")
    visitor_id = Column(String(100), index=True, comment="访客ID（用于区分不同用户）")
    title = Column(String(200), comment="会话标题")
    summary = Column(Text, comment="早期对话摘要（记忆压缩结果）")
    summary_upto_id = Column(Integer, default=0, comment="摘要已覆盖到的最后一条消息ID")
    is_active = Column(Boolean, default=True, comment="是否活跃")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联消息
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan",
                            order_by="Message.created_at")


class Message(Base):
    """消息记录表（持久记忆的消息粒度）"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(20), nullable=False, comment="角色：user / assistant / system")
    content = Column(Text, nullable=False, comment="消息内容")
    tokens_used = Column(Integer, default=0, comment="消耗Token数")
    meta = Column(JSON, comment="元数据（引用的简历片段、记忆ID等）")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    conversation = relationship("Conversation", back_populates="messages")


class ResumeChunk(Base):
    """简历检索片段（结构化分块 + 向量缓存）"""
    __tablename__ = "resume_chunks"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"), nullable=False, index=True)
    owner_key = Column(String(100), index=True, comment="所有者标识")
    chunk_key = Column(String(50), index=True, nullable=False, comment="稳定片段ID，如 edu:3 / proj:7")
    section = Column(String(50), nullable=False, comment="章节：基本信息/教育经历/实习经历/项目经验/技能")
    title = Column(String(200), comment="条目名称（学校/公司/项目名）")
    content = Column(Text, nullable=False, comment="片段正文")
    embedding = Column(JSON, comment="向量（失败时为空，降级为关键词检索）")
    resume_version = Column(DateTime, comment="生成该片段时的简历更新时间，用于缓存失效判断")
    created_at = Column(DateTime, default=datetime.utcnow)


class MemoryChunk(Base):
    """长期记忆片段（可跨会话复用的记忆）"""
    __tablename__ = "memory_chunks"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    category = Column(String(50), index=True, comment="记忆分类：resume_fact / user_preference / qa_pair")
    key = Column(String(200), index=True, comment="记忆关键词/标签")
    content = Column(Text, nullable=False, comment="记忆内容")
    owner_key = Column(String(100), index=True, comment="所有者标识")
    source = Column(String(200), comment="来源：admin / conversation:xxx")
    importance = Column(Integer, default=5, comment="重要程度 1-10")
    access_count = Column(Integer, default=0, comment="被引用次数")
    last_accessed = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
