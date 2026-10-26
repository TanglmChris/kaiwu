// io_comb_deps 的用例夹具（io-comb-deps 1.1）：每个输出对应 spec 的一个场景。
module IODEPS_MINI (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [1:0] i_a,      // 直通：o_y ← i_a
    input  wire       i_vld,    // 握手：o_rdy ← i_vld
    input  wire       i_c,      // 只进 mid[1]，mid[1] 不出端口
    input  wire       i_d,      // 只进 mid[0]：o_p ← i_d
    input  wire       i_e,      // 只经寄存器：o_q 不依赖任何输入
    input  wire       i_f,      // o_r ← i_f；复位不计
    input  wire       cfg_mode, // 静态端口：按排除模式不计
    output wire [1:0] o_y,
    output wire       o_rdy,
    output wire       o_p,
    output wire       o_q,
    output wire       o_r,
    output wire       o_s
);
    reg  [1:0] mid_r;
    reg        e_r;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mid_r <= 2'b00;
            e_r   <= 1'b0;
        end else begin
            mid_r <= {i_a[1], i_e};
            e_r   <= i_e;
        end
    end
    // 两位的字级异或：字级分析会把 i_c 也算进 o_p，逐位分析只剩 i_d
    wire [1:0] mid = {i_c, i_d} ^ mid_r;
    assign o_y   = {i_a[1] ^ mid_r[1], i_a[0]};
    assign o_rdy = ~i_vld;
    assign o_p   = mid[0];
    assign o_q   = e_r;
    assign o_r   = i_f & rst_n;
    assign o_s   = cfg_mode ^ e_r;
endmodule
