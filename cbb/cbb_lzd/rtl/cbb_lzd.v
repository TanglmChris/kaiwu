//=============================================================================
// File    : cbb_lzd.v
// Module  : CBB_LZD
// Purpose : Find the lowest or highest set bit: position, one-hot and all-zero
// Spec    : cbb/cbb_lzd/spec.CBB_LZD.md
// Language: Verilog-2001 (assertions are SVA, compiled only under CBB_ASSERT_ON)
//=============================================================================
module CBB_LZD #(
     parameter DAT_W  = 16
    ,parameter ADDR_W = $clog2(DAT_W)
    ,parameter MSB_EN = 0
    ,parameter SCHEME = 0
)(
     input  wire [DAT_W-1:0]  i_dat
    ,output wire [ADDR_W-1:0] o_enc
    ,output wire [DAT_W-1:0]  o_dec
    ,output wire              o_zero
);

//---- localparam
localparam SCHEME_CLA        = 0;
localparam SCHEME_CLA_SHARED = 1;
localparam SCHEME_TOOL       = 2;

localparam CNT_W = $clog2(DAT_W);
localparam PAD_W = 1 << CNT_W;

//---- signal declaration
wire [PAD_W-1:0] dat_pad;
wire [PAD_W-1:0] lzd_in;
wire [CNT_W-1:0] lzd_cnt;
wire             lzd_zero;
wire [CNT_W-1:0] pos;
genvar           gi;
genvar           gj;
genvar           gk;

//---- pad to a power of 2, zeros on top
generate
    for(gi = 0; gi < PAD_W; gi = gi + 1) begin : GEN_FOR_PAD
        if(gi < DAT_W) begin : GEN_DAT
            assign dat_pad[gi] = i_dat[gi];
        end else begin : GEN_ZERO
            assign dat_pad[gi] = 1'b0;
        end
    end
endgenerate

//---- direction: the count is taken from the top, so the lowest-bit search reverses the bit order
generate
    if(MSB_EN == 1) begin : GEN_MSB
        assign lzd_in = dat_pad;
        assign pos    = ~lzd_cnt;
    end else if(MSB_EN == 0) begin : GEN_LSB
        for(gi = 0; gi < PAD_W; gi = gi + 1) begin : GEN_FOR_REV
            assign lzd_in[gi] = dat_pad[PAD_W-1-gi];
        end
        assign pos = lzd_cnt;
    end
endgenerate

