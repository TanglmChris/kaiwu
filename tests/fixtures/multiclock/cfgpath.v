// 静态配置输入经一段很深的组合逻辑直接到输出，寄存器路径很浅（sta-static-ports，内部#154）。
//
// 不排除 cfg 时，最坏路径是 cfg -> o（乘法器）；把 cfg 声明为 static_ports 之后，
// 最坏路径必须回到寄存器那一段 —— 一个大设计上配置端口到门控空闲信号的路径挡住内部
// 关键路径就是这个形状。
`default_nettype none
`timescale 1ns/1ps

module cfgpath (
  input  wire       clk,
  input  wire       rst_n,
  input  wire [7:0] cfg,
  input  wire [7:0] d,
  output reg  [7:0] q,
  output wire [7:0] o
);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) q <= 8'd0;
    else        q <= d ^ q;
  end
  assign o = (cfg * cfg) ^ q;
endmodule
