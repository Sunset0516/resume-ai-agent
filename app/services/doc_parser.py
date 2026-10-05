"""
文档解析服务：从上传的简历文档（PDF/DOCX/TXT/MD）提取文本，
再用 LLM 解析为结构化简历数据。
"""
import io
import json
import logging
from typing import Dict, Any

from .llm_service import llm_service

logger = logging.getLogger(__name__)


class DocParserService:
    """文档解析 + LLM 结构化提取"""

    SUPPORTED_EXT = {".pdf", ".docx", ".txt", ".md"}

    # ------------------------------------------------------------------
    # 文本提取
    # ------------------------------------------------------------------
    def extract_text(self, filename: str, content: bytes) -> str:
        """根据文件类型提取纯文本"""
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in self.SUPPORTED_EXT:
            raise ValueError(
                f"不支持的文件格式: {ext}，请上传 PDF/DOCX/TXT/MD 文件"
            )
        if ext == ".pdf":
            return self._extract_pdf(content)
        elif ext == ".docx":
            return self._extract_docx(content)
        else:
            return self._extract_text(content)

    def _extract_pdf(self, content: bytes) -> str:
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            raise RuntimeError("未安装 PyPDF2，请联系管理员安装")
        reader = PdfReader(io.BytesIO(content))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
        return "\n".join(pages).strip()

    def _extract_docx(self, content: bytes) -> str:
        try:
            from docx import Document
        except ImportError:
            raise RuntimeError("未安装 python-docx，请联系管理员安装")
        doc = Document(io.BytesIO(content))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs).strip()

    def _extract_text(self, content: bytes) -> str:
        for encoding in ("utf-8", "gbk", "gb2312", "big5"):
            try:
                return content.decode(encoding).strip()
            except (UnicodeDecodeError, LookupError):
                continue
        return content.decode("utf-8", errors="replace").strip()

    # ------------------------------------------------------------------
    # LLM 结构化解析
    # ------------------------------------------------------------------
    def parse_resume(self, text: str) -> Dict[str, Any]:
        """调用 LLM 把简历文本解析为结构化 JSON 数据"""
        system_prompt = (
            "你是一个简历解析助手。用户会给你一段简历文本，"
            "请提取结构化信息并以纯 JSON 格式返回，不要输出任何其他内容。\n"
            "JSON 字段如下，没有的字段填 null 或空数组：\n"
            "{\n"
            '  "name": "姓名",\n'
            '  "title": "求职意向或头衔",\n'
            '  "email": "邮箱",\n'
            '  "phone": "电话",\n'
            '  "location": "所在地",\n'
            '  "github": "GitHub地址",\n'
            '  "blog": "博客地址",\n'
            '  "summary": "个人简介自我评价",\n'
            '  "educations": [{"school":"","degree":"","major":"","start_date":"","end_date":"","description":""}],\n'
            '  "internships": [{"company":"","position":"","start_date":"","end_date":"","location":"","highlights":["亮点"]}],\n'
            '  "projects": [{"name":"","role":"","start_date":"","end_date":"","description":"","highlights":["亮点"],"tech_stack":["技术"],"link":""}],\n'
            '  "skills": [{"category":"分类","items":["技能1","技能2"]}]\n'
            "}\n"
            "要求：1.只返回纯JSON，不要markdown代码块标记 2.字段名用英文 3.日期保持原文格式"
        )
        user_prompt = f"请解析以下简历文本并提取结构化JSON：\n\n{text[:8000]}"

        messages = llm_service.build_messages(system_prompt, user_prompt)
        content, tokens = llm_service.chat_completion(
            messages, temperature=0.1, max_tokens=4000
        )

        cleaned = self._clean_json(content)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"LLM返回JSON解析失败: {e}\n原始内容: {content[:500]}")
            raise RuntimeError("AI解析简历失败，返回的内容不是合法JSON，请重试或手动录入")

        # 清洗 null 值：LLM 可能返回 null 但 Pydantic 必填字段不接受
        if not data.get("name"):
            data["name"] = "未命名"
        data.setdefault("educations", [])
        data.setdefault("internships", [])
        data.setdefault("projects", [])
        data.setdefault("skills", [])
        # 清洗子表中必填字段的 null
        for edu in data["educations"]:
            if not edu.get("school"):
                edu["school"] = "未知学校"
        for intern in data["internships"]:
            if not intern.get("company"):
                intern["company"] = "未知公司"
        for proj in data["projects"]:
            if not proj.get("name"):
                proj["name"] = "未知项目"
        for sk in data["skills"]:
            if not sk.get("items"):
                sk["items"] = []
        logger.info(f"[DocParser] LLM解析完成 name={data.get('name')} "
                     f"edu={len(data['educations'])} int={len(data['internships'])} "
                     f"proj={len(data['projects'])} skill={len(data['skills'])}")
        return data

    def _clean_json(self, text: str) -> str:
        """去掉 LLM 可能包裹的 markdown 代码块标记"""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        return text.strip()


# 全局单例
doc_parser = DocParserService()
