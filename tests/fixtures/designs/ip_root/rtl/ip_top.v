module IP_TOP #(
    parameter DAT_W = 8,
    parameter DEP_N = 2
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire [DAT_W-1:0] i_dat,
    output reg  [DAT_W-1:0] o_dat
);

wire [DAT_W-1:0] sum;

IP_SUB #(.DAT_W(DAT_W)) U_IP_TOP_ADD_IP_SUB (.i_a(i_dat), .i_b(o_dat), .o_sum(sum));

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        o_dat <= {DAT_W{1'b0}};
    end else begin
        o_dat <= sum;
    end
end

endmodule
