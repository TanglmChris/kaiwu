// clk_b 域里只有一个触发器，它的进与出**都是跨域**，没有任何 primary I/O
// 落在这个域上。异步分组之后 clk_b 域一条可分析的路径都没有。
//
// 用来验 D4/F3：那时该域的 slack_ns 与 fmax_mhz 必须**缺席**（null），
// 不能填 0（会被读成「刚好卡住」）、不能填周期（会被读成「完全空闲」）。
// 而 name/port/period_ns 仍要在 —— 「这个时钟被建立过」与「它没有域内路径」
// 是两件都要记下来的事。
//
// 不能用 two.v 验这条：加了逐时钟输出延时之后 two.v 的 clk_b 有 reg -> output
// 路径，不再是空域。
`default_nettype none
`timescale 1ns/1ps

module nopath (
  input  wire clk_a,
  input  wire clk_b,
  input  wire d,
  output reg  q
);
  reg m;
  reg s;
  always @(posedge clk_a) m <= d;
  always @(posedge clk_b) s <= m;    // 跨域进
  always @(posedge clk_a) q <= s;    // 跨域出
endmodule
