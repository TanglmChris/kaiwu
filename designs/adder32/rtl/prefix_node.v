//=============================================================================
// File    : prefix_node.v
// Module  : PREFIX_NODE
// Purpose : Prefix operator (G, P) o (G', P') = (G | P&G', P&P'), high on the left
// Spec    : designs/adder32/lld.ADDER32.md
// Language: Verilog-2001
//=============================================================================
// Keeping hierarchy MUST land on this operator, not only on the networks.
// Measured 2026-09-08: with only the network kept, ABC rebuilt the 6-level
// 64-bit Sklansky tree into a 47-level chain (21 A2O1A1O1I + 20 OAI21 on the
// critical path, not one buffer), and an abc -D delay target left the netlist
// byte-identical, i.e. it is not timing driven. Keeping PREFIX_NODE brought the
// critical path back to 9 levels, matching theory. Do not drop it from the
// keep_hierarchy list in params.yaml.
module PREFIX_NODE (
     input  wire i_g_hi
    ,input  wire i_p_hi
    ,input  wire i_g_lo
    ,input  wire i_p_lo
    ,output wire o_g
    ,output wire o_p
);

assign o_g = i_g_hi | (i_p_hi & i_g_lo);
assign o_p = i_p_hi & i_p_lo;

endmodule
