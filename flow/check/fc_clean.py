# fast_check 的「设计根下只有源文件」检查器：从 scripts/fast_check.sh 的内嵌 Python 原样迁出，正文未改（内部#336）。
# 在仓库根跑：.venv/bin/python3 -m flow.check.fc_clean [参数]；参数、输出与退出码怎么用见 scripts/fast_check.sh 调它的那一段。
from flow.paths import tree_glob as _TG, is_cbb_path as _IS_CBB  # 设计树遍历（内部#305）
import glob, os, sys, yaml

# 设计根下允许的形态。加一项之前先问：它是 repo-layout 说的「源」吗？
#
# 四类文档**一个被测顶层一套**，文件名带顶层名（2026-09-20 收根，本仓 内部#45）：
#   spec.<top>.md  design.<top>.md  verify.<top>.md  REPORT.<top>.md
# 所以这里不能再用固定文件名白名单，得按该根声明的顶层集合生成。
#
# ⚠️ **必须校验文件名里的顶层是不是真的被声明了**，不能只匹配 `*.<任意>.md` 的
# 形状。一个拼错的 `spec.zc_decompres_pipe.md` 形状上完全合法，于是会被放行 ——
# 而它永远不会被任何东西读到。那正是本仓最怕的那类失效：看起来有文档，实际没人读。
# 文档按设计根的类型区分（lrs-lld-docs）：designs/ 下的专用设计是 LRS（需求）+ LLD
# （实现）+ verify；cbb/ 下的通用构件只有精简 spec + verify。designs/ 的旧格式 spec / design
# 已退役（用户 2026-10-04，内部#134），过渡清单随之取消。
DESIGN_DOC_STEMS = ("lrs", "lld", "verify", "REPORT", "param", "ppa", "timing")  # 三份：内部#203 lld-restructure D4
CBB_DOC_STEMS = ("spec", "verify", "REPORT")
ALL_DOC_STEMS = ("spec", "design", "lrs", "lld", "verify", "REPORT")
ALLOWED_DIRS = {"rtl", "tb", "doc", "review"}
# review/：评审记录，一次评审一个子目录，只收文档（2026-10-15 闭源切换 D2，内部#305）；流程工具不往里写。
REVIEW_SUFFIX = {".md", ".diff", ".patch", ".html", ".svg", ".drawio"}
ALLOWED_SUFFIX = {".v", ".sv", ".py", ".md", ".yaml", ".html", ".drawio", ".svg"}   # .drawio / .svg：draw.io 图（内部#119）

def doc_stems(root):
    root = root.rstrip(os.sep)
    return CBB_DOC_STEMS if _IS_CBB(root) else DESIGN_DOC_STEMS


def spec_only(root):
    """规格先行根：既没有 params.yaml 也没有 rtl/（repo-layout「设计根可以先只有规格」）。"""
    return not os.path.exists(os.path.join(root, "params.yaml")) and not os.path.isdir(os.path.join(root, "rtl"))

def spec_only_tops(root):
    """规格先行根里本根文档（doc_stems）用到的顶层名集合。"""
    tops = set()
    for f in os.listdir(root):
        parts = f.split(".")
        if len(parts) == 3 and parts[0] in doc_stems(root) and parts[2] == "md":
            tops.add(parts[1])
    return tops

def allowed_top_files(root):
    """该设计根下允许出现的顶层文件名集合。"""
    names = {"params.yaml", "waivers.vlt",   # waivers.vlt：设计根自己的 lint 豁免（内部#109）
             "sim_waivers.vlt",              # sim_waivers.vlt：设计根自己的仿真构建豁免（内部#312）
             "local_cbb.txt"}                # local_cbb.txt：本根的本地 CBB 副本名单（内部#305）
    # 规格先行根没有 params.yaml，顶层名无从核对：本根文档用的顶层名只有一个时放行，
    # 两个以上说明有一份拼错了，全部拒掉、由 where() 点名（内部#391）
    if spec_only(root):
        tops = spec_only_tops(root)
        if len(tops) == 1:
            names.update(f"{stem}.{top}.md" for stem in doc_stems(root) for top in tops)
        return names
    try:
        doc = yaml.safe_load(open(os.path.join(root, "params.yaml"))) or {}
    except (OSError, yaml.YAMLError):
        return names          # params.yaml 本身的问题由上面的组合展开那一项报
    for top in (doc.get("tops") or {}):
        names.update(f"{stem}.{top}.md" for stem in doc_stems(root))
    return names

