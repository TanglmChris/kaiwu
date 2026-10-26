// 慢一个量级的纯组合夹具（tests/test_fmax_search.py，trim-design-roots 的 D2）：256 级串行的
// 进位式链，ABC 无法把它并行化，关键路径远超 1000 ps。早先用一个已删的地址流水设计，2026-10-01 删除。
module SLOW_CHAIN #(parameter DAT_W = 256) (
    input  wire [DAT_W-1:0] i_a,
    input  wire [DAT_W-1:0] i_b,
    output wire             o_y
);
    wire [DAT_W:0] c;
    assign c[0] = 1'b0;
    genvar gi;
    generate
        for (gi = 0; gi < DAT_W; gi = gi + 1) begin : GEN_FOR
            assign c[gi+1] = (c[gi] & i_a[gi]) | i_b[gi];
        end
    endgenerate
    assign o_y = c[DAT_W];
endmodule
