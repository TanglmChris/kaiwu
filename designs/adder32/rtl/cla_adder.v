//=============================================================================
// File    : cla_adder.v
// Module  : CLA_ADDER
// Purpose : Carry-lookahead adder built on FLAT_LOOKAHEAD
// Spec    : designs/adder32/lld.ADDER32.md
// Language: Verilog-2001
//=============================================================================
// Hierarchy is kept by the flow (params.yaml keep_hierarchy), see FULL_ADDER.
module CLA_ADDER #(
     parameter DAT_W = 32
)(
     input  wire [DAT_W-1:0] i_a
    ,input  wire [DAT_W-1:0] i_b
    ,input  wire             i_cin
    ,output wire [DAT_W-1:0] o_sum
    ,output wire             o_cout
);

//---- signal declaration
wire [DAT_W-1:0] g;
wire [DAT_W-1:0] p;
wire [DAT_W:0]   c;

assign g = i_a & i_b;
assign p = i_a ^ i_b;

FLAT_LOOKAHEAD #(
     .DAT_W ( DAT_W )
) U_CLA_ADDER_CARRY_FLAT_LOOKAHEAD (
     .i_g   ( g     )
    ,.i_p   ( p     )
    ,.i_cin ( i_cin )
    ,.o_c   ( c     )
);

assign o_sum  = p ^ c[DAT_W-1:0];
assign o_cout = c[DAT_W];

endmodule
