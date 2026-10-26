module NOEQ_TOP #(
    parameter DAT_W = 8
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire [DAT_W-1:0] i_dat,
    output reg  [DAT_W-1:0] o_dat
);

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        o_dat <= {DAT_W{1'b0}};
    end else begin
        o_dat <= i_dat;
    end
end

endmodule
