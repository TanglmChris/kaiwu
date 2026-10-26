//=============================================================================
// File    : prefix_adder.v
// Module  : PREFIX_ADDER
// Purpose : Prefix adder shell: g/p precompute, prefix network, sum XOR
// Spec    : designs/adder32/lld.ADDER32.md
// Language: Verilog-2001
//=============================================================================
// All three networks share this shell, so measured differences come from the
// network topology alone, not from how the stages around it are written.
// cin does not take a column: the network reduces g/p only, and the carries
//   c[0]   = cin
//   c[i+1] = G[i] | (P[i] & cin)
// add it back, G[i] / P[i] being the group generate / propagate of bits i..0.
module PREFIX_ADDER #(
     parameter DAT_W  = 32
    ,parameter SCHEME = 4   // 3 SKLANSKY, 4 KOGGE_STONE, 5 BRENT_KUNG (same numbering as ADDER_CORE)
)(
     input  wire [DAT_W-1:0] i_a
    ,input  wire [DAT_W-1:0] i_b
    ,input  wire             i_cin
    ,output wire [DAT_W-1:0] o_sum
    ,output wire             o_cout
);

//---- localparam
localparam SCHEME_SKLANSKY    = 3;
localparam SCHEME_KOGGE_STONE = 4;
localparam SCHEME_BRENT_KUNG  = 5;

//---- signal declaration
wire [DAT_W-1:0] g;
wire [DAT_W-1:0] p;
wire [DAT_W-1:0] gg;   // group generate, bit i down to bit 0
wire [DAT_W-1:0] gp;   // group propagate
wire [DAT_W:0]   c;
genvar           gi;

assign g = i_a & i_b;
assign p = i_a ^ i_b;

generate
    if(SCHEME == SCHEME_SKLANSKY) begin : GEN_SKLANSKY
        PREFIX_NETWORK_SKLANSKY #(
             .DAT_W ( DAT_W )
        ) U_PREFIX_ADDER_NET_PREFIX_NETWORK_SKLANSKY (
             .i_g   ( g     )
            ,.i_p   ( p     )
            ,.o_g   ( gg    )
            ,.o_p   ( gp    )
        );
    end else if(SCHEME == SCHEME_KOGGE_STONE) begin : GEN_KOGGE_STONE
        PREFIX_NETWORK_KOGGE_STONE #(
             .DAT_W ( DAT_W )
        ) U_PREFIX_ADDER_NET_PREFIX_NETWORK_KOGGE_STONE (
             .i_g   ( g     )
            ,.i_p   ( p     )
            ,.o_g   ( gg    )
            ,.o_p   ( gp    )
        );
    end else if(SCHEME == SCHEME_BRENT_KUNG) begin : GEN_BRENT_KUNG
        PREFIX_NETWORK_BRENT_KUNG #(
             .DAT_W ( DAT_W )
        ) U_PREFIX_ADDER_NET_PREFIX_NETWORK_BRENT_KUNG (
             .i_g   ( g     )
            ,.i_p   ( p     )
            ,.o_g   ( gg    )
            ,.o_p   ( gp    )
        );
    end
endgenerate

assign c[0] = i_cin;

generate
    for(gi = 0; gi < DAT_W; gi = gi + 1) begin : GEN_FOR_CARRY
        assign c[gi+1] = gg[gi] | (gp[gi] & i_cin);
    end
endgenerate

assign o_sum  = p ^ c[DAT_W-1:0];
assign o_cout = c[DAT_W];

`ifdef CBB_PARAM_CHK_ON
generate
    if(   (SCHEME != SCHEME_SKLANSKY) && (SCHEME != SCHEME_KOGGE_STONE)
       && (SCHEME != SCHEME_BRENT_KUNG)) begin : GEN_SCHEME_CHK
        $error("PREFIX_ADDER: SCHEME is not 3/4/5");
    end
endgenerate
`endif

endmodule
