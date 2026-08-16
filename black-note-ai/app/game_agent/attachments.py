"""通用文档入口：校验上传内容并提取有界正文。

图片直接作为 HumanMessage 的一部分交给主模型；PDF、DOCX、文本和代码文件在本地提取正文。
原始文件不进入长期模型上下文，只保存哈希引用和有界的提取结果。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime
from xml.etree import ElementTree

from app.game_agent.models import AttachmentInput


MAX_EXTRACTED_CHARS = 24_000
TEXT_MIME_TYPES = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-yaml",
}


class AttachmentArtifactService:
    """保留文档正文提取能力；图片不经过这个旁路服务。"""

    def __init__(self, image_service=None):
        self.image_service = image_service

    async def analyze(self, attachment: AttachmentInput | dict) -> dict:
        """验证附件并返回统一 Artifact；不支持的格式也返回可展示的状态。"""
        item = AttachmentInput.model_validate(attachment)
        raw = decode_data_url(item.data_url, item.size)
        if item.mime_type.startswith("image/"):
            raise ValueError("图片应直接作为多模态 HumanMessage 处理")

        # 非图片附件直接在服务端解析，避免额外消耗一次语言模型调用。
        artifact_id = f"file_{hashlib.sha256(raw).hexdigest()[:12]}"
        try:
            text = extract_file_text(item.name, item.mime_type, raw)
            status = "ready"
            error = None
        except ValueError as exc:
            text = ""
            status = "unsupported"
            error = str(exc)

        return {
            "artifact_id": artifact_id,
            "kind": "file_text",
            "status": status,
            "created_at": datetime.now().astimezone().isoformat(),
            "name": item.name,
            "mime_type": item.mime_type,
            "size": item.size,
            "raw_ref": f"inline-file://sha256/{hashlib.sha256(raw).hexdigest()}",
            "summary": {
                "extracted_text": text[:MAX_EXTRACTED_CHARS],
                "truncated": len(text) > MAX_EXTRACTED_CHARS,
                "processing_error": error,
            },
        }


def decode_data_url(data_url: str, declared_size: int) -> bytes:
    """解码前端 Data URL，并校验编码、10MB 上限和声明大小。"""
    match = re.fullmatch(r"data:([^;,]+)?(?:;charset=[^;,]+)?;base64,(.+)", data_url, re.DOTALL)
    if not match:
        raise ValueError("附件必须使用 base64 Data URL")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except ValueError as exc:
        raise ValueError("附件 base64 内容无效") from exc
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError("单个附件不能超过 10MB")
    if declared_size and len(raw) != declared_size:
        raise ValueError("附件大小与声明不一致")
    return raw


def extract_file_text(name: str, mime_type: str, raw: bytes) -> str:
    """按照文件类型提取纯文本；无法安全解析的二进制格式明确拒绝。"""
    suffix = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if mime_type.startswith("text/") or mime_type in TEXT_MIME_TYPES or suffix in {
        "txt", "md", "json", "csv", "tsv", "log", "py", "js", "ts", "html", "css", "xml", "yaml", "yml",
    }:
        return raw.decode("utf-8", errors="replace")
    if mime_type == "application/pdf" or suffix == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("服务端未安装 PDF 解析依赖 pypdf") from exc
        return "\n\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or suffix == "docx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                root = ElementTree.fromstring(archive.read("word/document.xml"))
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise ValueError("DOCX 文件结构无效") from exc
        return "\n".join(text for text in root.itertext() if text.strip())
    raise ValueError("当前支持图片、PDF、DOCX 和常见文本/代码文件")


def render_attachment_artifacts(artifacts: dict[str, dict]) -> str:
    """把附件 Artifact 序列化为 Agent 可阅读的精简 JSON。"""
    if not artifacts:
        return "无附件 Artifact"
    compact = [
        {
            "artifact_id": artifact["artifact_id"],
            "name": artifact.get("name"),
            "mime_type": artifact.get("mime_type"),
            "status": artifact["status"],
            "summary": artifact["summary"],
        }
        for artifact in artifacts.values()
    ]
    return json.dumps(compact, ensure_ascii=False)
