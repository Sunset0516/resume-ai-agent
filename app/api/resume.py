"""
简历管理 API 路由
"""
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..database import get_db
from ..main import get_owner_key
from ..schemas import (
    ResumeCreate, ResumeUpdate, Resume as ResumeSchema, ApiResponse,
    EducationCreate, InternshipCreate, ProjectCreate, SkillCreate,
)
from ..services.resume_crud import ResumeCRUD

router = APIRouter(prefix="/api/resume", tags=["简历管理"])
logger = logging.getLogger(__name__)


@router.get("", response_model=ApiResponse[ResumeSchema])
def get_default_resume(owner_key: str = Depends(get_owner_key),
    db: Session = Depends(get_db)):
    """获取默认（第一条）简历"""
    crud = ResumeCRUD(db, owner_key=owner_key)
    r = crud.get_default()
    if not r:
        raise HTTPException(status_code=404, detail="暂无简历数据，请先创建")
    return ApiResponse(data=r)


@router.get("/list", response_model=ApiResponse[List[ResumeSchema]])
def list_resumes(owner_key: str = Depends(get_owner_key),
    db: Session = Depends(get_db)):
    """列出所有简历"""
    crud = ResumeCRUD(db, owner_key=owner_key)
    return ApiResponse(data=crud.list_all())


@router.get("/{resume_id}", response_model=ApiResponse[ResumeSchema])
def get_resume(resume_id: int, owner_key: str = Depends(get_owner_key),
    db: Session = Depends(get_db)):
    crud = ResumeCRUD(db, owner_key=owner_key)
    r = crud.get(resume_id)
    if not r:
        raise HTTPException(status_code=404, detail="简历不存在")
    return ApiResponse(data=r)


@router.post("", response_model=ApiResponse[ResumeSchema])
def create_resume(data: ResumeCreate, owner_key: str = Depends(get_owner_key),
    db: Session = Depends(get_db)):
    """创建完整简历"""
    crud = ResumeCRUD(db, owner_key=owner_key)
    try:
        r = crud.create(data)
    except Exception as e:
        logger.exception("创建简历失败")
        raise HTTPException(status_code=400, detail=f"创建失败: {e}")
    return ApiResponse(data=r, message="简历创建成功")


@router.put("/{resume_id}", response_model=ApiResponse[ResumeSchema])
def update_resume(resume_id: int, data: ResumeUpdate, owner_key: str = Depends(get_owner_key),
    db: Session = Depends(get_db)):
    crud = ResumeCRUD(db, owner_key=owner_key)
    r = crud.update(resume_id, data)
    if not r:
        raise HTTPException(status_code=404, detail="简历不存在")
    return ApiResponse(data=r, message="简历更新成功")


@router.delete("/{resume_id}", response_model=ApiResponse)
def delete_resume(resume_id: int, owner_key: str = Depends(get_owner_key),
    db: Session = Depends(get_db)):
    crud = ResumeCRUD(db, owner_key=owner_key)
    if not crud.delete(resume_id):
        raise HTTPException(status_code=404, detail="简历不存在")
    return ApiResponse(message="简历已删除")


# ==========================================================
# 子项操作
# ==========================================================
@router.post("/{resume_id}/education", response_model=ApiResponse)
def add_education(resume_id: int, edu: EducationCreate, owner_key: str = Depends(get_owner_key),
    db: Session = Depends(get_db)):
    crud = ResumeCRUD(db, owner_key=owner_key)
    e = crud.add_education(resume_id, edu)
    if not e:
        raise HTTPException(status_code=404, detail="简历不存在")
    from ..schemas import Education as EducationSchema
    return ApiResponse(data=EducationSchema.model_validate(e).model_dump(), message="教育经历已添加")


@router.post("/{resume_id}/internship", response_model=ApiResponse)
def add_internship(resume_id: int, it: InternshipCreate, owner_key: str = Depends(get_owner_key),
    db: Session = Depends(get_db)):
    crud = ResumeCRUD(db, owner_key=owner_key)
    r = crud.add_internship(resume_id, it)
    if not r:
        raise HTTPException(status_code=404, detail="简历不存在")
    from ..schemas import Internship as InternshipSchema
    return ApiResponse(data=InternshipSchema.model_validate(r).model_dump(), message="实习经历已添加")


