// 测试夹具（内部#305）：DAT_W 个带异步复位的触发器，相邻位做一次异或再打拍，
// 于是有一条短的 reg -> reg 路径，而 rst_n 扇出到全部 DAT_W 个触发器的复位端。
module RST_FANOUT #(parameter DAT_W = 1024) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             i_d,
    output wire [DAT_W-1:0] o_q
);
    reg [DAT_W-1:0] q_r;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) q_r <= {DAT_W{1'b0}};
        else        q_r <= {q_r[DAT_W-2:0], i_d} ^ {1'b0, q_r[DAT_W-1:1]};
    end
    assign o_q = q_r;
endmodule
