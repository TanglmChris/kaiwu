# 工具链：STA 的时钟与静态端口声明

> 从 `docs/toolchain.md` 按主题拆出（内部#336），条文未改；其余主题见索引 [`docs/toolchain.md`](../toolchain.md)。

### 同周期的第二个时钟（门控时钟，内部#138）

同源、同频、同相的时钟（如经外部门控得到的 `cg_clk`）在 `params.yaml` 里这样声明：

```yaml
tops:
  <顶层>:
    sta:
      clocks:
        - {name: clk,    port: clk,    period_ns: cli}   # cli = 取命令行的 --period-ns
        - {name: cg_clk, port: cg_clk, period_ns: cli}
      clock_groups:
        - [clk, cg_clk]    # 同组 = 同步：两个域之间的路径照常定时
```

- `period_ns` 只能写数字或 `cli`，写别的字符串当场报错。
- 不放进同一组的话，两个时钟默认互为异步，跨域路径不参与分析（`flow/paths.py::clock_groups`）。
- 指纹按设计算（内部#146）：只有改了这段声明的设计换代。

### 静态端口排除在时序分析之外（内部#154）

全局静态配置、复位这类输入到输出的路径，会占住最坏路径、挡住真正的关键路径。用户 2026-10-04 定：正式 STA 也排除，但**要在设计上就保证这里可以设 false_path 或 multicycle**。所以每一项排除都要指向 LRS 里担保它的需求：

```yaml
tops:
  <顶层>:
    sta:
      static_ports:
        - {ports: [cfg_*],  kind: false_path, by: R.011}            # R.011：配置只在空闲时改，改后到下一条命令才生效
        - {ports: [win_*_cfg],  kind: multicycle, cycles: 2, by: R.012}  # R.012：改后两拍内不被采用
        - {ports: [rst_n],      kind: false_path, by: R.013}            # R.013：复位由外部同步释放
```

- `ports` 支持通配，只匹配输入端口；`kind` 是 `false_path`，或 `multicycle` 加 `cycles`（≥ 2，hold 自动取 `cycles - 1`）。
- 担保链路的检查：`by` 必须在接口文档里以加粗 `**R.xxx**` 定义，模式必须匹配得到 RTL 输入端口，否则 fast_check 失败；正式 STA 运行时匹配不到也报错。
- 正式 STA 与 `make depth` 用同一份声明。声明进设计配方（内部#146），改它只让这个设计换代。
