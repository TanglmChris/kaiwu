// 等价证明用的包装件（equiv-cbb-structures 的 D2），不是被测对象。
// CBB_LZD 的 o_enc 在全零输入时无意义；o_zero 为 1 时强制为 0，o_dec 与 o_zero 原样比。
module CBB_LZD_MASKED #(parameter DAT_W = 16, parameter MSB_EN = 0, parameter SCHEME = 0) (
    input  wire [DAT_W-1:0]         i_dat,
    output wire [$clog2(DAT_W)-1:0] o_enc,
    output wire [DAT_W-1:0]         o_dec,
    output wire                     o_zero
);
    wire [$clog2(DAT_W)-1:0] enc;
    CBB_LZD #(.DAT_W(DAT_W), .MSB_EN(MSB_EN), .SCHEME(SCHEME)) u (
        .i_dat(i_dat), .o_enc(enc), .o_dec(o_dec), .o_zero(o_zero));
    assign o_enc = o_zero ? {$clog2(DAT_W){1'b0}} : enc;
endmodule
