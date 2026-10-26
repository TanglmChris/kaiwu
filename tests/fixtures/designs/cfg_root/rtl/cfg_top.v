// 测试夹具（sta-static-ports 内部#154、depth 建钟 内部#167）：cfg 是静态配置，cfg * cfg 很深；寄存器路径
// d ^ q 很浅。顶层的时钟端口叫 core_clk（params.yaml 用 sta.clocks 声明），寄存器放在子模块
// CFG_REG 里、它的时钟端口叫 clk —— 网表里「有 input clk」而顶层没有 clk 端口，正是 内部#167 的形状。
module CFG_TOP #(
     parameter DAT_W = 8
)(
     input  wire             core_clk
    ,input  wire             rst_n
    ,input  wire [DAT_W-1:0] cfg
    ,input  wire [DAT_W-1:0] d
    ,output wire [DAT_W-1:0] q
    ,output wire [DAT_W-1:0] o
);

CFG_REG #(.DAT_W(DAT_W)) U_CFG_TOP_Q_CFG_REG (
     .clk   (core_clk)
    ,.rst_n (rst_n)
    ,.d     (d)
    ,.q     (q)
);

assign o = (cfg * cfg) ^ q;

endmodule

module CFG_REG #(
     parameter DAT_W = 8
)(
     input  wire             clk
    ,input  wire             rst_n
    ,input  wire [DAT_W-1:0] d
    ,output reg  [DAT_W-1:0] q
);

always@(posedge clk,negedge rst_n) begin : BLK_Q
    if(!rst_n) begin
        q <= {DAT_W{1'b0}};
    end else begin
        q <= d ^ q;
    end
end

endmodule
