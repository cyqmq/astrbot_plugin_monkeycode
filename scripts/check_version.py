#!/usr/bin/env python3
"""发布前版本一致性检查。

校验 metadata.yaml 的 version 与 main.py 中 @register 的版本号一致。
用法：python scripts/check_version.py
不一致时退出码为 1。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    meta = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")

    m_meta = re.search(r"^version:\s*v?([0-9]+\.[0-9]+\.[0-9]+)", meta, re.M)
    if not m_meta:
        print("❌ metadata.yaml 中未找到 version 字段")
        return 1
    meta_ver = m_meta.group(1)

    m_register = re.search(
        r'@register\((.*?)\)\s*class\s+',
        main_src,
        re.S,
    )
    if not m_register:
        print("❌ main.py 中未找到 @register")
        return 1
    args = re.findall(r'"([^"]+)"', m_register.group(1))
    if len(args) < 4:
        print("❌ @register 参数不足（应为 name/author/desc/version）")
        return 1
    register_ver = args[3]

    if meta_ver != register_ver:
        print(
            f"❌ 版本号不一致：metadata.yaml = {meta_ver}，"
            f"@register = {register_ver}"
        )
        print("请同步后再提交。")
        return 1

    print(f"✅ 版本号一致：v{meta_ver}")
    return 0


if __name__ == "__main__":
    sys.exit(main())