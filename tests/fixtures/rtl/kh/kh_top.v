// 保层级用例的夹具（tests/test_synth_keep_hierarchy.py，trim-design-roots 的 D2）：
// 参数化、嵌套、按 SCHEME 选子模块 —— 早先用 ADDER32 的 RTL，2026-10-01 随设计根删除。
module KH_TOP #(parameter DAT_W = 8, parameter SCHEME = 0) (
    input  wire [DAT_W-1:0] i_a,
    input  wire [DAT_W-1:0] i_b,
    output wire [DAT_W:0]   o_sum
);
    KH_CORE #(.DAT_W(DAT_W), .SCHEME(SCHEME)) U_KH_TOP_SUM_KH_CORE (
        .i_a(i_a), .i_b(i_b), .o_sum(o_sum));
endmodule
