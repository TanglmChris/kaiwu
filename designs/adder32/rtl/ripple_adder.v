//=============================================================================
// File    : ripple_adder.v
// Module  : RIPPLE_ADDER
// Purpose : Ripple-carry adder: a chain of DAT_W full adders
// Spec    : designs/adder32/lld.ADDER32.md
// Language: Verilog-2001
//=============================================================================
// Hierarchy is kept by the flow (params.yaml keep_hierarchy), see FULL_ADDER.
module RIPPLE_ADDER #(
     parameter DAT_W = 32
)(
     input  wire [DAT_W-1:0] i_a
    ,input  wire [DAT_W-1:0] i_b
    ,input  wire             i_cin
    ,output wire [DAT_W-1:0] o_sum
    ,output wire             o_cout
);

//---- signal declaration
wire [DAT_W:0] c;
genvar         gi;

//---- carry chain
assign c[0] = i_cin;

generate
    for(gi = 0; gi < DAT_W; gi = gi + 1) begin : GEN_FOR_BIT
        FULL_ADDER U_RIPPLE_ADDER_BIT_FULL_ADDER (
             .i_a    ( i_a[gi]   )
            ,.i_b    ( i_b[gi]   )
            ,.i_cin  ( c[gi]     )
            ,.o_sum  ( o_sum[gi] )
            ,.o_cout ( c[gi+1]   )
        );
    end
endgenerate

assign o_cout = c[DAT_W];

endmodule
