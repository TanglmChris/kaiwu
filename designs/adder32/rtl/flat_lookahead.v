//=============================================================================
// File    : flat_lookahead.v
// Module  : FLAT_LOOKAHEAD
// Purpose : Flat carry lookahead: every carry as a direct sum of products
// Spec    : designs/adder32/lld.ADDER32.md
// Language: Verilog-2001
//=============================================================================
// c[i] is expanded as a sum of products over g/p instead of the serial
// recurrence c[i] = g | p & c[i-1]. Same math as ripple, written so synthesis
// can build a shallow AND-OR tree per bit rather than an N-deep carry chain.
module FLAT_LOOKAHEAD #(
     parameter DAT_W = 32
)(
     input  wire [DAT_W-1:0] i_g
    ,input  wire [DAT_W-1:0] i_p
    ,input  wire             i_cin
    ,output wire [DAT_W:0]   o_c
);

//---- signal declaration
genvar gi;
genvar gj;

assign o_c[0] = i_cin;

generate
    for(gi = 1; gi <= DAT_W; gi = gi + 1) begin : GEN_FOR_CARRY
        wire [gi:0]   pacc;   // pacc[k] = i_p[gi-1] & i_p[gi-2] & ... & i_p[gi-k]
        wire [gi-1:0] term;   // term[j] = pacc[j] & i_g[gi-1-j]

        assign pacc[0] = 1'b1;
        for(gj = 0; gj < gi; gj = gj + 1) begin : GEN_FOR_PACC
            assign pacc[gj+1] = pacc[gj] & i_p[gi-1-gj];
        end
        for(gj = 0; gj < gi; gj = gj + 1) begin : GEN_FOR_TERM
            assign term[gj] = pacc[gj] & i_g[gi-1-gj];
        end

        assign o_c[gi] = (|term) | (pacc[gi] & i_cin);
    end
endgenerate

endmodule
