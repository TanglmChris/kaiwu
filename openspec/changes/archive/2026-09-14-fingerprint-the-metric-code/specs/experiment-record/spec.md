## MODIFIED Requirements

### Requirement: 记录必须自解释其产出流程

一条实验记录 MUST 携带一个 `flow` 段，用来判断它与另一条记录是否出自同一套
测量流程。`flow` MUST 包含一个 `fingerprint` 标量，以及构成该指纹的各项事实
（至少：综合器与静态时序分析器的版本、所用 liberty 的内容哈希、综合与 STA
两段脚本配方的哈希、**把工具输出解析成记录字段的那部分代码的哈希**）。

`git_commit` 不足以承担这件事：它记的是仓库的版本，而换 PDK、换 Vt/corner、
重新生成合并 liberty 都不改变任何 commit，却会让全部数字整体挪位。

**只哈希交给工具的脚本是不够的。** 同一份工具输出，换一种解析方式就得到不同口径的
字段，而脚本一个字没变。这类改动 MUST 改变指纹。

覆盖范围 MUST NOT 依赖"记得登记"：把哪些函数算作派生逻辑列成一份清单，会在有人
新增一条派生路径却忘了登记时失效 —— 而"忘了"正是这条要求要防的那件事。
覆盖 MUST 以模块为单位，且被覆盖的模块清单本身 MUST 进入该哈希，
使删减清单同样改变指纹。

该哈希 MUST NOT 因**注释、空行或 docstring** 的改动而改变。理由是文档修订频繁
且不改变任何测量结果；若它们也分代，流程代就会被噪声淹没，人就会开始无视代的边界，
这条要求也就失效了。

#### Scenario: 同一套流程下的两次测量

- **WHEN** 在不改动工具、liberty 与流程脚本的前提下跑两次实验
- **THEN** 两条记录的 `flow.fingerprint` 相同

#### Scenario: 换掉综合库

- **WHEN** 用另一份 liberty（不同 Vt/corner，或重新生成过的合并库）跑同一个设计
- **THEN** 新记录的 `flow.fingerprint` 与旧记录不同
- **AND** `flow` 里记录的 liberty 内容哈希不同

#### Scenario: 改动综合配方

- **WHEN** 综合脚本模板或 abc 约束文件的内容发生变化后再跑实验
- **THEN** 新记录的 `flow.fingerprint` 与变化之前不同

#### Scenario: 只改解析逻辑，不改交给工具的脚本

- **WHEN** 把工具输出解析成记录字段的代码发生变化，而脚本模板与约束文件一个字未变
- **THEN** 新记录的 `flow.fingerprint` 与变化之前不同
- **AND** 两批记录 MUST NOT 被判成同一流程代

#### Scenario: 只改注释或 docstring

- **WHEN** 只修订注释、空行或 docstring，没有改动任何可执行语句
- **THEN** `flow.fingerprint` 保持不变

#### Scenario: 从覆盖清单里删掉一个模块

- **WHEN** 被覆盖的模块清单被缩小
- **THEN** `flow.fingerprint` 随之改变
