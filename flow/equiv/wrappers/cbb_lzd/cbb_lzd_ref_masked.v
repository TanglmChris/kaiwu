// CBB_LZD 的独立行为级参考（equiv-cbb-structures 的 D1）：MSB_EN = 0 找最低位的 1，
// = 1 找最高位的 1；o_enc 是位置，o_dec 是那一位的 one-hot，全零时 o_dec 为 0。
// 不复用 CBB_LZD 的 TOOL 结构。SCHEME 不用，只为让同一组 chparam 两侧都能套用（D2）。
module CBB_LZD_REF_MASKED #(parameter DAT_W = 16, parameter MSB_EN = 0, parameter SCHEME = 0) (
    input  wire [DAT_W-1:0]         i_dat,
    output reg  [$clog2(DAT_W)-1:0] o_enc,
    output reg  [DAT_W-1:0]         o_dec,
    output reg                      o_zero
);
    integer k, j;
    always @* begin
        o_enc  = {$clog2(DAT_W){1'b0}};
        o_dec  = {DAT_W{1'b0}};
        o_zero = 1'b1;
        for (j = 0; j < DAT_W; j = j + 1) begin
            k = (MSB_EN != 0) ? DAT_W - 1 - j : j;
            if (i_dat[k] && o_zero) begin
                o_enc    = k;
                o_dec[k] = 1'b1;
                o_zero   = 1'b0;
            end
        end
    end
endmodule
