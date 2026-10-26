module POINT_TOP #(
    parameter DAT_W = 8,
    parameter MODE  = 0,
    parameter NUM   = 2
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire [DAT_W-1:0] i_dat,
    output reg  [DAT_W-1:0] o_dat
);

wire [DAT_W-1:0] sum;

POINT_SUB #(.DAT_W(DAT_W)) U_POINT_TOP_ADD_POINT_SUB (.i_a(i_dat), .i_b(MODE ? o_dat : {DAT_W{1'b0}}), .o_sum(sum));

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        o_dat <= {DAT_W{1'b0}};
    end else if (NUM > 0) begin
        o_dat <= sum;
    end
end

endmodule
