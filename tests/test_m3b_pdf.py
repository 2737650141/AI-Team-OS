"""007 3.1：PDF 真实可用测试（pypdf 已入项目依赖）。

覆盖：普通文本/多页/页数上限/加密/无文字/超大文件/页面引用/原文件不被修改。
全部使用 pypdf 生成的合成 PDF（临时目录），不访问网络。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from app.tools.local_file import LocalPathPolicy, build_local_tools


@pytest.fixture()
def pdf_root(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    return root


def _make_pdf(path: Path, pages: list[str] | None = None, encrypt: str | None = None) -> None:
    """空白/多页 PDF（含可选加密），文本页由 reportlab 生成。"""
    if pages:
        _text_pdf(path, pages[0])
        if len(pages) > 1:
            from pypdf import PdfWriter as W

            w = W()
            w.append(str(path))
            for _ in range(len(pages) - 1):
                w.add_blank_page(width=200, height=200)
            with path.open("wb") as fh:
                w.write(fh)
    else:
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        if encrypt:
            writer.encrypt(encrypt)
        with path.open("wb") as fh:
            writer.write(fh)


def _text_pdf(path: Path, text: str) -> None:
    """生成含可提取文本的单页 PDF（reportlab，测试专用生成库）。"""
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=(300, 300))
    c.drawString(72, 200, text)
    c.save()


def _tools(root: Path):
    policy = LocalPathPolicy([root])
    return {s.name: s for s in build_local_tools(policy)}


def test_pdf_plain_text(pdf_root: Path) -> None:
    """1. 普通文本 PDF。"""
    p = pdf_root / "plain.pdf"
    _text_pdf(p, "Hello PDF world")
    tools = _tools(pdf_root)
    r = tools["local_read_pdf"].handler("plain.pdf")
    assert r["ok"] and "Hello PDF world" in r["content"]


def test_pdf_multi_page(pdf_root: Path) -> None:
    """2. 多页 PDF（页码引用保留）。"""
    p = pdf_root / "multi.pdf"
    _text_pdf(p, "Page one")
    # 追加第二页（重新打开写入）
    from pypdf import PdfWriter as W

    w = W()
    w.append(str(p))
    w.add_blank_page(width=300, height=300)
    with p.open("wb") as fh:
        w.write(fh)
    tools = _tools(pdf_root)
    r = tools["local_read_pdf"].handler("multi.pdf")
    assert r["ok"] and r["page_count"] >= 2
    assert r["page_range"] == [1, r["page_count"]]  # 页码引用（9.1）


def test_pdf_page_limit(pdf_root: Path) -> None:
    """3. 页数上限（MAX_PDF_PAGES=100）。"""
    from app.tools.local_file import MAX_PDF_PAGES

    p = pdf_root / "many.pdf"
    w = PdfWriter()
    for _ in range(MAX_PDF_PAGES + 1):
        w.add_blank_page(width=100, height=100)
    with p.open("wb") as fh:
        w.write(fh)
    tools = _tools(pdf_root)
    r = tools["local_read_pdf"].handler("many.pdf")
    assert r["ok"] is False and r["code"] == "blocked"


def test_pdf_encrypted_rejected(pdf_root: Path) -> None:
    """4. 加密 PDF 明确拒绝（本阶段不接收密码）。"""
    p = pdf_root / "enc.pdf"
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    w.encrypt("secret-pass")
    with p.open("wb") as fh:
        w.write(fh)
    tools = _tools(pdf_root)
    r = tools["local_read_pdf"].handler("enc.pdf")
    assert r["ok"] is False and r["code"] == "blocked"
    assert "encrypted" in r["error"]


def test_pdf_no_text_marks_ocr(pdf_root: Path) -> None:
    """5. 无文字 PDF 标记 ocr_required=true。"""
    p = pdf_root / "image.pdf"
    w = PdfWriter()
    w.add_blank_page(width=300, height=300)  # 无内容流 → 无文本
    with p.open("wb") as fh:
        w.write(fh)
    tools = _tools(pdf_root)
    r = tools["local_read_pdf"].handler("image.pdf")
    assert r["ok"] and r["ocr_required"] is True
    assert "OCR" in r["note"]


def test_pdf_oversized_rejected(pdf_root: Path) -> None:
    """6. 超大文件（>2MB）拒绝。"""
    from app.tools.local_file import MAX_FILE_BYTES

    p = pdf_root / "big.pdf"
    p.write_bytes(b"%PDF-1.4\n" + b"x" * (MAX_FILE_BYTES + 100))
    tools = _tools(pdf_root)
    r = tools["local_read_pdf"].handler("big.pdf")
    assert r["ok"] is False and r["code"] == "blocked"


def test_pdf_page_reference_preserved(pdf_root: Path) -> None:
    """7. 页面引用：Evidence 支持 page_range（read_pdf 返回 page_range）。"""
    p = pdf_root / "ref.pdf"
    _text_pdf(p, "Referenced")
    tools = _tools(pdf_root)
    r = tools["local_read_pdf"].handler("ref.pdf")
    assert r["ok"]
    assert isinstance(r["page_range"], list) and len(r["page_range"]) == 2
    assert r["page_range"][0] == 1


def test_pdf_source_file_unchanged(pdf_root: Path) -> None:
    """8. 原文件不被修改（只读工具：读取前后哈希一致）。"""
    import hashlib

    p = pdf_root / "stable.pdf"
    _text_pdf(p, "Stable content")
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    tools = _tools(pdf_root)
    r = tools["local_read_pdf"].handler("stable.pdf")
    assert r["ok"]
    after = hashlib.sha256(p.read_bytes()).hexdigest()
    assert before == after


def test_pdf_dependency_installed() -> None:
    """pypdf 已入项目依赖（007 3.1：pyproject 锁定范围）。"""
    import pypdf

    assert pypdf.__version__.startswith("5.")  # >=4.0,<6.0
    assert PdfReader is not None
