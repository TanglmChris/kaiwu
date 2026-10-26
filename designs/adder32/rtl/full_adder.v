//=============================================================================
// File    : full_adder.v
// Module  : FULL_ADDER
// Purpose : One-bit full adder, the cell of the ripple and carry-select adders
// Spec    : designs/adder32/lld.ADDER32.md
// Language: Verilog-2001
//=============================================================================
// Hierarchy is kept by the flow (params.yaml tops:ADDER32:synth:keep_hierarchy),
// not by an attribute here: without it ABC's &dch restructures across module
// boundaries and the carry structures collapse into one netlist (pitfalls P-3).
module FULL_ADDER (
     input  wire i_a
    ,input  wire i_b
    ,input  wire i_cin
    ,output wire o_sum
    ,output wire o_cout
);

assign o_sum  = i_a ^ i_b ^ i_cin;
assign o_cout = (i_a & i_b) | (i_cin & (i_a ^ i_b));

endmodule