@router.post("/{resume_id}/project", response_model=ApiResponse)
def add_project(resume_id: int, pj: ProjectCreate, owner_key: str = Depends(get_owner_key),
    db: Session = Depends(get_db)):
    crud = ResumeCRUD(db, owner_key=owner_key)
    r = crud.add_project(resume_id, pj)
    if not r:
        raise HTTPException(status_code=404, detail="简历不存在")
    from ..schemas import Project as ProjectSchema
    return ApiResponse(data=ProjectSchema.model_validate(r).model_dump(), message="项目经验已添加")


@router.post("/{resume_id}/skill", response_model=ApiResponse)
def add_skill(resume_id: int, sk: SkillCreate, owner_key: str = Depends(get_owner_key),
    db: Session = Depends(get_db)):
    crud = ResumeCRUD(db, owner_key=owner_key)
    r = crud.add_skill(resume_id, sk)
    if not r:
        raise HTTPException(status_code=404, detail="简历不存在")
    from ..schemas import Skill as SkillSchema
    return ApiResponse(data=SkillSchema.model_validate(r).model_dump(), message="技能已添加")


@router.get("/export/text", response_model=ApiResponse)
def export_resume_text(resume_id: int = None, owner_key: str = Depends(get_owner_key),
    db: Session = Depends(get_db)):
    """把简历导出为纯文本（用于调试 / 预览喂给 LLM 的内容）"""
    crud = ResumeCRUD(db, owner_key=owner_key)
    r = crud.get(resume_id) if resume_id else crud.get_default()
    if not r:
        raise HTTPException(status_code=404, detail="简历不存在")
    text = crud.dump_resume_text(r)
    return ApiResponse(data={"name": r.name, "text": text, "length": len(text)})


# ==========================================================
# 文档上传 + AI 自动解析
# ==========================================================
@router.post("/upload", response_model=ApiResponse[ResumeSchema])
async def upload_resume_file(
    file: UploadFile = File(...),
    owner_key: str = Depends(get_owner_key),
    db: Session = Depends(get_db),
):
    """上传简历文档（PDF/DOCX/TXT/MD），AI 自动解析并创建简历（按 owner_key 隔离）"""
    from ..services.doc_parser import doc_parser
    from ..schemas import ResumeCreate

    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(content_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件过大，请上传 10MB 以内的文件")

    # 1. 提取文本
    try:
        text = doc_parser.extract_text(file.filename, content_bytes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not text or len(text) < 10:
        raise HTTPException(status_code=400, detail="无法从文档中提取有效文本，请检查文件内容")

    logger.info(f"[upload][owner={owner_key[:12]}...] file={file.filename} text_len={len(text)}")

    # 2. 调用 LLM 解析结构化数据
    try:
        parsed = doc_parser.parse_resume(text)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 3. 创建简历（若当前 owner 已有默认简历则覆盖，绝不影响其他 owner）
    try:
        resume_data = ResumeCreate(**parsed)
        crud = ResumeCRUD(db, owner_key=owner_key)
        old = crud.get_default()
        if old:
            crud.delete(old.id)
        resume = crud.create(resume_data)
    except Exception as e:
        logger.exception("create resume from upload failed")
        raise HTTPException(status_code=400, detail=f"解析成功但创建简历失败: {e}")

    # 用 Pydantic schema 序列化 SQLAlchemy 对象，避免 json.dumps 遇到 ORM 对象崩溃
    from fastapi.responses import JSONResponse
    from ..schemas import Resume as ResumeSchema
    resume_schema = ResumeSchema.model_validate(resume)
    resp = ApiResponse(
        data=resume_schema,
        message=f"简历解析成功！从 {file.filename} 提取了 {len(text)} 字符",
    )
    return JSONResponse(
        content=resp.model_dump(mode="json"),
        headers={"X-Owner-Key": owner_key, "Access-Control-Expose-Headers": "X-Owner-Key"},
    )
