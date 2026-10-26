module KH_CLA #(parameter DAT_W = 8) (
    input  wire [DAT_W-1:0] i_a,
    input  wire [DAT_W-1:0] i_b,
    output wire [DAT_W:0]   o_sum
);
    assign o_sum = i_a + i_b;
endmodule
