//=============================================================================
// File    : prefix_network_sklansky.v
// Module  : PREFIX_NETWORK_SKLANSKY
// Purpose : Sklansky (divide and conquer) prefix network, (l, f, t) = (0, log2N-1, 0)
// Spec    : designs/adder32/lld.ADDER32.md
// Language: Verilog-2001
//=============================================================================
// Also log2N levels with a single wiring track, paid for with fanout that
// doubles per level: the midpoint of each block at level k drives 2^k nodes.
// Level k: blocks are 2^(k+1) wide; every bit in the upper half of a block
// combines with the last bit of that block's lower half.
module PREFIX_NETWORK_SKLANSKY #(
     parameter DAT_W = 32
)(
     input  wire [DAT_W-1:0] i_g
    ,input  wire [DAT_W-1:0] i_p
    ,output wire [DAT_W-1:0] o_g
    ,output wire [DAT_W-1:0] o_p
);

//---- localparam
localparam LVL_N = (DAT_W <= 1) ? 0 : $clog2(DAT_W);

//---- signal declaration
wire [DAT_W-1:0] gl [0:LVL_N];
wire [DAT_W-1:0] pl [0:LVL_N];
genvar           gk;
genvar           gi;

assign gl[0] = i_g;
assign pl[0] = i_p;

// Inlined below:
//   HALF = 1 << gk              width of the lower half
//   BLK  = 1 << (gk + 1)        block width
//   OFF  = gi % BLK             offset in the block; >= HALF means upper half
//   MID  = gi - OFF + HALF - 1  last bit of the block's lower half
generate
    for(gk = 0; gk < LVL_N; gk = gk + 1) begin : GEN_FOR_LEVEL
        for(gi = 0; gi < DAT_W; gi = gi + 1) begin : GEN_FOR_BIT
            if((gi % (1 << (gk + 1))) >= (1 << gk)) begin : GEN_COMB   // OFF >= HALF
                PREFIX_NODE U_PREFIX_NETWORK_SKLANSKY_OP_PREFIX_NODE (
                     .i_g_hi ( gl[gk][gi] )
                    ,.i_p_hi ( pl[gk][gi] )
                    ,.i_g_lo ( gl[gk][gi - (gi % (1 << (gk + 1))) + (1 << gk) - 1] )   // [MID]
                    ,.i_p_lo ( pl[gk][gi - (gi % (1 << (gk + 1))) + (1 << gk) - 1] )
                    ,.o_g    ( gl[gk+1][gi] )
                    ,.o_p    ( pl[gk+1][gi] )
                );
            end else begin : GEN_PASS
                assign gl[gk+1][gi] = gl[gk][gi];
                assign pl[gk+1][gi] = pl[gk][gi];
            end
        end
    end
endgenerate

assign o_g = gl[LVL_N];
assign o_p = pl[LVL_N];

endmodule
