//=============================================================================
// File    : cbb_onehot2bin.v
// Module  : CBB_ONEHOT2BIN
// Purpose : One-hot (or all-zero) vector to binary index
// Spec    : cbb/cbb_onehot2bin/spec.CBB_ONEHOT2BIN.md
// Language: Verilog-2001 (assertions are SVA, compiled only under CBB_ASSERT_ON)
//=============================================================================
module CBB_ONEHOT2BIN #(
     parameter DAT_W  = 16
    ,parameter ADDR_W = $clog2(DAT_W)
)(
     input  wire [DAT_W-1:0]  i_oh
    ,output wire [ADDR_W-1:0] o_bin
);

//---- function
function [DAT_W-1:0] f_idx_mask;
    input integer bit_idx;
    integer idx;
    begin
        f_idx_mask = {DAT_W{1'b0}};
        for(idx = 0; idx < DAT_W; idx = idx + 1) begin
            f_idx_mask[idx] = (((idx >> bit_idx) % 2) == 1);
        end
    end
endfunction

//---- localparam
localparam CNT_W = $clog2(DAT_W);

//---- signal declaration
genvar gi;

//---- index bit gi: OR of the inputs whose index has bit gi set
generate
    for(gi = 0; gi < ADDR_W; gi = gi + 1) begin : GEN_FOR_BIN
        if(gi < CNT_W) begin : GEN_POS
            assign o_bin[gi] = |(i_oh & f_idx_mask(gi));
        end else begin : GEN_ZERO
            assign o_bin[gi] = 1'b0;
        end
    end
endgenerate

//---- parameter check
`ifdef CBB_PARAM_CHK_ON
generate
    if(DAT_W < 2) begin : GEN_DAT_W_CHK
        $error("CBB_ONEHOT2BIN: DAT_W is less than 2");
    end
    if(ADDR_W < CNT_W) begin : GEN_ADDR_W_CHK
        $error("CBB_ONEHOT2BIN: ADDR_W is less than $clog2(DAT_W)");
    end
endgenerate
`endif

//---- assertion
`ifdef CBB_ASSERT_ON
always@(*) begin : BLK_ASSERT
    if($onehot(i_oh) && (((i_oh >> o_bin) & {{(DAT_W-1){1'b0}},1'b1}) == {DAT_W{1'b0}})) begin
        $error("A1: i_oh[o_bin] is not set for a one-hot input");
    end
    if((i_oh == {DAT_W{1'b0}}) && (o_bin != {ADDR_W{1'b0}})) begin
        $error("A2: o_bin is not 0 for an all-zero input");
    end
    if((o_bin >> CNT_W) != {ADDR_W{1'b0}}) begin
        $error("A3: o_bin has a set bit above $clog2(DAT_W)");
    end
end
`endif

endmodule
