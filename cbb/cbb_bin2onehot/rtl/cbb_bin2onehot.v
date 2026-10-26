//=============================================================================
// File    : cbb_bin2onehot.v
// Module  : CBB_BIN2ONEHOT
// Purpose : Binary index to one-hot vector, all-zero when the index is out of range
// Spec    : cbb/cbb_bin2onehot/spec.CBB_BIN2ONEHOT.md
// Language: Verilog-2001 (assertions are SVA, compiled only under CBB_ASSERT_ON)
//=============================================================================
module CBB_BIN2ONEHOT #(
     parameter DAT_W  = 16
    ,parameter ADDR_W = $clog2(DAT_W)
)(
     input  wire [ADDR_W-1:0] i_bin
    ,output wire [DAT_W-1:0]  o_oh
);

//---- decode: a shift by DAT_W or more gives all zeros
assign o_oh = {{(DAT_W-1){1'b0}},1'b1} << i_bin;

//---- parameter check
`ifdef CBB_PARAM_CHK_ON
generate
    if(DAT_W < 2) begin : GEN_DAT_W_CHK
        $error("CBB_BIN2ONEHOT: DAT_W is less than 2");
    end
    if(ADDR_W < $clog2(DAT_W)) begin : GEN_ADDR_W_CHK
        $error("CBB_BIN2ONEHOT: ADDR_W is less than $clog2(DAT_W)");
    end
endgenerate
`endif

//---- assertion
`ifdef CBB_ASSERT_ON
wire in_rng;
assign in_rng = ({{32{1'b0}},i_bin} < {{ADDR_W{1'b0}},DAT_W[31:0]});

always@(*) begin : BLK_ASSERT
    if(!$onehot0(o_oh)) begin
        $error("A1: o_oh has more than one set bit");
    end
    if(in_rng != (o_oh != {DAT_W{1'b0}})) begin
        $error("A2: o_oh is zero for an index in range, or nonzero out of range");
    end
    if(in_rng && (((o_oh >> i_bin) & {{(DAT_W-1){1'b0}},1'b1}) == {DAT_W{1'b0}})) begin
        $error("A3: o_oh[i_bin] is not set");
    end
end
`endif

endmodule
