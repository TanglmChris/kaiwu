// 测试夹具（trim-design-roots 的 D2）：有触发器、但只有「输入 → 寄存器 → 输出」，没有域内路径。
module SHAPE_REG1 #(parameter DAT_W = 8) (
    input  wire             clk,
    input  wire [DAT_W-1:0] i_a,
    output wire [DAT_W-1:0] o_y
);
    reg [DAT_W-1:0] y_r;
    always @(posedge clk) y_r <= ~i_a;
    assign o_y = y_r;
endmodule
