// 参考口径夹具（内部#202）：静态输入 mode=1 时，只在 mode=0 用的乘法用不到；REF_ADD 是保层级的算子；
// U1 的 dbg 输出空连接 —— 正好撞 内部#205（opt_hier 碰上空连接报错），参考综合要绕开它
module REF_ADD #(parameter W = 8) (input wire [W-1:0] a, input wire [W-1:0] b, output wire [W-1:0] s);
    assign s = a + b;
endmodule

module SUB #(parameter W = 8) (input wire mode, input wire [W-1:0] a, input wire [W-1:0] b,
                               output wire [W-1:0] y, output wire [W-1:0] dbg);
    wire [W-1:0] s;
    REF_ADD #(.W(W)) U_ADD (.a(a), .b(b), .s(s));
    assign y   = mode ? s : (a * b) ^ s;
    assign dbg = a & b;
endmodule

module REF_TOP #(parameter W = 8) (input wire clk, input wire rst_n, input wire mode,
                                   input wire [W-1:0] a, input wire [W-1:0] b,
                                   output reg [W-1:0] q0, output reg [W-1:0] q1);
    wire [W-1:0] y0, y1, d0;
    SUB #(.W(W)) U0 (.mode(mode), .a(a), .b(b), .y(y0), .dbg(d0));
    SUB #(.W(W)) U1 (.mode(mode), .a(b), .b(a), .y(y1), .dbg( ));
    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin q0 <= 0; q1 <= 0; end
        else begin q0 <= y0 ^ d0; q1 <= y1; end
endmodule
