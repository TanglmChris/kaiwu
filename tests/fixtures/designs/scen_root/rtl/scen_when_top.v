// 场景按参数组合适用的夹具（内部#198）：与 SCEN_TOP 同样的两条链，多一个只用来匹配 when 的参数 PICK
module SCEN_WHEN_TOP #(parameter DAT_W = 8, parameter PICK = 0) (input wire clk, input wire mode, input wire [63:0] a, input wire [63:0] b,
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
