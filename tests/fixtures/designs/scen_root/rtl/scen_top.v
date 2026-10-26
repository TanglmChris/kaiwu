// 验收场景夹具（内部#189）：mode 是静态输入，选深链（64 级进位式）或浅链（6 级）的结果打进 y
module SCEN_TOP #(parameter DAT_W = 8) (input wire clk, input wire mode, input wire [63:0] a, input wire [63:0] b,
                                       output reg y);
    reg  [63:0] ra, rb;
    wire [64:0] c;
    wire [6:0]  s;
    assign c[0] = 1'b0;
    assign s[0] = 1'b0;
    genvar gi;
    generate
        for (gi = 0; gi < 64; gi = gi + 1) begin : GEN_FOR_DEEP
            assign c[gi+1] = (c[gi] & ra[gi]) | rb[gi];
        end
        for (gi = 0; gi < 6; gi = gi + 1) begin : GEN_FOR_SHALLOW
            assign s[gi+1] = (s[gi] & ra[gi]) | rb[gi];
        end
    endgenerate
    always @(posedge clk) begin ra <= a; rb <= b; y <= mode ? s[6] : c[64]; end
endmodule
