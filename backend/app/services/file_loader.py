"""Canonical local source loader."""

from pathlib import Path
from app.models.schemas import Chapter
from app.services.preprocessor import preprocess_file
from app.services.project_paths import get_project_paths


class FileLoader:
    """本地文件加载器 — 扫描目录、加载文本、调用预处理"""

    def __init__(self, raw_dir: Path | None = None):
        self._raw_dir = raw_dir or get_project_paths().source

    def list_files(self) -> list[Path]:
        """列出 raw 目录下的所有文本文件"""
        if not self._raw_dir.exists():
            return []
        files = sorted(self._raw_dir.glob("*.txt"))
        return files

    def load_raw(self, file_path: Path) -> str:
        """读取单个原始文本文件"""
        return file_path.read_text(encoding="utf-8")

    def load_all(self) -> dict[str, str]:
        """加载 raw 目录下所有 txt 文件，返回 {文件名: 内容}"""
        result: dict[str, str] = {}
        for fp in self.list_files():
            try:
                content = fp.read_text(encoding="utf-8")
                result[fp.stem] = content
            except Exception:
                continue
        return result

    def load_and_preprocess(self) -> list[Chapter]:
        """加载全部原始文本并预处理为 Chapter 列表"""
        all_chapters: list[Chapter] = []
        for fp in self.list_files():
            try:
                volume_name = fp.stem
                chapters = preprocess_file(fp, volume_name=volume_name)
                all_chapters.extend(chapters)
            except Exception:
                continue
        return all_chapters

    def ingest_to_corpus(self) -> int:
        """Import through the same canonical pipeline used by the API."""
        from app.services.local_importer import scan_and_import

        report = scan_and_import()
        if report.failed_files:
            raise RuntimeError("本地语料导入失败")
        return report.total_chapters_after


# ── 便捷函数 ──

def scan_directory(path: str) -> list[Path]:
    """扫描目录中所有 txt 文件"""
    p = Path(path)
    if not p.exists():
        return []
    return sorted(p.glob("*.txt"))


def load_chapters_from_dir(path: str, volume_name: str = "") -> list[Chapter]:
    """从目录加载所有 txt 文件并预处理为 Chapter 列表"""
    all_chapters: list[Chapter] = []
    for fp in scan_directory(path):
        try:
            vol = volume_name or fp.stem
            chapters = preprocess_file(fp, volume_name=vol)
            all_chapters.extend(chapters)
        except Exception:
            continue
    return all_chapters
