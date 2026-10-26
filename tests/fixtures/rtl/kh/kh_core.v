module KH_CORE #(parameter DAT_W = 8, parameter SCHEME = 0) (
    input  wire [DAT_W-1:0] i_a,
    input  wire [DAT_W-1:0] i_b,
    output wire [DAT_W:0]   o_sum
);
    generate
        if (SCHEME == 0) begin : GEN_RIPPLE
            KH_RIPPLE #(.DAT_W(DAT_W)) U_KH_CORE_SUM_KH_RIPPLE (.i_a(i_a), .i_b(i_b), .o_sum(o_sum));
        end else begin : GEN_CLA
            KH_CLA #(.DAT_W(DAT_W)) U_KH_CORE_SUM_KH_CLA (.i_a(i_a), .i_b(i_b), .o_sum(o_sum));
        end
    endgenerate
endmodule
