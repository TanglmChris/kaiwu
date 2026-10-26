// 测试夹具（trim-design-roots 的 D2）：零触发器的纯组合顶层。
module SHAPE_COMB #(parameter DAT_W = 8) (
    input  wire [DAT_W-1:0] i_a,
    output wire [DAT_W-1:0] o_y
);
    assign o_y = ~i_a;
endmodule
