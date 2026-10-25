"""
简历数据 CRUD 服务（按 owner_key 隔离）
"""
import logging
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session

from ..models import Resume, Education, Internship, Project, Skill
from ..schemas import ResumeCreate, ResumeUpdate, EducationCreate, InternshipCreate, ProjectCreate, SkillCreate

logger = logging.getLogger(__name__)


class ResumeCRUD:
    """简历增删查改（按 owner_key 隔离）"""

    def __init__(self, db: Session, owner_key: str | None = None):
        self.db = db
        self.owner_key = owner_key

    # ------------------------------------------------------------------
    # 简历主表
    # ------------------------------------------------------------------
    def get_default(self) -> Optional[Resume]:
        """获取当前 owner 的默认简历；若当前owner无简历则回退到最新公开简历"""
        q = self.db.query(Resume)
        if self.owner_key:
            owned = q.filter(Resume.owner_key == self.owner_key).order_by(Resume.updated_at.desc()).first()
            if owned:
                return owned
            orphan = q.filter((Resume.owner_key.is_(None)) | (Resume.owner_key == "")).order_by(Resume.id.asc()).first()
            if orphan:
                orphan.owner_key = self.owner_key
                self.db.commit()
                self.db.refresh(orphan)
                return orphan
            return q.order_by(Resume.updated_at.desc()).first()
        return q.order_by(Resume.updated_at.desc()).first()

    def get(self, resume_id: int) -> Optional[Resume]:
        r = self.db.get(Resume, resume_id)
        if not r:
            return None
        if self.owner_key and r.owner_key and r.owner_key != self.owner_key:
            r.owner_key = self.owner_key
            self.db.commit()
            self.db.refresh(r)
        return r

    def list_all(self) -> List[Resume]:
        q = self.db.query(Resume)
        if self.owner_key:
            owned = q.filter(Resume.owner_key == self.owner_key).all()
            if owned:
                return owned
            latest = q.order_by(Resume.updated_at.desc()).first()
            return [latest] if latest else []
        return q.order_by(Resume.updated_at.desc()).all()

    def create(self, data: ResumeCreate) -> Resume:
        """创建完整简历（含所有子表）"""
        resume = Resume(
            name=data.name,
            title=data.title,
            avatar=data.avatar,
            email=data.email,
            phone=data.phone,
            location=data.location,
            github=data.github,
            blog=data.blog,
            summary=data.summary,
            owner_key=self.owner_key,
        )
        self.db.add(resume)
        self.db.flush()

        for edu in data.educations or []:
            self.db.add(Education(resume_id=resume.id, **edu.model_dump()))
        for it in data.internships or []:
            self.db.add(Internship(resume_id=resume.id, **it.model_dump()))
        for pj in data.projects or []:
            self.db.add(Project(resume_id=resume.id, **pj.model_dump()))
        for sk in data.skills or []:
            self.db.add(Skill(resume_id=resume.id, **sk.model_dump()))

        self.db.commit()
        self.db.refresh(resume)
        logger.info(f"[ResumeCRUD] 创建简历 id={resume.id} name={resume.name} owner_key={self.owner_key}")
        return resume

    def update(self, resume_id: int, data: ResumeUpdate) -> Optional[Resume]:
        resume = self.db.get(Resume, resume_id)
        if not resume:
            return None
        if self.owner_key and resume.owner_key and resume.owner_key != self.owner_key:
            resume.owner_key = self.owner_key
        update_data = data.model_dump(exclude_unset=True)
        for k, v in update_data.items():
            setattr(resume, k, v)
        resume.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(resume)
        return resume

    def delete(self, resume_id: int) -> bool:
        resume = self.db.get(Resume, resume_id)
        if not resume:
            return False
        self.db.delete(resume)
        self.db.commit()
        return True

    # ------------------------------------------------------------------
    # 子表操作
    # ------------------------------------------------------------------
    def add_education(self, resume_id: int, edu: EducationCreate) -> Optional[Education]:
        if not self.db.get(Resume, resume_id):
            return None
        e = Education(resume_id=resume_id, **edu.model_dump())
        self.db.add(e)
        self._touch_resume(resume_id)
        self.db.commit()
        self.db.refresh(e)
        return e

    def add_internship(self, resume_id: int, it: InternshipCreate) -> Optional[Internship]:
        if not self.db.get(Resume, resume_id):
            return None
        obj = Internship(resume_id=resume_id, **it.model_dump())
        self.db.add(obj)
        self._touch_resume(resume_id)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def add_project(self, resume_id: int, pj: ProjectCreate) -> Optional[Project]:
        if not self.db.get(Resume, resume_id):
            return None
        obj = Project(resume_id=resume_id, **pj.model_dump())
        self.db.add(obj)
        self._touch_resume(resume_id)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def add_skill(self, resume_id: int, sk: SkillCreate) -> Optional[Skill]:
        if not self.db.get(Resume, resume_id):
            return None
        obj = Skill(resume_id=resume_id, **sk.model_dump())
        self.db.add(obj)
        self._touch_resume(resume_id)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def _touch_resume(self, resume_id: int):
        r = self.db.get(Resume, resume_id)
        if r:
            r.updated_at = datetime.utcnow()
            self.db.flush()

    # ------------------------------------------------------------------
    # 导出简历为纯文本（喂给 LLM）
    # ------------------------------------------------------------------
    def dump_resume_text(self, resume: Resume) -> str:
        """把简历数据序列化为结构化纯文本，供 LLM 检索"""
        lines = []
        lines.append(f"【基本信息】")
        lines.append(f"姓名: {resume.name}")
        if resume.title:
            lines.append(f"求职意向/头衔: {resume.title}")
        contact = []
        if resume.email:
            contact.append(f"邮箱: {resume.email}")
        if resume.phone:
            contact.append(f"电话: {resume.phone}")
        if resume.location:
            contact.append(f"所在地: {resume.location}")
        if resume.github:
            contact.append(f"GitHub: {resume.github}")
        if resume.blog:
            contact.append(f"博客: {resume.blog}")
        if contact:
            lines.append("联系方式: " + " | ".join(contact))
        if resume.summary:
            lines.append(f"\n个人简介:\n{resume.summary}")

        if resume.educations:
            lines.append("\n【教育经历】")
            for i, e in enumerate(resume.educations, 1):
                date = f" ({e.start_date or '?'}-{e.end_date or '至今'})"
                lines.append(f"{i}. {e.school}{date}")
                if e.degree or e.major:
                    lines.append(f"   {e.degree or ''} · {e.major or ''}")
                if e.description:
                    lines.append(f"   描述: {e.description}")

        if resume.internships:
            lines.append("\n【实习经历】")
            for i, it in enumerate(resume.internships, 1):
                date = f" ({it.start_date or '?'}-{it.end_date or '至今'})"
                loc = f" [{it.location}]" if it.location else ""
                lines.append(f"{i}. {it.company} · {it.position or '实习生'}{loc}{date}")
                if it.highlights:
                    for h in it.highlights:
                        lines.append(f"   - {h}")

        if resume.projects:
            lines.append("\n【项目经验】")
            for i, p in enumerate(resume.projects, 1):
                date = f" ({p.start_date or '?'}-{p.end_date or '至今'})"
                lines.append(f"{i}. {p.name} · {p.role or '参与'}{date}")
                if p.tech_stack:
                    lines.append(f"   技术栈: {', '.join(p.tech_stack)}")
                if p.description:
                    lines.append(f"   描述: {p.description}")
                if p.highlights:
                    for h in p.highlights:
                        lines.append(f"   - {h}")
                if p.link:
                    lines.append(f"   链接: {p.link}")

        if resume.skills:
            lines.append("\n【技能】")
            for s in resume.skills:
                items = ", ".join(s.items) if s.items else ""
                label = s.category or "技能"
                lines.append(f"- {label}: {items}")

        return "\n".join(lines)
