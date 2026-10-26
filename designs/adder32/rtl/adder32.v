//=============================================================================
// File    : adder32.v
// Module  : ADDER32
// Purpose : Parameterized adder: a carry structure per segment, PIPE_STAGES registers
// Spec    : designs/adder32/lrs.ADDER32.md
// Language: Verilog-2001
//=============================================================================
// The width is split into PIPE_STAGES+1 segments with registers on the carry
// chain between segments. The name ADDER32 is historical; DAT_W sets the width.
//
// NOTE: i_a / i_b are assumed stable for at least PIPE_STAGES+1 cycles after
// being applied. This models pipeline latency, not a streaming pipeline that
// accepts a new operand pair every cycle.
module ADDER32 #(
     parameter DAT_W       = 32
    ,parameter SCHEME      = 0   // 0 RIPPLE, 1 CLA, 2 CSEL, 3 SKLANSKY, 4 KOGGE_STONE, 5 BRENT_KUNG
    ,parameter PIPE_STAGES = 0   // 0, 1 or 2
    ,parameter CSEL_BLK_W  = 4   // used only by SCHEME CSEL
)(
     input  wire             clk
    ,input  wire             rst_n
    ,input  wire [DAT_W-1:0] i_a
    ,input  wire [DAT_W-1:0] i_b
    ,input  wire             i_cin
    ,output wire [DAT_W-1:0] o_sum
    ,output wire             o_cout
);

//---- localparam
localparam SEG_N = PIPE_STAGES + 1;
localparam SEG_W = DAT_W / SEG_N;

//---- signal declaration
wire [DAT_W-1:0] stage_sum_in  [0:SEG_N-1];
wire             stage_cin_in  [0:SEG_N-1];
wire [DAT_W-1:0] stage_sum_out [0:SEG_N-1];
wire             stage_cout    [0:SEG_N-1];
genvar           gk;

assign stage_sum_in[0] = {DAT_W{1'b0}};
assign stage_cin_in[0] = i_cin;

// Segment gk covers bits [LO, HI), inlined below:
//   LO = gk*SEG_W
//   HI = (gk == SEG_N-1) ? DAT_W : (gk*SEG_W + SEG_W)
//        the last segment takes the remainder when DAT_W is not a multiple of SEG_N
//   W  = HI - LO
generate
    for(gk = 0; gk < SEG_N; gk = gk + 1) begin : GEN_FOR_STAGE
        wire [(((gk == SEG_N-1) ? DAT_W : (gk*SEG_W + SEG_W)) - gk*SEG_W)-1:0] seg_sum;   // [W-1:0]
        wire                                                                   seg_cout;

        ADDER_CORE #(
             .DAT_W      ( (((gk == SEG_N-1) ? DAT_W : (gk*SEG_W + SEG_W)) - gk*SEG_W) )   // W
            ,.SCHEME     ( SCHEME     )
            ,.CSEL_BLK_W ( CSEL_BLK_W )
        ) U_ADDER32_SEG_ADDER_CORE (
             .i_a    ( i_a[((gk == SEG_N-1) ? DAT_W : (gk*SEG_W + SEG_W))-1 : gk*SEG_W] )   // i_a[HI-1:LO]
            ,.i_b    ( i_b[((gk == SEG_N-1) ? DAT_W : (gk*SEG_W + SEG_W))-1 : gk*SEG_W] )   // i_b[HI-1:LO]
            ,.i_cin  ( stage_cin_in[gk] )
            ,.o_sum  ( seg_sum          )
            ,.o_cout ( seg_cout         )
        );

        if(gk*SEG_W > 0) begin : GEN_LOW_PASS   // LO > 0: bits below pass through
            assign stage_sum_out[gk][(gk*SEG_W)-1:0] = stage_sum_in[gk][(gk*SEG_W)-1:0];
        end
        // stage_sum_out[gk][HI-1:LO] = seg_sum
        assign stage_sum_out[gk][((gk == SEG_N-1) ? DAT_W : (gk*SEG_W + SEG_W))-1 : gk*SEG_W] = seg_sum;
        if(((gk == SEG_N-1) ? DAT_W : (gk*SEG_W + SEG_W)) < DAT_W) begin : GEN_HIGH_PASS   // HI < DAT_W
            assign stage_sum_out[gk][DAT_W-1 : ((gk == SEG_N-1) ? DAT_W : (gk*SEG_W + SEG_W))] =
                   stage_sum_in[gk][DAT_W-1 : ((gk == SEG_N-1) ? DAT_W : (gk*SEG_W + SEG_W))];
        end
        assign stage_cout[gk] = seg_cout;

        if(gk < SEG_N-1) begin : GEN_REG
            reg [DAT_W-1:0] sum_r;
            reg             cout_r;

            always @(posedge clk or negedge rst_n) begin : BLK_SEG_REG
                if(!rst_n) begin
                    sum_r  <= {DAT_W{1'b0}};
                    cout_r <= 1'b0;
                end else begin
                    sum_r  <= stage_sum_out[gk];
                    cout_r <= stage_cout[gk];
                end
            end

            assign stage_sum_in[gk+1] = sum_r;
            assign stage_cin_in[gk+1] = cout_r;
        end
    end
endgenerate

assign o_sum  = stage_sum_out[SEG_N-1];
assign o_cout = stage_cout[SEG_N-1];

`ifdef CBB_PARAM_CHK_ON
generate
    if(DAT_W < SEG_N) begin : GEN_DAT_W_CHK
        $error("ADDER32: DAT_W is less than PIPE_STAGES+1");
    end
    if(   (SCHEME != 0) && (SCHEME != 1) && (SCHEME != 2) && (SCHEME != 3)
       && (SCHEME != 4) && (SCHEME != 5)) begin : GEN_SCHEME_CHK
        $error("ADDER32: SCHEME is not 0/1/2/3/4/5");
    end
    if((PIPE_STAGES != 0) && (PIPE_STAGES != 1) && (PIPE_STAGES != 2)) begin : GEN_PIPE_STAGES_CHK
        $error("ADDER32: PIPE_STAGES is not 0/1/2");
    end
    if(CSEL_BLK_W < 1) begin : GEN_CSEL_BLK_W_CHK
        $error("ADDER32: CSEL_BLK_W is less than 1");
    end
endgenerate
`endif

endmodule