WHERE = {
    "results.xml": "测试框架的结果文件，应落在 runs/<experiment_id>/sim/ 下",
    "__pycache__": "解释器的字节码缓存，应由 PYTHONPYCACHEPREFIX 指到设计根之外",
}

def where(path):
    base = os.path.basename(path)
    root = os.path.dirname(path)
    if "review" in path.split(os.sep)[2:-1]:
        return ("review/ 只收文档（.md / .diff / .patch / .html / .svg+.drawio）：日志、JSON、脚本等证据不进设计根，"
                "需要时写进评审正文或 issue（repo-layout「每类产物必须归属到明确的一层」）")
    for key, msg in WHERE.items():
        if key in path.split(os.sep) or base == key:
            return msg
    if base.endswith((".vcd", ".saif", ".log", ".json", ".rpt")):
        return "单次原始产物，应落在 runs/<experiment_id>/ 下"
    parts = base.split(".")
    if len(parts) == 3 and parts[0] in ALL_DOC_STEMS and parts[2] == "md" \
            and parts[0] not in doc_stems(root):
        if _IS_CBB(root):
            return ("通用构件（构件树）只有精简 spec 与 verify，实现要点写进 spec"
                    "（repo-layout，lrs-lld-docs）")
        return ("专用设计（专用设计树）的文档是 lrs / lld / verify：spec / design 旧格式已退役（#134），"
                "spec 改叫 lrs，design 由 lld 取代（repo-layout，lrs-lld-docs）")
    if len(parts) == 3 and parts[0] in ALL_DOC_STEMS and parts[2] == "md" and spec_only(root):
        return (f"规格先行根（没有 params.yaml）里文档的顶层名不一致：{'、'.join(sorted(spec_only_tops(root)))}"
                " —— 顶层名无从对 params.yaml 核，同一根内的文档要写同一个顶层名（#391）")
    if len(parts) == 3 and parts[0] in ALL_DOC_STEMS and parts[2] == "md":
        return (f"形状对但顶层名 {parts[1]!r} **没有在本根的 params.yaml 的 tops: 里声明** ——"
                " 拼错的文档不会被任何东西读到，所以这里拒掉而不是放行")
    if len(parts) == 2 and parts[0] in ALL_DOC_STEMS and parts[1] == "md":
        return ("文档一个被测顶层一套，文件名要带顶层名"
                f"（{parts[0]}.<top>.md，2026-09-20 收根，本仓 #45）")
    return "不是 repo-layout 声明的「源」；它要么进 runs/<experiment_id>/，要么根本不该产生"

roots = _TG("*/")
bad = []
no_source = []   # 没有同名 .drawio 的 .svg（内部#119）
for root in roots:
    root = root.rstrip(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        if rel == ".":
            for d in list(dirnames):
                if d not in ALLOWED_DIRS:
                    bad.append(os.path.join(dirpath, d))
                    dirnames.remove(d)
            allowed = allowed_top_files(root)
            for f in filenames:
                if f not in allowed:
                    bad.append(os.path.join(dirpath, f))
            continue
        in_review = rel.split(os.sep)[0] == "review"
        if not in_review:
            for d in list(dirnames):
                bad.append(os.path.join(dirpath, d))   # rtl//tb//doc/ 下不该再有子目录
                dirnames.remove(d)
        for f in filenames:
            stem, ext = os.path.splitext(f)
            if ext not in (REVIEW_SUFFIX if in_review else ALLOWED_SUFFIX):
                bad.append(os.path.join(dirpath, f))
            elif ext == ".svg" and stem + ".drawio" not in filenames:
                no_source.append(os.path.join(dirpath, f))

for path in sorted(no_source):
    print(f"设计根下的 SVG 没有同名的 .drawio 源文件：{path}（SVG 要由 draw.io 源文件导出，两者一起入库）",
          file=sys.stderr)
bad += no_source
for path in sorted(set(bad) - set(no_source)):
    print(f"设计根下有不该存在的东西：{path}", file=sys.stderr)
    print(f"    {where(path)}", file=sys.stderr)
if bad:
    print("  判据是**目录内容**，不是 git status —— 被 .gitignore 挡住的产物",
          file=sys.stderr)
    print("  同样是写进了设计根（openspec/specs/repo-layout/spec.md）。",
          file=sys.stderr)
print(len(roots))
sys.exit(1 if bad else 0)
