//=============================================================================
// File    : prefix_network_kogge_stone.v
// Module  : PREFIX_NETWORK_KOGGE_STONE
// Purpose : Kogge-Stone prefix network, Harris (l, f, t) = (0, 0, log2N-1)
// Spec    : designs/adder32/lld.ADDER32.md
// Language: Verilog-2001
//=============================================================================
// Fewest levels (log2N) and fanout fixed at 2, paid for with O(N) wiring tracks.
// Level k: every bit i >= 2^k combines with bit i-2^k; the rest pass through.
module PREFIX_NETWORK_KOGGE_STONE #(
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

// STEP = 1 << gk, the span of level gk, inlined below
generate
    for(gk = 0; gk < LVL_N; gk = gk + 1) begin : GEN_FOR_LEVEL
        for(gi = 0; gi < DAT_W; gi = gi + 1) begin : GEN_FOR_BIT
            if(gi >= (1 << gk)) begin : GEN_COMB   // gi >= STEP
                PREFIX_NODE U_PREFIX_NETWORK_KOGGE_STONE_OP_PREFIX_NODE (
                     .i_g_hi ( gl[gk][gi]            )
                    ,.i_p_hi ( pl[gk][gi]            )
                    ,.i_g_lo ( gl[gk][gi-(1 << gk)]  )   // [gi-STEP]
                    ,.i_p_lo ( pl[gk][gi-(1 << gk)]  )
                    ,.o_g    ( gl[gk+1][gi]          )
                    ,.o_p    ( pl[gk+1][gi]          )
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
