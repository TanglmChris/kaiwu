# cbb/ —— 通用构件库

`cbb/<构件>/` 放**通用的参数化构件**（CLZ、popcount、FIFO、仲裁器 ……），每个构件
本身就是一个设计根：独立参数化、独立测 PPA、独立挂 `knowledge/` 的资料卡。
`designs/` 只放由构件组装出来的 IP（用户 2026-09-27 定，放宽了
2026-09-21 的「被两个 IP 真正复用才进」）。

**为 IP 搭建提供的通用构件**（2026-09-29 起）：顶层模块名以 `CBB_` 开头，目录名是顶层名的小写
（`CBB_LZD` → `cbb/cbb_lzd/`）；只有规格、还没有 RTL 时规格先放 `docs/cbb/`，RTL 落地时原样搬进设计根。
`cbb/` 下是开源构件：`cbb_lzd`（找第一个 1）、`cbb_bin2onehot`（二进制转 one-hot）、`cbb_onehot2bin`（one-hot 转二进制）、`cbb_fifo`（同步 FIFO，2026-10-21 起）；闭源构件在私有的 `ip_cbb/` 下（repo-layout「闭源内容只在闭源设计根下」）。2026-09-30 落地时只过了 lint；2026-10-03 起每个构件都有 cocotb TB，覆盖 `params.yaml` 的全部组合（内部#62，见各自的 `verify.*.md`）。
书写风格见 `openspec/specs/rtl-structure-authority/spec.md` 的书写约定（2026-10-03 随 `add-rtl-coding-style` 归档合入），可照抄的模板是 `flow/templates/rtl_module.v`；新文件由 fast_check 的「RTL 书写风格」一项强制（CBB 内部尽量不例化其它模块，D25）。早先的 PPA 实验构件 `cbb/lzd`（`LZD`）2026-10-02 已删，只留单文件的 `CBB_LZD`（内部#75）。

布局与设计根相同；文档只有精简的 `spec.<顶层>.md`（实现要点写在里面）与 `verify.<顶层>.md`，不写 LRS / LLD，模板见 `flow/templates/cbb-root/`。`scripts/fast_check.sh` 已经把
`cbb/*/` 算进设计根洁净度与 RTL 仿真逃生口两项扫描，进来就被管住，不必另加守卫。

**什么进 cbb、什么留在设计根**：结构不绑定某个 IP 的协议或数据格式、换个 IP 也能
原样例化的，进 cbb；只为某个 IP 写的留在设计根。
某个设计根里的模块后来被第二个 IP 需要时，同样搬进 `cbb/<构件>/`，连同它的 TB
与等价证明对一起搬。

**节奏与顺序**：每周约 2 个构件。先做组合类（CLZ/LZD、popcount），用现有 flow 就能测；
带 valid/ready 或 `done` 的构件（sync FIFO、skid buffer ……）进来之前，`sim.cycles`
的口径要先泛化 —— 见 `docs/data-credibility.md` 的 C-6 与
内部#7。

历史讨论：内部#8（2026-09-25 按「等触发」关闭）。
