// 网表等价夹具（内部#186）：复位 sys_rst_n（异步低有效），clk_a 与 clk_b 各驱动一组寄存器
module EQV_TOP #(parameter DAT_W = 8) (input wire clk_a, input wire clk_b, input wire sys_rst_n,
                                      input wire [DAT_W-1:0] d, output wire [DAT_W-1:0] y);
    reg [DAT_W-1:0] ra, rb;
    always @(posedge clk_a or negedge sys_rst_n) if (!sys_rst_n) ra <= {DAT_W{1'b1}}; else ra <= d + 1'b1;
    always @(posedge clk_b or negedge sys_rst_n) if (!sys_rst_n) rb <= 0; else rb <= ra ^ d;
    assign y = rb;
endmodule
