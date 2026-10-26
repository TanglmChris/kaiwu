// 级数预算夹具（内部#184）：CHAIN_DEEP 与 CHAIN_MID 各是「寄存器 → N 级进位式链 → 寄存器」，CHAIN_SHORT 不超预算。
module BUDGET_CHAIN #(parameter N = 8) (input wire clk, input wire [N-1:0] a, input wire [N-1:0] b, output reg y);
    reg  [N-1:0] ra, rb;
    wire [N:0]   c;
    assign c[0] = 1'b0;
    genvar gi;
    generate
        for (gi = 0; gi < N; gi = gi + 1) begin : GEN_FOR
            assign c[gi+1] = (c[gi] & ra[gi]) | rb[gi];
        end
    endgenerate
    always @(posedge clk) begin ra <= a; rb <= b; y <= c[N]; end
endmodule

module BUDGET_TOP #(parameter DAT_W = 8) (input wire clk, input wire [63:0] a, input wire [63:0] b,
                                          output wire y_deep, output wire y_mid, output wire y_short);
    BUDGET_CHAIN #(.N(64)) U_BUDGET_TOP_DEEP  (.clk(clk), .a(a),        .b(b),        .y(y_deep));
    BUDGET_CHAIN #(.N(40)) U_BUDGET_TOP_MID   (.clk(clk), .a(a[39:0]),  .b(b[39:0]),  .y(y_mid));
    BUDGET_CHAIN #(.N(6))  U_BUDGET_TOP_SHORT (.clk(clk), .a(a[5:0]),   .b(b[5:0]),   .y(y_short));
endmodule

// 内部#207：输入端口起点的链（不例化，只用 --module 单独量）：输入 → N 级 → 寄存器，报告行数 = 组合单元数 + 2。
module BUDGET_PORT_CHAIN #(parameter N = 24) (input wire clk, input wire [N-1:0] a, input wire [N-1:0] b, output reg y);
    wire [N:0] c;
    assign c[0] = 1'b0;
    genvar gi;
    generate
        for (gi = 0; gi < N; gi = gi + 1) begin : GEN_FOR
            assign c[gi+1] = (c[gi] & a[gi]) | b[gi];
        end
    endgenerate
    always @(posedge clk) y <= c[N];
endmodule