//---- leading zero count of lzd_in
generate
    if(SCHEME == SCHEME_CLA) begin : GEN_CLA
        wire [2*PAD_W-2:0] orp;

        assign orp[PAD_W-1:0] = lzd_in;
        for(gi = 1; gi <= CNT_W; gi = gi + 1) begin : GEN_FOR_OR
            for(gj = 0; gj < (PAD_W >> gi); gj = gj + 1) begin : GEN_FOR_BIT
                assign orp[2*PAD_W-(2*PAD_W >> gi)+gj] =   orp[2*PAD_W-(2*PAD_W >> (gi-1))+2*gj+1]
                                                          | orp[2*PAD_W-(2*PAD_W >> (gi-1))+2*gj];
            end
        end
        assign lzd_zero         = ~orp[2*PAD_W-2];
        assign lzd_cnt[CNT_W-1] = ~orp[2*PAD_W-(2*PAD_W >> (CNT_W-1))+1];

        for(gi = 0; gi < CNT_W-1; gi = gi + 1) begin : GEN_FOR_CNT
            wire [2*(PAD_W >> (gi+1))-2:0]          g;
            wire [2*(PAD_W >> (gi+1))-CNT_W+gi-2:0] p;

            for(gk = 0; gk < (PAD_W >> (gi+1)); gk = gk + 1) begin : GEN_FOR_LEAF
                assign g[gk] = orp[2*PAD_W-(2*PAD_W >> gi)+2*gk+1];
                if(gk > 0) begin : GEN_P
                    assign p[gk-1] = ~orp[2*PAD_W-(2*PAD_W >> gi)+2*gk];
                end
            end
            for(gj = 1; ((PAD_W >> (gi+1)) >> gj) > 0; gj = gj + 1) begin : GEN_FOR_LVL
                for(gk = 0; gk < ((PAD_W >> (gi+1)) >> gj); gk = gk + 1) begin : GEN_FOR_NODE
                    if(gk == 0) begin : GEN_GO
                        assign g[2*(PAD_W >> (gi+1))-(2*(PAD_W >> (gi+1)) >> gj)] =
                                 g[2*(PAD_W >> (gi+1))-(2*(PAD_W >> (gi+1)) >> (gj-1))+1]
                               | p[2*(PAD_W >> (gi+1))-(2*(PAD_W >> (gi+1)) >> (gj-1))-(gj-1)]
                               & g[2*(PAD_W >> (gi+1))-(2*(PAD_W >> (gi+1)) >> (gj-1))];
                    end else begin : GEN_GP
                        assign g[2*(PAD_W >> (gi+1))-(2*(PAD_W >> (gi+1)) >> gj)+gk] =
                                 g[2*(PAD_W >> (gi+1))-(2*(PAD_W >> (gi+1)) >> (gj-1))+2*gk+1]
                               | p[2*(PAD_W >> (gi+1))-(2*(PAD_W >> (gi+1)) >> (gj-1))-(gj-1)+2*gk]
                               & g[2*(PAD_W >> (gi+1))-(2*(PAD_W >> (gi+1)) >> (gj-1))+2*gk];
                        assign p[2*(PAD_W >> (gi+1))-(2*(PAD_W >> (gi+1)) >> gj)-gj+gk-1] =
                                 p[2*(PAD_W >> (gi+1))-(2*(PAD_W >> (gi+1)) >> (gj-1))-(gj-1)+2*gk]
                               & p[2*(PAD_W >> (gi+1))-(2*(PAD_W >> (gi+1)) >> (gj-1))-(gj-1)+2*gk-1];
                    end
                end
            end
            assign lzd_cnt[gi] = ~g[2*(PAD_W >> (gi+1))-2];
        end
    end else if(SCHEME == SCHEME_CLA_SHARED) begin : GEN_CLA_SHARED
        wire [2*PAD_W-2:0] orp;

        assign orp[PAD_W-1:0] = lzd_in;
        for(gi = 1; gi <= CNT_W; gi = gi + 1) begin : GEN_FOR_OR
            for(gj = 0; gj < (PAD_W >> gi); gj = gj + 1) begin : GEN_FOR_BIT
                assign orp[2*PAD_W-(2*PAD_W >> gi)+gj] =   orp[2*PAD_W-(2*PAD_W >> (gi-1))+2*gj+1]
                                                          | orp[2*PAD_W-(2*PAD_W >> (gi-1))+2*gj];
            end
        end
        assign lzd_zero         = ~orp[2*PAD_W-2];
        assign lzd_cnt[CNT_W-1] = ~orp[2*PAD_W-(2*PAD_W >> (CNT_W-1))+1];

        for(gi = 0; gi < CNT_W-1; gi = gi + 1) begin : GEN_FOR_CNT
            wire [2*(PAD_W >> (gi+1))-2:0] g;

            for(gk = 0; gk < (PAD_W >> (gi+1)); gk = gk + 1) begin : GEN_FOR_LEAF
                assign g[gk] = orp[2*PAD_W-(2*PAD_W >> gi)+2*gk+1];
            end
            for(gj = 1; ((PAD_W >> (gi+1)) >> gj) > 0; gj = gj + 1) begin : GEN_FOR_LVL
                for(gk = 0; gk < ((PAD_W >> (gi+1)) >> gj); gk = gk + 1) begin : GEN_FOR_NODE
                    assign g[2*(PAD_W >> (gi+1))-(2*(PAD_W >> (gi+1)) >> gj)+gk] =
                              g[2*(PAD_W >> (gi+1))-(2*(PAD_W >> (gi+1)) >> (gj-1))+2*gk+1]
                           | ~orp[2*PAD_W-(2*PAD_W >> (gi+gj))+2*gk+1]
                           &  g[2*(PAD_W >> (gi+1))-(2*(PAD_W >> (gi+1)) >> (gj-1))+2*gk];
                end
            end
            assign lzd_cnt[gi] = ~g[2*(PAD_W >> (gi+1))-2];
        end
    end else if(SCHEME == SCHEME_TOOL) begin : GEN_TOOL
        wire [(PAD_W+1)*CNT_W-1:0] chain;

        assign chain[CNT_W-1:0] = {CNT_W{1'b0}};
        for(gi = 0; gi < PAD_W; gi = gi + 1) begin : GEN_FOR_SCAN
            for(gj = 0; gj < CNT_W; gj = gj + 1) begin : GEN_FOR_BIT
                assign chain[(gi+1)*CNT_W+gj] =    lzd_in[gi] & (((gi >> gj) % 2) == 0)
                                                | ~lzd_in[gi] & chain[gi*CNT_W+gj];
            end
        end
        assign lzd_cnt  = chain[PAD_W*CNT_W+:CNT_W];
        assign lzd_zero = ~|lzd_in;
    end
endgenerate

//---- output
generate
    for(gi = 0; gi < ADDR_W; gi = gi + 1) begin : GEN_FOR_ENC
        if(gi < CNT_W) begin : GEN_POS
            assign o_enc[gi] = pos[gi];
        end else begin : GEN_ZERO
            assign o_enc[gi] = 1'b0;
        end
    end
endgenerate

assign o_dec  = {{(DAT_W-1){1'b0}},~lzd_zero} << pos;
assign o_zero = lzd_zero;

//---- parameter check
`ifdef CBB_PARAM_CHK_ON
generate
    if(DAT_W < 2) begin : GEN_DAT_W_CHK
        $error("CBB_LZD: DAT_W is less than 2");
    end
    if(ADDR_W < CNT_W) begin : GEN_ADDR_W_CHK
        $error("CBB_LZD: ADDR_W is less than $clog2(DAT_W)");
    end
    if((MSB_EN != 0) && (MSB_EN != 1)) begin : GEN_MSB_EN_CHK
        $error("CBB_LZD: MSB_EN is not 0/1");
    end
    if(   (SCHEME != SCHEME_CLA) && (SCHEME != SCHEME_CLA_SHARED)
       && (SCHEME != SCHEME_TOOL)) begin : GEN_SCHEME_CHK
        $error("CBB_LZD: SCHEME is not 0/1/2");
    end
endgenerate
`endif

endmodule
