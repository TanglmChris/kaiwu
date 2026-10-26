//=============================================================================
// File    : cbb_fifo.v
// Module  : CBB_FIFO
// Purpose : Synchronous FIFO with vld/rdy handshake, count and almost flags
// Spec    : cbb/cbb_fifo/spec.CBB_FIFO.md
// Language: Verilog-2001 (assertions are SVA, compiled only under CBB_ASSERT_ON)
//=============================================================================
module CBB_FIFO #(
     parameter DAT_W      = 32
    ,parameter FIFO_DEP_N = 4
    ,parameter PT_EN      = 0
    ,parameter RST_EN     = 0
)(
     input  wire                        clk
    ,input  wire                        rst_n
    ,input  wire                        i_clr
    ,input  wire                        i_src_vld
    ,output wire                        o_src_rdy
    ,input  wire [DAT_W-1:0]            i_src_dat
    ,output wire                        o_dst_vld
    ,input  wire                        i_dst_rdy
    ,output wire [DAT_W-1:0]            o_dst_dat
    ,input  wire [$clog2(FIFO_DEP_N):0] i_af_lvl
    ,input  wire [$clog2(FIFO_DEP_N):0] i_ae_lvl
    ,output wire [$clog2(FIFO_DEP_N):0] o_cnt
    ,output wire                        o_afull
    ,output wire                        o_aempty
    ,output wire                        o_overflow
    ,output wire                        o_underflow
);

//---- localparam
localparam ADDR_W = $clog2(FIFO_DEP_N);
localparam CNT_W  = ADDR_W + 1;

localparam [ADDR_W-1:0] PTR_ONE = 1;
localparam [CNT_W-1:0]  CNT_ONE = 1;
localparam [CNT_W-1:0]  CNT_DEP = {1'b1,{ADDR_W{1'b0}}};

//---- signal declaration
reg  [DAT_W-1:0]      mem_r [0:FIFO_DEP_N-1];
reg  [ADDR_W-1:0]     wr_ptr_r;
reg  [ADDR_W-1:0]     rd_ptr_r;
reg  [CNT_W-1:0]      cnt_r;
wire [CNT_W-1:0]      cnt_pre;
wire                  full;
wire                  empty;
wire                  wr_en;
wire                  rd_en;
wire [FIFO_DEP_N-1:0] wr_sel;
wire [DAT_W-1:0]      mem_rd_dat;
genvar                gi;

