//=============================================================================
// File    : rtl_module.v
// Module  : RTL_MODULE
// Purpose : Template: a small packet pipe written with every RTL convention
// Spec    : openspec/specs/rtl-structure-authority/spec.md
// Language: Verilog-2001 (assertions are SVA, compiled only under CBB_ASSERT_ON)
//=============================================================================
module RTL_MODULE #(
    //---- structure
     parameter DAT_W        = 32    // multiple of 16, >= 16
    ,parameter BEAT_NUM     = 8     // max beats per packet, power of 2, >= 2
    ,parameter HIST_NUM     = 2     // output history depth, >= 2
    ,parameter SCHEME       = 0     // 0 PASS, 1 INVERT, 2 SWAP (halves)
)(
     input  wire                        clk
    ,input  wire                        rst_n
    //---- src
    ,input  wire                        i_src_vld
    ,output wire                        o_src_rdy
    ,input  wire [DAT_W-1:0]            i_src_dat
    ,input  wire                        i_src_last
    //---- dst
    ,output wire                        o_dst_vld
    ,input  wire                        i_dst_rdy
    ,output wire [DAT_W-1:0]            o_dst_dat
    ,output wire [DAT_W/8-1:0]          o_dst_par
    ,output wire [$clog2(BEAT_NUM)-1:0] o_dst_cnt
    ,output wire [BEAT_NUM-1:0]         o_dst_cnt_oh
    //---- configuration
    ,input  wire                        i_cfg_hist_en
);

//---- function
function integer f_ceil_div;
    input integer dividend;
    input integer divisor;
    begin
        f_ceil_div = (dividend + divisor - 1) / divisor;
    end
endfunction

//---- localparam
localparam SCHEME_PASS   = 0;
localparam SCHEME_INVERT = 1;
localparam SCHEME_SWAP   = 2;

localparam BYTE_SIZE = 8;
localparam BYTE_NUM  = f_ceil_div(DAT_W, BYTE_SIZE);
localparam CNT_W     = $clog2(BEAT_NUM);
localparam HALF_SIZE = DAT_W / 2;          // GEN_SWAP; never inside generate

localparam [0:0] ST_IDLE = 1'b0;
localparam [0:0] ST_BUSY = 1'b1;

//---- payload: fields from MSB in port order
localparam SRC_PLD_W = DAT_W + 1;
localparam DST_PLD_W = DAT_W + BYTE_NUM;

//---- signal declaration
wire [SRC_PLD_W-1:0] src_pld;
reg                  src_vld_r;
wire                 src_rdy;
reg  [SRC_PLD_W-1:0] src_pld_r;
wire [DAT_W-1:0]     src_dat;
wire                 src_last;
wire                 src_hsk;
wire [DAT_W-1:0]     proc_dat;
reg  [0:0]           st_r;
reg  [0:0]           st_pre;
wire                 st_idle;
reg  [CNT_W-1:0]     cnt_r;
wire [CNT_W-1:0]     cnt_pre;
reg  [CNT_W-1:0]     cnt_1ff;
reg                  dst_vld_r;
reg  [DAT_W-1:0]     dst_dat_r;
wire [DAT_W-1:0]     dst_dat_pre;
wire [BYTE_NUM-1:0]  byte_par;
reg  [DAT_W-1:0]     hist_r [0:HIST_NUM-1];
wire [DST_PLD_W-1:0] dst_pld;
integer              bi;
genvar               gi;

//---- src: pack, forward register slice (valid with reset, payload without), unpack
assign src_pld   = {i_src_dat,i_src_last};
assign o_src_rdy = ~src_vld_r | src_rdy;

