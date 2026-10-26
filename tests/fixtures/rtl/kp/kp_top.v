// 网表等价分层证明的夹具（tests/test_netlist_equiv.py，trim-design-roots 的 D2）：
// 带触发器（PIPE_STAGES 级移位寄存器）、包着一个保层级的子模块。早先用 ADDER32，2026-10-01 删除。
module KP_TOP #(parameter DAT_W = 8, parameter PIPE_STAGES = 2) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire [DAT_W-1:0] i_a,
    input  wire [DAT_W-1:0] i_b,
    output wire [DAT_W:0]   o_sum
);
    localparam S_W = DAT_W + 1;
    wire [S_W-1:0] sum;
    KP_ADD #(.DAT_W(DAT_W)) U_KP_TOP_SUM_KP_ADD (.i_a(i_a), .i_b(i_b), .o_sum(sum));
    // 第 k 级在 pipe_r[S_W*k +: S_W]，新值从第 0 级进，最后一级出
    reg  [S_W*PIPE_STAGES-1:0] pipe_r;
    wire [S_W*PIPE_STAGES-1:0] pipe_pre;
    generate
        if (PIPE_STAGES == 1) begin : GEN_ONE
            assign pipe_pre = sum;
        end else begin : GEN_MANY
            assign pipe_pre = {pipe_r[S_W*(PIPE_STAGES-1)-1:0], sum};
        end
    endgenerate
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) pipe_r <= {S_W*PIPE_STAGES{1'b0}};
        else        pipe_r <= pipe_pre;
    end
    assign o_sum = pipe_r[S_W*PIPE_STAGES-1 -: S_W];
endmodule
