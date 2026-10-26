//=============================================================================
// File    : prefix_network_brent_kung.v
// Module  : PREFIX_NETWORK_BRENT_KUNG
// Purpose : Brent-Kung prefix network, (l, f, t) = (log2N-1, 0, 0)
// Spec    : designs/adder32/lld.ADDER32.md
// Language: Verilog-2001
//=============================================================================
// Fanout fixed at 2 and a single wiring track, paid for with the most levels
// (2*log2N - 1). Two sweeps:
//   up   (k = 0..L-1): combine only where (i+1) is a multiple of 2^(k+1),
//                      producing block prefixes
//   down (j = L-2..0): fill the block prefixes back into the bits in between
module PREFIX_NETWORK_BRENT_KUNG #(
     parameter DAT_W = 32
)(
     input  wire [DAT_W-1:0] i_g
    ,input  wire [DAT_W-1:0] i_p
    ,output wire [DAT_W-1:0] o_g
    ,output wire [DAT_W-1:0] o_p
);

//---- localparam
localparam LG    = (DAT_W <= 1) ? 0 : $clog2(DAT_W);
localparam LVL_N = (LG == 0) ? 0 : (2 * LG - 1);

//---- signal declaration
wire [DAT_W-1:0] gl [0:LVL_N];
wire [DAT_W-1:0] pl [0:LVL_N];
genvar           glv;
genvar           gi;

assign gl[0] = i_g;
assign pl[0] = i_p;

// Inlined below (they nest, so STEP gets long):
//   UP      = (glv < LG)                          up sweep or down sweep
//   K       = UP ? glv : (LG - 2 - (glv - LG))    span exponent of this level;
//             down level (glv - LG) maps to j = LG-2 down to 0
//   STEP    = 1 << K
//   DO_UP   = UP  && ((gi+1) % 2^(K+1) == 0)      node at this bit, up sweep
//   DO_DOWN = !UP && gi >= 3*2^K - 1 && ((gi+1-2^K) % 2^(K+1) == 0)
//                                                 node at this bit, down sweep
generate
    for(glv = 0; glv < LVL_N; glv = glv + 1) begin : GEN_FOR_LEVEL
        for(gi = 0; gi < DAT_W; gi = gi + 1) begin : GEN_FOR_BIT
            // DO_UP || DO_DOWN
            if(   ((glv < LG) && (((gi + 1) % (2 * (1 << ((glv < LG) ? glv : (LG - 2 - (glv - LG)))))) == 0))
               || (!(glv < LG) && (gi >= (3 * (1 << ((glv < LG) ? glv : (LG - 2 - (glv - LG)))) - 1))
                   && ((((gi + 1) - (1 << ((glv < LG) ? glv : (LG - 2 - (glv - LG))))) % (2 * (1 << ((glv < LG) ? glv : (LG - 2 - (glv - LG)))))) == 0))) begin : GEN_COMB
                PREFIX_NODE U_PREFIX_NETWORK_BRENT_KUNG_OP_PREFIX_NODE (
                     .i_g_hi ( gl[glv][gi] )
                    ,.i_p_hi ( pl[glv][gi] )
                    ,.i_g_lo ( gl[glv][gi-(1 << ((glv < LG) ? glv : (LG - 2 - (glv - LG))))] )   // [gi-STEP]
                    ,.i_p_lo ( pl[glv][gi-(1 << ((glv < LG) ? glv : (LG - 2 - (glv - LG))))] )
                    ,.o_g    ( gl[glv+1][gi] )
                    ,.o_p    ( pl[glv+1][gi] )
                );
            end else begin : GEN_PASS
                assign gl[glv+1][gi] = gl[glv][gi];
                assign pl[glv+1][gi] = pl[glv][gi];
            end
        end
    end
endgenerate

assign o_g = gl[LVL_N];
assign o_p = pl[LVL_N];

endmodule
