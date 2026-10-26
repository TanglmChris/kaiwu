"""draw.io 图元重叠检查（内部#227，drawio-figlib D3）。

    .venv/bin/python3 flow/doc/drawio_overlap.py designs/<根>/doc/*.drawio     # 有重叠退出 1，逐条列出

同一页里两两比较顶点（嵌套的按父容器累加坐标）：
- 形状 × 形状：部分相交就报；一个完全包含另一个（容器）不报。
- 文字 × 文字：按字迹相交就报。文字框常比字本身宽，所以按字数估字迹：CJK 1 个字号宽、其余 0.6 个字号宽，
  行高 1.25 个字号，再按 align / verticalAlign 摆位置（10-21 在仓里 90 份图上试过：只按框判 9 份报警，按字迹判剩 2 份）。
- 文字 × 形状：字迹跨在形状边上就报，整个在里面或外面不报。
- style 带 kaiwuOverlap=ok 的图元不报（故意跨边的标签；figlib 的 ok_overlap=True 就是写这个）。
"""
import html
import re
import sys
import xml.etree.ElementTree as ET

EPS = 0.5


def _style(s):
    d = {}
    for part in (s or "").split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            d[k] = v
        elif part:
            d[part] = "1"
    return d


def _ink(text, size):
    lines = html.unescape(re.sub(r"<br\s*/?>", "\n", text or "")).split("\n")
    w = max((sum(size if ord(ch) > 0x2E80 else 0.6 * size for ch in ln) for ln in lines), default=0)
    return w, len(lines) * size * 1.25


def elements(path):
    """[(页名, 文字, 是否文字, 是否放行, (x0, y0, x1, y1))]"""
    out = []
    for d in ET.parse(path).getroot().iter("diagram"):
        cells = {c.get("id"): c for c in d.iter("mxCell")}
        for c in cells.values():
            if c.get("vertex") != "1":
                continue
            g = c.find("mxGeometry")
            if g is None or g.get("relative") == "1":
                continue
            x, y, w, h = (float(g.get(k, 0)) for k in ("x", "y", "width", "height"))
            p = cells.get(c.get("parent"))
            while p is not None and p.get("vertex") == "1":
                pg = p.find("mxGeometry")
                x += float(pg.get("x", 0))
                y += float(pg.get("y", 0))
                p = cells.get(p.get("parent"))
            st = _style(c.get("style"))
            is_text = "text" in st or (st.get("fillColor") == "none" and st.get("strokeColor") == "none")
            if is_text:
                size = float(st.get("fontSize", 12))
                iw, ih = _ink(c.get("value"), size)
                iw, ih = min(iw, w), min(ih, h)
                al, va = st.get("align", "center"), st.get("verticalAlign", "middle")
                x = x if al == "left" else (x + w - iw if al == "right" else x + (w - iw) / 2)
                y = y if va == "top" else (y + h - ih if va == "bottom" else y + (h - ih) / 2)
                w, h = iw, ih
            text = html.unescape(c.get("value") or "").replace("\n", " ")
            out.append((d.get("name") or "", text, is_text, st.get("kaiwuOverlap") == "ok", (x, y, x + w, y + h)))
    return out


def _meets(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > EPS and min(a[3], b[3]) - max(a[1], b[1]) > EPS


def _inside(a, b):
    return a[0] >= b[0] - EPS and a[1] >= b[1] - EPS and a[2] <= b[2] + EPS and a[3] <= b[3] + EPS


def overlaps(path):
    els = elements(path)
    hits = []
    for i in range(len(els)):
        for j in range(i + 1, len(els)):
            a, b = els[i], els[j]
            if a[0] != b[0] or a[3] or b[3] or not _meets(a[4], b[4]):
                continue
            if not (a[2] and b[2]) and (_inside(a[4], b[4]) or _inside(b[4], a[4])):
                continue   # 容器，或文字整个在形状里
            hits.append((a[0], a[1], b[1], tuple(round(v) for v in (max(a[4][0], b[4][0]), max(a[4][1], b[4][1]),
                                                                    min(a[4][2], b[4][2]), min(a[4][3], b[4][3])))))
    return hits


def main(argv=None):
    paths = sys.argv[1:] if argv is None else argv
    if not paths:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    n = 0
    for p in paths:
        for page, ta, tb, box in overlaps(p):
            n += 1
            print(f"重叠  {p}「{page}」：「{ta or '（无文字）'}」×「{tb or '（无文字）'}」，相交 {box}")
    print(f"图元重叠 {n} 处（{len(paths)} 个文件）" + ("；故意的在 style 里加 kaiwuOverlap=ok" if n else ""))
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main())