//---- status
assign full  = (cnt_r == CNT_DEP);
assign empty = (cnt_r == {CNT_W{1'b0}});

// PT mode reuses a slot released this cycle. Keep source valid independent of ready.
assign o_src_rdy   = (PT_EN == 1) ? (~full | i_dst_rdy) : ~full;
assign o_cnt       = cnt_r;
assign o_afull     = (cnt_r >= i_af_lvl);
assign o_aempty    = (cnt_r <= i_ae_lvl);
assign o_overflow  = i_src_vld & ~o_src_rdy;
assign o_underflow = i_dst_rdy & ~o_dst_vld;

//---- output: pass-through when empty (PT_EN=1) or storage only (PT_EN=0)
generate
    if(PT_EN == 1) begin : GEN_PT
        assign o_dst_vld = ~empty | i_src_vld;
        assign o_dst_dat =   {DAT_W{ empty}} & i_src_dat
                           | {DAT_W{~empty}} & mem_rd_dat;
        assign wr_en     = i_src_vld & o_src_rdy & ~(empty & i_dst_rdy);
    end else if(PT_EN == 0) begin : GEN_NPT
        assign o_dst_vld = ~empty;
        assign o_dst_dat = mem_rd_dat;
        assign wr_en     = i_src_vld & o_src_rdy;
    end
endgenerate

assign rd_en = i_dst_rdy & ~empty;

//---- pointer and count
assign cnt_pre = cnt_r + ({CNT_W{wr_en}} & CNT_ONE)
                       - ({CNT_W{rd_en}} & CNT_ONE);

always@(posedge clk,negedge rst_n) begin : BLK_WR_PTR
    if(rst_n == 1'b0) begin
        wr_ptr_r <= {ADDR_W{1'b0}};
    end else if(i_clr == 1'b1) begin
        wr_ptr_r <= {ADDR_W{1'b0}};
    end else if(wr_en == 1'b1) begin
        wr_ptr_r <= wr_ptr_r + PTR_ONE;
    end
end

always@(posedge clk,negedge rst_n) begin : BLK_RD_PTR
    if(rst_n == 1'b0) begin
        rd_ptr_r <= {ADDR_W{1'b0}};
    end else if(i_clr == 1'b1) begin
        rd_ptr_r <= {ADDR_W{1'b0}};
    end else if(rd_en == 1'b1) begin
        rd_ptr_r <= rd_ptr_r + PTR_ONE;
    end
end

always@(posedge clk,negedge rst_n) begin : BLK_CNT
    if(rst_n == 1'b0) begin
        cnt_r <= {CNT_W{1'b0}};
    end else if(i_clr == 1'b1) begin
        cnt_r <= {CNT_W{1'b0}};
    end else begin
        cnt_r <= cnt_pre;
    end
end

//---- storage
assign wr_sel     = {{(FIFO_DEP_N-1){1'b0}},wr_en} << wr_ptr_r;
assign mem_rd_dat = mem_r[rd_ptr_r];

generate
    for(gi = 0; gi < FIFO_DEP_N; gi = gi + 1) begin : GEN_FOR
        if(RST_EN == 1) begin : GEN_MEM_RST
            always@(posedge clk,negedge rst_n) begin : BLK_MEM
                if(rst_n == 1'b0) begin
                    mem_r[gi] <= {DAT_W{1'b0}};
                end else if(wr_sel[gi] == 1'b1) begin
                    mem_r[gi] <= i_src_dat;
                end
            end
        end else if(RST_EN == 0) begin : GEN_MEM
            always@(posedge clk) begin : BLK_MEM
                if(wr_sel[gi] == 1'b1) begin
                    mem_r[gi] <= i_src_dat;
                end
            end
        end
    end
endgenerate

//---- parameter check
`ifdef CBB_PARAM_CHK_ON
generate
    if(DAT_W < 1) begin : GEN_DAT_W_CHK
        $error("CBB_FIFO: DAT_W is less than 1");
    end
    if((FIFO_DEP_N < 2) || ((FIFO_DEP_N & (FIFO_DEP_N-1)) != 0)) begin : GEN_FIFO_DEP_N_CHK
        $error("CBB_FIFO: FIFO_DEP_N is not a power of 2 no less than 2");
    end
    if((PT_EN != 0) && (PT_EN != 1)) begin : GEN_PT_EN_CHK
        $error("CBB_FIFO: PT_EN is not 0/1");
    end
    if((RST_EN != 0) && (RST_EN != 1)) begin : GEN_RST_EN_CHK
        $error("CBB_FIFO: RST_EN is not 0/1");
    end
endgenerate
`endif

//---- assertion
`ifdef CBB_ASSERT_ON
reg              mon_past_vld_r;

// $past has no valid sample before the first edge after reset release (random initial value when a gated clock
// does not toggle during reset; after a mid-run reset it still holds the pre-reset sample, and Verilator only
// samples disable iff on clock edges), so A5, A6 and M10 are checked from the second edge; A8 uses
// mon_past_vld_r == 0 to find the first edge after reset release
always@(posedge clk,negedge rst_n) begin : BLK_MON_PAST_VLD
    if(rst_n == 1'b0) begin
        mon_past_vld_r <= 1'b0;
    end else begin
        mon_past_vld_r <= 1'b1;
    end
end

wire             mon_byp_take;
wire [CNT_W-1:0] mon_cnt_nxt;

assign mon_byp_take = (PT_EN == 1) & (o_cnt == {CNT_W{1'b0}}) & i_src_vld & i_dst_rdy;
assign mon_cnt_nxt  = o_cnt + ({CNT_W{i_src_vld & o_src_rdy & ~mon_byp_take}} & CNT_ONE)
                            - ({CNT_W{i_dst_rdy & o_dst_vld & ~mon_byp_take}} & CNT_ONE);

A1_CNT_MAX: assert property (@(posedge clk) disable iff(rst_n == 1'b0)
    o_cnt <= CNT_DEP)
    else $error("A1: o_cnt exceeds FIFO_DEP_N");
A2_SRC_RDY: assert property (@(posedge clk) disable iff(rst_n == 1'b0)
    o_src_rdy == ((o_cnt != CNT_DEP) | ((PT_EN == 1) & i_dst_rdy)))
    else $error("A2: o_src_rdy does not match the PT/full/ready contract");
A3_DST_VLD: assert property (@(posedge clk) disable iff(rst_n == 1'b0)
    o_dst_vld == ((o_cnt != {CNT_W{1'b0}}) | (PT_EN == 1) & i_src_vld))
    else $error("A3: o_dst_vld mismatch");
A4_AFULL_AEMPTY: assert property (@(posedge clk) disable iff(rst_n == 1'b0)
    (o_afull == (o_cnt >= i_af_lvl)) && (o_aempty == (o_cnt <= i_ae_lvl)))
    else $error("A4: o_afull / o_aempty mismatch");
A5_CNT_NXT: assert property (@(posedge clk) disable iff((rst_n == 1'b0) || (mon_past_vld_r == 1'b0))
    1'b1 |=> (o_cnt == ($past(i_clr) ? {CNT_W{1'b0}} : $past(mon_cnt_nxt))))
    else $error("A5: next o_cnt mismatch");
A6_DST_HOLD: assert property (@(posedge clk) disable iff((rst_n == 1'b0) || (mon_past_vld_r == 1'b0))
    o_dst_vld && !i_dst_rdy && !i_clr |=> o_dst_vld && $stable(o_dst_dat))
    else $error("A6: o_dst_vld / o_dst_dat changed before handshake");
A7_OVF_UDF: assert property (@(posedge clk) disable iff(rst_n == 1'b0)
    (o_overflow == (i_src_vld && !o_src_rdy)) && (o_underflow == (i_dst_rdy && !o_dst_vld)))
    else $error("A7: o_overflow / o_underflow mismatch");
A8_RST_REL: assert property (@(posedge clk) disable iff(rst_n == 1'b0)
    (mon_past_vld_r == 1'b0) |-> (o_cnt == {CNT_W{1'b0}}) && o_src_rdy
                               && (o_dst_vld == (i_src_vld && (PT_EN == 1))))
    else $error("A8: state after reset release mismatch");
M10_LVL_STABLE: assume property (@(posedge clk) disable iff((rst_n == 1'b0) || (mon_past_vld_r == 1'b0))
    $stable(i_af_lvl) && $stable(i_ae_lvl));
`endif

endmodule
