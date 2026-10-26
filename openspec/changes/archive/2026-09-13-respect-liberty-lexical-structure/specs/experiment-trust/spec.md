## MODIFIED Requirements

### Requirement: 合并出来的 liberty 必须自洽

由多个 liberty 文件合并而成的综合库中，任何被 cell 的时序表或功耗表引用的
查找表模板（`lu_table_template` / `power_lut_template`）MUST 在**第一次被引用之前**
就已经在同一个 `library` 块里定义。合并工具 MUST 保证这个顺序，
MUST NOT 依赖各个源文件里模板与 cell 的相对位置。

理由是 liberty 是自上而下解析的，模板在引用之后才定义时**解析器不会报错退出**，
只会警告一句并把那个时序组丢弃 —— 该 cell 的那条弧从此没有延时模型。
后果不是精度损失，是**整类路径消失**：时序单元的 `CLK→Q` 弧一旦丢失，
所有以触发器为起点的路径都不再存在，而工具照常给出一个看上去正常的 slack。

合并工具切分块时，块边界 MUST 与 liberty 的词法结构一致：出现在**字符串字面量**
或**注释**里的花括号 MUST NOT 参与块深度计算，出现在其中的块头 MUST NOT 被当作
一个块的开始。边界算错时工具 MUST NOT 静默产出 —— 它会把相邻的块吞进来或截断，
而产物的语法错误只会在下游换来一句警告。

#### Scenario: 合并后校验模板顺序

- **WHEN** 用合并工具把多个 liberty 文件合成一个
- **THEN** 产物中每个被引用的模板名都能在其第一次被引用的位置之前找到定义
- **AND** 这条性质由自动检查覆盖，MUST NOT 只靠人读警告发现

#### Scenario: 源文件里模板定义在 cell 之后

- **WHEN** 某个源 liberty 文件把模板定义放在它自己的 cell 之后
- **THEN** 合并产物仍然满足"定义先于引用"
- **AND** 合并工具 MUST NOT 原样保留源文件的块顺序

#### Scenario: 花括号出现在字符串字面量或注释里

- **WHEN** 某个源 liberty 文件的字符串字面量或 `/* */` 注释里出现花括号
- **THEN** 该花括号 MUST NOT 影响块边界的判定
- **AND** 合并产物中每个块的内容与源文件中该块的内容逐字相同

#### Scenario: 注释里出现形如块头的文本

- **WHEN** 某个源 liberty 文件的注释里出现形如 `cell (FOO)` 的文本
- **THEN** 它 MUST NOT 被当作一个块的开始
