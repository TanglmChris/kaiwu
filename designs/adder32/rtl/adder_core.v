//=============================================================================
// File    : adder_core.v
// Module  : ADDER_CORE
// Purpose : Pick one of six carry structures by SCHEME
// Spec    : designs/adder32/lld.ADDER32.md
// Language: Verilog-2001
//=============================================================================
// Hierarchy is kept by the flow (params.yaml keep_hierarchy), see FULL_ADDER.
module ADDER_CORE #(
     parameter DAT_W      = 32
    ,parameter SCHEME     = 0   // 0 RIPPLE, 1 CLA, 2 CSEL, 3 SKLANSKY, 4 KOGGE_STONE, 5 BRENT_KUNG
    ,parameter CSEL_BLK_W = 4   // speculation block width, used only by CSEL
)(
     input  wire [DAT_W-1:0] i_a
    ,input  wire [DAT_W-1:0] i_b
    ,input  wire             i_cin
    ,output wire [DAT_W-1:0] o_sum
    ,output wire             o_cout
);

//---- localparam
// numbering follows the values order in params.yaml; PREFIX_ADDER reuses it
localparam SCHEME_RIPPLE      = 0;
localparam SCHEME_CLA         = 1;
localparam SCHEME_CSEL        = 2;
localparam SCHEME_SKLANSKY    = 3;
localparam SCHEME_KOGGE_STONE = 4;
localparam SCHEME_BRENT_KUNG  = 5;

// Every branch lists the legal values it covers, with no catch-all else:
// an illegal SCHEME generates no branch, lint reports undriven outputs, and
// the CBB_PARAM_CHK_ON block below names it.
generate
    if(SCHEME == SCHEME_RIPPLE) begin : GEN_RIPPLE
        RIPPLE_ADDER #(
             .DAT_W  ( DAT_W  )
        ) U_ADDER_CORE_RIPPLE_RIPPLE_ADDER (
             .i_a    ( i_a    )
            ,.i_b    ( i_b    )
            ,.i_cin  ( i_cin  )
            ,.o_sum  ( o_sum  )
            ,.o_cout ( o_cout )
        );
    end else if(SCHEME == SCHEME_CLA) begin : GEN_CLA
        CLA_ADDER #(
             .DAT_W  ( DAT_W  )
        ) U_ADDER_CORE_CLA_CLA_ADDER (
             .i_a    ( i_a    )
            ,.i_b    ( i_b    )
            ,.i_cin  ( i_cin  )
            ,.o_sum  ( o_sum  )
            ,.o_cout ( o_cout )
        );
    end else if(SCHEME == SCHEME_CSEL) begin : GEN_CSEL
        CARRY_SELECT_ADDER #(
             .DAT_W  ( DAT_W      )
            ,.BLK_W  ( CSEL_BLK_W )
        ) U_ADDER_CORE_CSEL_CARRY_SELECT_ADDER (
             .i_a    ( i_a    )
            ,.i_b    ( i_b    )
            ,.i_cin  ( i_cin  )
            ,.o_sum  ( o_sum  )
            ,.o_cout ( o_cout )
        );
    end else if(   (SCHEME == SCHEME_SKLANSKY) || (SCHEME == SCHEME_KOGGE_STONE)
                || (SCHEME == SCHEME_BRENT_KUNG)) begin : GEN_PREFIX
        // the three prefix networks share one shell; SCHEME is passed through
        PREFIX_ADDER #(
             .DAT_W  ( DAT_W  )
            ,.SCHEME ( SCHEME )
        ) U_ADDER_CORE_PREFIX_PREFIX_ADDER (
             .i_a    ( i_a    )
            ,.i_b    ( i_b    )
            ,.i_cin  ( i_cin  )
            ,.o_sum  ( o_sum  )
            ,.o_cout ( o_cout )
        );
    end
endgenerate

`ifdef CBB_PARAM_CHK_ON
generate
    if(   (SCHEME != SCHEME_RIPPLE) && (SCHEME != SCHEME_CLA) && (SCHEME != SCHEME_CSEL)
       && (SCHEME != SCHEME_SKLANSKY) && (SCHEME != SCHEME_KOGGE_STONE)
       && (SCHEME != SCHEME_BRENT_KUNG)) begin : GEN_SCHEME_CHK
        $error("ADDER_CORE: SCHEME is not 0/1/2/3/4/5");
    end
endgenerate
`endif

endmodule
