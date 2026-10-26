// io_comb_loops 接入 run_config 的用例夹具（io-comb-loops 1.2）：S 侧一个通道、M 侧两个通道。
// m_r_rdy 组合依赖 m_r_flg —— 内部#264 的形状：对端声明 flg 随本方 rdy 变时成环。
// S → M 的组合直通（vld / 数据往前、rdy 往回）按 AXI 基线不成环。
module IODEPS_LOOP (
    input  wire       clk,
    input  wire       s_c_vld,
    input  wire [3:0] s_c_dat,
    output wire       s_c_rdy,
    output wire       m_c_vld,
    output wire [3:0] m_c_dat,
    input  wire       m_c_rdy,
    input  wire       m_r_vld,
    input  wire       m_r_flg,
    output wire       m_r_rdy,
    output wire       s_r_vld,
    input  wire       s_r_rdy
);
    reg r_vld_r;
    always @(posedge clk) r_vld_r <= m_r_vld;
    assign m_c_vld = s_c_vld;
    assign m_c_dat = s_c_dat;
    assign s_c_rdy = m_c_rdy;
    assign m_r_rdy = m_r_flg ? s_r_rdy : 1'b1;
    assign s_r_vld = r_vld_r;
endmodule
