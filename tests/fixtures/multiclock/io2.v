// 两个时钟域各自有自己的 primary I/O，域之间没有任何路径。
//
// 用来验 D5/F4 —— 本变更里唯一一处「不这么写就静默丢数」的地方：
// 把全部输入都绑到第一个时钟（set_input_delay 0 -clock clk_a [all_inputs]）
// 再配上异步分组，clk_b 域的 db -> reg 与 reg -> qb 会被**整片静默排除**。
// 实测两类路径各 0 条、没有任何警告；按每个时钟各发一次（第二个起 -add_delay）
// 之后各恢复为 1 条。
//
// 这个坑在单时钟下不存在，所以重跑既有记录的对比**发现不了它** —— 只能靠这个
// 夹具守住。
`default_nettype none
`timescale 1ns/1ps

module io2 (
  input  wire clk_a,
  input  wire clk_b,
  input  wire da,
  input  wire db,
  output reg  qa,
  output reg  qb
);
  always @(posedge clk_a) qa <= ~da;
  always @(posedge clk_b) qb <= ~db;
endmodule
