# -*- coding: utf-8 -*-
"""draw.io 作图库（内部#227，drawio-figlib D1）。接口沿用规格会话 10-04 起用的旧版作图类，配色加上 docs/spec-writing.md §6。

    import sys; sys.path.insert(0, "flow/doc")        # 或 from flow.doc.figlib import *
    from figlib import *
    f = Fig()
    f.title("写数据通路")                              # 图内第一行标题
    a = f.box(20, 40, 100, 40, "写缓冲", kind="data")  # 返回 id
    b = f.diamond(160, 30, 80, 60, "命中？", kind="ctrl")
    f.edge(a, b, label="wdat", kind="data")            # dashed=True 表示旁带；exit / entry / points 控制走线
    f.line(10, 120, 300, 120)                          # 不挂图元的线（分界线、时间轴）
    f.save("designs/<根>/doc/<图名>.drawio", "页名")

产出与仓里现有 .drawio 同一形态：未压缩 XML、html=0（导出的 SVG 不带 foreignObject）、标签换行转 &#xa;、正交连线。
导出用 flow/doc/drawio_export.py，画完用 flow/doc/drawio_overlap.py 查图元有没有压在一起。
"""
from xml.sax.saxutils import escape

# 旧版的颜色常量照旧；C_BRN 是 §6 的「常开部分 / 控制」棕，旧版在调用处自己定义
C_ON = '#D5E8D4'; C_CG = '#DAE8FC'; C_Y = '#FFF2CC'; C_R = '#F8CECC'; C_P = '#E1D5E7'; C_O = '#FFE6CC'; C_G = '#F5F5F5'
C_BRN = '#F0E0CC'
# §6：棕＝常开部分 / 控制，蓝＝数据通路，绿＝汇聚 / 仲裁，红＝丢弃与错误，紫＝中断
FILL = {"ctrl": C_BRN, "data": C_CG, "merge": C_ON, "error": C_R, "intr": C_P, "plain": '#FFFFFF'}
# §6：黑色连线＝命令 / 控制，蓝色连线＝数据；虚线＝旁带
LINE = {"cmd": '#333333', "data": '#6C8EBF'}

__all__ = ["Fig", "FILL", "LINE", "C_ON", "C_CG", "C_Y", "C_R", "C_P", "C_O", "C_G", "C_BRN"]


def _esc(s):
    return escape(s, {'"': '&quot;', '\n': '&#xa;'})


def _ok(ok_overlap):
    return 'kaiwuOverlap=ok;' if ok_overlap else ''


class Fig:
    def __init__(self):
        self.cells = []
        self.n = 2

    def _id(self):
        self.n += 1
        return 'c%d' % self.n

    def _v(self, x, y, w, h, text, st):
        i = self._id()
        self.cells.append('<mxCell id="%s" value="%s" style="%s" vertex="1" parent="1"><mxGeometry x="%g" y="%g" '
                          'width="%g" height="%g" as="geometry"/></mxCell>' % (i, _esc(text), st, x, y, w, h))
        return i

    def title(self, text, x=20, y=8, w=880, h=22, font=12):
        """图内第一行标题（spec-writing §6：离开上下文也知道讲什么）。"""
        return self.text(x, y, w, h, text, font=font, align='left')

    def box(self, x, y, w, h, text='', fill=None, stroke='#333333', dashed=False, rounded=True, font=12, bold=False,
            align='center', valign='middle', color='#000000', kind='plain', ok_overlap=False):
        st = 'html=0;fillColor=%s;strokeColor=%s;fontSize=%d;align=%s;verticalAlign=%s;fontColor=%s;' % (
            fill or FILL[kind], stroke, font, align, valign, color)
        st += 'rounded=1;arcSize=8;' if rounded else 'rounded=0;'
        if dashed:
            st += 'dashed=1;'
        if bold:
            st += 'fontStyle=1;'
        if align == 'left':
            st += 'spacingLeft=6;'
        if valign == 'top':
            st += 'spacingTop=2;'
        return self._v(x, y, w, h, text, st + _ok(ok_overlap))

    def diamond(self, x, y, w, h, text, fill=None, font=11, kind=None, ok_overlap=False):
        """判断菱形；不给 fill / kind 时与旧版一样用黄 C_Y。"""
        st = 'html=0;rhombus;fillColor=%s;strokeColor=#333333;fontSize=%d;' % (fill or (FILL[kind] if kind else C_Y), font)
        return self._v(x, y, w, h, text, st + _ok(ok_overlap))

    def text(self, x, y, w, h, text, font=11, align='center', color='#333333', bold=False, ok_overlap=False):
        """纯文字。ok_overlap=True 表示故意跨在别的图元边上，drawio_overlap.py 不报。"""
        st = 'html=0;text;fillColor=none;strokeColor=none;fontSize=%d;align=%s;verticalAlign=middle;fontColor=%s;' % (
            font, align, color)
        if bold:
            st += 'fontStyle=1;'
        return self._v(x, y, w, h, text, st + _ok(ok_overlap))

    def edge(self, src, dst, label='', dashed=False, points=None, exit=None, entry=None, color=None, font=10, kind='cmd'):
        i = self._id()
        st = ('html=0;endArrow=block;endFill=1;strokeColor=%s;fontSize=%d;labelBackgroundColor=#FFFFFF;'
              'edgeStyle=orthogonalEdgeStyle;rounded=0;' % (color or LINE[kind], font))
        if dashed:
            st += 'dashed=1;'
        if exit:
            st += 'exitX=%g;exitY=%g;exitDx=0;exitDy=0;' % exit
        if entry:
            st += 'entryX=%g;entryY=%g;entryDx=0;entryDy=0;' % entry
        geo = '<mxGeometry relative="1" as="geometry">'
        if points:
            geo += '<Array as="points">' + ''.join('<mxPoint x="%g" y="%g"/>' % p for p in points) + '</Array>'
        geo += '</mxGeometry>'
        self.cells.append('<mxCell id="%s" value="%s" style="%s" edge="1" parent="1" source="%s" target="%s">%s</mxCell>'
                          % (i, _esc(label), st, src, dst, geo))
        return i

    def line(self, x1, y1, x2, y2, dashed=True, color='#C0392B', arrow=False, width=1, both=False):
        i = self._id()
        st = 'html=0;strokeColor=%s;strokeWidth=%g;endArrow=%s;' % (color, width, 'block;endFill=1' if arrow else 'none')
        if both:
            st += 'startArrow=block;startFill=1;'
        if dashed:
            st += 'dashed=1;'
        self.cells.append('<mxCell id="%s" style="%s" edge="1" parent="1"><mxGeometry relative="1" as="geometry">'
                          '<mxPoint x="%g" y="%g" as="sourcePoint"/><mxPoint x="%g" y="%g" as="targetPoint"/>'
                          '</mxGeometry></mxCell>' % (i, st, x1, y1, x2, y2))
        return i

    def save(self, path, name):
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('<mxfile><diagram name="%s"><mxGraphModel grid="0" page="0"><root><mxCell id="0"/>'
                     '<mxCell id="1" parent="0"/>%s</root></mxGraphModel></diagram></mxfile>\n'
                     % (_esc(name), ''.join(self.cells)))
        return path
