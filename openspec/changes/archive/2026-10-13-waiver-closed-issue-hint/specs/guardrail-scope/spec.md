## MODIFIED Requirements

### Requirement: 秒级护栏必须检查失败豁免没有过时

一条豁免本次运行没有放行任何违规时，护栏 MUST 失败并点名它。豁免还在放行违规、且能查到挂的 issue 已关闭时，护栏 MUST 打一行提示点名该 issue，MUST NOT 因此失败（内部#291，用户 2026-10-13 定：修复交付即关、还没进本分支时不能卡住基于 main 的分支）；挂着失败豁免的 issue 在删豁免的提交进 main 之后才关。查不到 issue 状态时 MUST 提示「未核 issue 状态」，不得静默。

#### Scenario: 违规已修好，豁免还在

- **WHEN** 豁免登记的 `style` 段在 `designs/foo/rtl/a.v` 上已没有违规
- **THEN** 护栏 MUST 失败，并点名这条豁免已过时

#### Scenario: issue 已关，修复还没进本分支

- **WHEN** 豁免仍在放行 `designs/foo/rtl/a.v` 上的违规，而挂的 issue 已关闭
- **THEN** 护栏 MUST NOT 因此失败，输出 MUST 有一行提示点名该 issue

#### Scenario: 离线

- **WHEN** 查询 issue 状态失败
- **THEN** 输出 MUST 有一行说明本次没有核 issue 状态
