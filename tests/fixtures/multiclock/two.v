// 跨时钟域路径的最小形态：clk_a 域的 m 直接喂 clk_b 域的 qb。
//
// 用来验「跨域路径参不参与分析由声明决定，不由工具默认行为决定」。实测
// （OpenSTA 3.1.0，2026-09-15）不设分组时 worst_slack 取自 m -> qb 这条跨域
// 路径、required 用 clk_b 的边沿；设了 -asynchronous 之后是域内的。两个都是
// slack (MET)、都不报警告，而前者不说明电路的任何性质。
//
// 这是**流程的测试输入**，不是被测设计 —— 所以它在 tests/fixtures/ 下而不在
// designs/ 下：进设计根就会产生记录、进扫参、被设计根洁净度检查按设计对待。
`default_nettype none
`timescale 1ns/1ps

module two (
  input  wire clk_a,
  input  wire clk_b,
  input  wire d,
  output reg  qa,
  output reg  qb
);
  reg m;
  always @(posedge clk_a) begin
    m  <= d;
    qa <= m;
  end
  always @(posedge clk_b) qb <= m;   // 跨域
endmodule
