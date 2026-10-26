# cbb-library Specification

## Purpose
通用构件（CBB）的命名、目录与接口约定：构件独立参数化、独立测 PPA，可被多个 IP 原样例化。

## Requirements

### Requirement: CBB 的模块名与目录名

`cbb/` 下为 IP 搭建提供的通用构件，被测顶层的模块名 MUST 以 `CBB_` 开头，设计根目录名 MUST 是
顶层名的小写（`CBB_LZD` → `cbb/cbb_lzd/`），没有例外。

#### Scenario: 新构件落地

- **WHEN** 一个新的通用构件在 `cbb/` 下建设计根
- **THEN** 它的顶层模块名 SHALL 以 `CBB_` 开头，目录名 SHALL 是顶层名的小写

### Requirement: 握手构件的通道命名

带 valid/ready 握手的 CBB，上游通道 MUST 叫 `src`、下游通道 MUST 叫 `dst`：上游侧端口是
`i_src_vld` / `o_src_rdy` / `i_src_dat`，下游侧是 `o_dst_vld` / `i_dst_rdy` / `o_dst_dat`。
同一种角色的两个构件（例如两种握手打拍构件 `CBB_SKID` 与 `CBB_PIPE`）因此可以只换模块名互相替换。

#### Scenario: 用 FIFO 替换打拍

- **WHEN** 一处 `CBB_SKID` 的例化被换成 `CBB_PIPE`
- **THEN** `src` / `dst` 两组端口的连接 SHALL 不需要改名

### Requirement: 电路落地之前的构件规格先放在文档目录

只有规格、还没有 RTL 的构件，规格 MUST 放在 `docs/cbb/spec.<顶层>.md`，MUST NOT 放进 `cbb/<目录>/`：
流程要求 `cbb/` 下每个目录都是有 `params.yaml` 的完整设计根，缺了会让全仓的实验命令与秒级护栏
一起失败（内部#74）。格式 MUST 与设计根的 `spec.<顶层>.md` 相同，端口表 MUST 能被机械读出
（`repo-layout` 的「spec 的端口表必须能被机械地读出」）。RTL 落地时 MUST 把它原样搬进设计根，
`docs/cbb/` 下 MUST NOT 留副本。

#### Scenario: 规格写好、RTL 未开工

- **WHEN** 一个构件只有规格
- **THEN** 它 SHALL 在 `docs/cbb/spec.<顶层>.md`，`cbb/` 下 SHALL 没有它的目录

#### Scenario: RTL 落地

- **WHEN** 一个构件的设计根建好（有 `params.yaml`、`rtl/`、`tb/`）
- **THEN** 它的规格 SHALL 在 `cbb/<目录>/spec.<顶层>.md`，`docs/cbb/` 下 SHALL 不再有这份文件
