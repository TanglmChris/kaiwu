//=============================================================================
// File    : carry_select_adder.v
// Module  : CARRY_SELECT_ADDER
// Purpose : Carry-select adder: each block computes both carry-in cases ahead
// Spec    : designs/adder32/lld.ADDER32.md
// Language: Verilog-2001
//=============================================================================
// Hierarchy is kept by the flow (params.yaml keep_hierarchy), see FULL_ADDER.
module CARRY_SELECT_ADDER #(
     parameter DAT_W = 32
    ,parameter BLK_W = 4
)(
     input  wire [DAT_W-1:0] i_a
    ,input  wire [DAT_W-1:0] i_b
    ,input  wire             i_cin
    ,output wire [DAT_W-1:0] o_sum
    ,output wire             o_cout
);

//---- localparam
localparam BLK_N = (DAT_W + BLK_W - 1) / BLK_W;

//---- signal declaration
wire [BLK_N:0] block_cin;
genvar         gk;

assign block_cin[0] = i_cin;

// Block gk covers bits [LO, HI), inlined below:
//   LO = gk*BLK_W
//   HI = (gk*BLK_W + BLK_W > DAT_W) ? DAT_W : (gk*BLK_W + BLK_W)
//        the last block is cut short when DAT_W is not a multiple of BLK_W
//   W  = HI - LO
generate
    for(gk = 0; gk < BLK_N; gk = gk + 1) begin : GEN_FOR_BLOCK
        // [W-1:0]
        wire [(((gk*BLK_W + BLK_W > DAT_W) ? DAT_W : (gk*BLK_W + BLK_W)) - gk*BLK_W)-1:0] sum0;
        wire [(((gk*BLK_W + BLK_W > DAT_W) ? DAT_W : (gk*BLK_W + BLK_W)) - gk*BLK_W)-1:0] sum1;
        wire                                                                             cout0;
        wire                                                                             cout1;

        // .DAT_W(W); i_a / i_b are i_a[HI-1:LO] / i_b[HI-1:LO]
        RIPPLE_ADDER #(
             .DAT_W  ( (((gk*BLK_W + BLK_W > DAT_W) ? DAT_W : (gk*BLK_W + BLK_W)) - gk*BLK_W) )
        ) U_CARRY_SELECT_ADDER_CIN0_RIPPLE_ADDER (
             .i_a    ( i_a[((gk*BLK_W + BLK_W > DAT_W) ? DAT_W : (gk*BLK_W + BLK_W))-1 : gk*BLK_W] )
            ,.i_b    ( i_b[((gk*BLK_W + BLK_W > DAT_W) ? DAT_W : (gk*BLK_W + BLK_W))-1 : gk*BLK_W] )
            ,.i_cin  ( 1'b0  )
            ,.o_sum  ( sum0  )
            ,.o_cout ( cout0 )
        );
        RIPPLE_ADDER #(
             .DAT_W  ( (((gk*BLK_W + BLK_W > DAT_W) ? DAT_W : (gk*BLK_W + BLK_W)) - gk*BLK_W) )
        ) U_CARRY_SELECT_ADDER_CIN1_RIPPLE_ADDER (
             .i_a    ( i_a[((gk*BLK_W + BLK_W > DAT_W) ? DAT_W : (gk*BLK_W + BLK_W))-1 : gk*BLK_W] )
            ,.i_b    ( i_b[((gk*BLK_W + BLK_W > DAT_W) ? DAT_W : (gk*BLK_W + BLK_W))-1 : gk*BLK_W] )
            ,.i_cin  ( 1'b1  )
            ,.o_sum  ( sum1  )
            ,.o_cout ( cout1 )
        );

        // o_sum[HI-1:LO]
        assign o_sum[((gk*BLK_W + BLK_W > DAT_W) ? DAT_W : (gk*BLK_W + BLK_W))-1 : gk*BLK_W] =
               block_cin[gk] ? sum1 : sum0;
        assign block_cin[gk+1] = block_cin[gk] ? cout1 : cout0;
    end
endgenerate

assign o_cout = block_cin[BLK_N];

endmodule
