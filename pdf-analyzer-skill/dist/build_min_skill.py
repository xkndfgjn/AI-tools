"""构建最小技能包：把项目打包为可分发的精简目录。

用法：
    python build_min_skill.py [输出目录]
默认输出到项目根目录下的 dist/ 目录。

打包内容（排除 .venv、__pycache__、缓存文件）：
    - plugin.json
    - install.py
    - build_min_skill.py
    - skills/  （skill.json 定义）
    - runtime/ （proxy.py、config/、mcp_server/ 源码）
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT_DIR / "dist"

# 需要排除的目录/文件模式
EXCLUDED_DIRS = {".venv", "__pycache__", ".git", "dist", ".idea"}
EXCLUDED_EXTENSIONS = {".pyc", ".pyo"}
EXCLUDED_FILES = {".DS_Store", "_e2e_test.py", "_inspect_*.py"}

INCLUDED_TOP_LEVEL = {
    "plugin.json",
    "install.py",
    "build_min_skill.py",
}


def _should_skip(path: Path) -> bool:
    if path.name in EXCLUDED_DIRS:
        return True
    if path.name in EXCLUDED_FILES:
        return True
    if path.suffix in EXCLUDED_EXTENSIONS:
        return True
    return False


def _copy_tree(src: Path, dst: Path) -> None:
    for item in src.iterdir():
        if _should_skip(item):
            continue
        target = dst / item.name
        if item.is_dir():
            # ignore_patterns 的规则同时应用于文件名和目录名，覆盖递归复制中的排除
            shutil.copytree(
                item,
                target,
                ignore=shutil.ignore_patterns(*EXCLUDED_DIRS, *EXCLUDED_FILES),
            )
        else:
            shutil.copy2(item, target)


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    print(f"[build] 输出目录：{output}")

    # 顶层文件
    for name in INCLUDED_TOP_LEVEL:
        src = ROOT_DIR / name
        if src.exists():
            shutil.copy2(src, output / name)

    # skills
    _copy_tree(ROOT_DIR / "skills", output / "skills")

    # runtime
    _copy_tree(ROOT_DIR / "runtime", output / "runtime")

    # 删除构建产物自带的 build_min_skill.py（简化）
    # 保留 install.py 作为安装入口
    print("[build] 构建完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