always@(posedge clk,negedge rst_n) begin : BLK_SRC_VLD
    if(rst_n == 1'b0) begin
        src_vld_r <= 1'b0;
    end else if(o_src_rdy == 1'b1) begin
        src_vld_r <= i_src_vld;
    end
end

always@(posedge clk) begin : BLK_SRC_PLD
    if((i_src_vld & o_src_rdy) == 1'b1) begin
        src_pld_r <= src_pld;
    end
end

assign {src_dat,src_last} = src_pld_r;
assign src_rdy                = ~dst_vld_r | i_dst_rdy;
assign src_hsk                = src_vld_r & src_rdy;

//---- data process: one branch per legal SCHEME
generate
    if(SCHEME == SCHEME_PASS) begin : GEN_PASS
        assign proc_dat = src_dat;
    end else if(SCHEME == SCHEME_INVERT) begin : GEN_INVERT
        assign proc_dat = ~src_dat;
    end else if(SCHEME == SCHEME_SWAP) begin : GEN_SWAP
        wire [HALF_SIZE-1:0] half_hi;
        wire [HALF_SIZE-1:0] half_lo;

        assign {half_hi,half_lo} = src_dat;
        assign proc_dat          = {half_lo,half_hi};
    end
endgenerate

//---- packet state: IDLE until the first beat, BUSY until the last
always@(*) begin : BLK_ST_PRE
    st_pre = st_r;
    case(st_r)
        ST_IDLE: begin
            if((src_hsk == 1'b1) && (src_last == 1'b0)) begin
                st_pre = ST_BUSY;
            end
        end
        ST_BUSY: begin
            if((src_hsk == 1'b1) && (src_last == 1'b1)) begin
                st_pre = ST_IDLE;
            end
        end
        default: begin
            st_pre = ST_IDLE;
        end
    endcase
end

always@(posedge clk,negedge rst_n) begin : BLK_ST
    if(rst_n == 1'b0) begin
        st_r <= ST_IDLE;
    end else begin
        st_r <= st_pre;
    end
end

assign st_idle = (st_r == ST_IDLE);

//---- beat counter: cleared by the last beat
assign cnt_pre = {CNT_W{~src_last}} & (cnt_r + 1'b1);

always@(posedge clk,negedge rst_n) begin : BLK_CNT
    if(rst_n == 1'b0) begin
        cnt_r <= {CNT_W{1'b0}};
    end else if(src_hsk == 1'b1) begin
        cnt_r <= cnt_pre;
    end
end

always@(posedge clk) begin : BLK_CNT_1FF
    if(src_hsk == 1'b1) begin
        cnt_1ff <= cnt_r;
    end
end

//---- dst register: valid with reset, data without
assign dst_dat_pre =   {DAT_W{ st_idle}} & proc_dat
                     | {DAT_W{~st_idle}} & (proc_dat ^ dst_dat_r);

always@(posedge clk,negedge rst_n) begin : BLK_DST_VLD
    if(rst_n == 1'b0) begin
        dst_vld_r <= 1'b0;
    end else if(src_rdy == 1'b1) begin
        dst_vld_r <= src_vld_r;
    end
end

always@(posedge clk) begin : BLK_DST_DAT
    if(src_hsk == 1'b1) begin
        dst_dat_r <= dst_dat_pre;
    end
end

//---- per-byte parity of the dst data
generate
    for(gi = 0; gi < BYTE_NUM; gi = gi + 1) begin : GEN_FOR_BYTE
        assign byte_par[gi] = ^dst_dat_r[gi*BYTE_SIZE +: BYTE_SIZE];
    end
endgenerate

//---- dst history, oldest last
always@(posedge clk) begin : BLK_HIST
    if(src_hsk == 1'b1) begin
        hist_r[0] <= dst_dat_r;
        for(bi = 1; bi < HIST_NUM; bi = bi + 1) begin : BLK_FOR
            hist_r[bi] <= hist_r[bi-1];
        end
    end
end

//---- dst outputs: current beat with parity, or the oldest history entry
assign dst_pld =   {DST_PLD_W{~i_cfg_hist_en}} & {dst_dat_r
                                                 ,byte_par}
                 | {DST_PLD_W{ i_cfg_hist_en}} & {hist_r[HIST_NUM-1]
                                                 ,{BYTE_NUM{1'b0}}};

assign {o_dst_dat,o_dst_par} = dst_pld;
assign o_dst_vld             = dst_vld_r;
assign o_dst_cnt             = cnt_1ff;

//---- beat count as one-hot: instance name is U_<this module>_<function>_<CBB>
CBB_BIN2ONEHOT #(
     .DAT_W  ( BEAT_NUM     )
    ,.ADDR_W ( CNT_W        )
) U_RTL_MODULE_CNT_CBB_BIN2ONEHOT (
     .i_bin  ( cnt_1ff      )
    ,.o_oh   ( o_dst_cnt_oh )
);

//---- parameter check
`ifdef CBB_PARAM_CHK_ON
generate
    if(   (SCHEME != SCHEME_PASS) && (SCHEME != SCHEME_INVERT)
       && (SCHEME != SCHEME_SWAP)) begin : GEN_SCHEME_CHK
        $error("RTL_MODULE: SCHEME is not 0/1/2");
    end
    if((DAT_W < 16) || ((DAT_W % 16) != 0)) begin : GEN_DAT_W_CHK
        $error("RTL_MODULE: DAT_W is not a multiple of 16");
    end
    if((BEAT_NUM < 2) || ((BEAT_NUM & (BEAT_NUM - 1)) != 0)) begin : GEN_BEAT_NUM_CHK
        $error("RTL_MODULE: BEAT_NUM is not a power of 2");
    end
    if(HIST_NUM < 2) begin : GEN_HIST_NUM_CHK
        $error("RTL_MODULE: HIST_NUM is less than 2");
    end
endgenerate
`endif

//---- assertion
`ifdef CBB_ASSERT_ON
M1_SRC_HOLD: assume property(@(posedge clk) disable iff(rst_n == 1'b0)
    i_src_vld & ~o_src_rdy |=> i_src_vld);
A1_DST_HOLD: assert property(@(posedge clk) disable iff(rst_n == 1'b0)
    o_dst_vld & ~i_dst_rdy |=> o_dst_vld & $stable(o_dst_dat))
    else $error("A1: o_dst_vld dropped or o_dst_dat changed while i_dst_rdy is low");
`endif

endmodule
