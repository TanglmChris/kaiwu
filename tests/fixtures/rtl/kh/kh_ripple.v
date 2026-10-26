module KH_RIPPLE #(parameter DAT_W = 8) (
    input  wire [DAT_W-1:0] i_a,
    input  wire [DAT_W-1:0] i_b,
    output wire [DAT_W:0]   o_sum
);
    wire [DAT_W:0] c;
    assign c[0] = 1'b0;
    genvar gi;
    generate
        for (gi = 0; gi < DAT_W; gi = gi + 1) begin : GEN_FOR
            KH_FULL U_KH_RIPPLE_BIT_KH_FULL (.i_a(i_a[gi]), .i_b(i_b[gi]), .i_cin(c[gi]),
                                             .o_sum(o_sum[gi]), .o_cout(c[gi+1]));
        end
    endgenerate
    assign o_sum[DAT_W] = c[DAT_W];
endmodule
