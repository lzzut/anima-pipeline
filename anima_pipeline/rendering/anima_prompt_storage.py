"""Small offline gallery for future v2 runs; images and evidence stay separate."""

from html import escape
from pathlib import Path
from urllib.parse import quote


def write_gallery(output_dir, candidates, selected):
    root = Path(output_dir)
    chosen = {str(Path(p)) for p in selected}
    cards = []
    for row in candidates:
        path = Path(row["path"])
        relative = path.relative_to(root).as_posix()
        audit = row.get("prompt_audit")
        audit_link = ""
        if audit:
            audit_link = (
                f'<a href="{quote(Path(audit).relative_to(root).as_posix())}">最终提示词与数据</a>'
            )
        cards.append(
            f"""<article><a href="{quote(relative)}"><img loading="lazy" src="{quote(relative)}"></a><p>{escape(str(row.get('channel', '')))} · seed {row['seed']} · 美学排序 {row['score']}</p><p>{audit_link}</p></article>"""
        )
    selected_links = " ".join(
        (
            f'<a href="{quote(Path(p).relative_to(root).as_posix())}">{escape(Path(p).name)}</a>'
            for p in chosen
        )
    )
    page = (
        f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>图片浏览</title><style>body{{background:#181b22;color:#eee;font:16px system-ui;margin:24px}}a{{color:#8fc9ff}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px}}article{{background:#252a35;padding:12px;border-radius:12px}}img{{width:100%;height:580px;object-fit:contain}}p{{overflow-wrap:anywhere}}</style><h1>本次图片</h1><p>点击图片查看原图。美学排序只供选择参考，图片仍需人工验收。</p><p>程序选中图：{selected_links}</p><main>'
        + "".join(cards)
        + "</main></html>"
    )
    path = root / "查看图片.html"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(page)
    return str(path)
