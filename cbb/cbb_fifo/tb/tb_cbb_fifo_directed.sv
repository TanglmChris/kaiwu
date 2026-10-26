//=============================================================================
// File    : tb_cbb_fifo_directed.sv
// Purpose : CBB_FIFO directed cases (内部#256): FIFO_DEP_N 2 / 8 x PT_EN 0 / 1, each checked every cycle against a
//           cycle model; reset, empty pass-through, empty store, hold, fill, full in / out in the same cycle,
//           pointer wrap, drain, clear, reset in the middle of a run
// Run     : iverilog -g2012 -s tb -o tb.vvp cbb/cbb_fifo/tb/tb_cbb_fifo_directed.sv cbb/cbb_fifo/rtl/cbb_fifo.v
//           vvp -n tb.vvp   (one PASS / FAIL line per instance, then the total; a failure exits non-zero by $fatal)
// Not in the flow: the flow runs tb/test_CBB_FIFO.py only, whose VCD gives the activity; this file does not touch it
//=============================================================================
`timescale 1ns/1ps

module fifo_dir_chk #(
     parameter DEP  = 2
    ,parameter PT   = 0
    ,parameter RST  = 0
    ,parameter SEED = 1
)(
     input  wire clk
    ,output reg  done
    ,output reg  fail
);

localparam AW = $clog2(DEP);
localparam CW = AW + 1;

reg           rst_n;
reg           clr;
reg           src_vld;
reg  [7:0]    src_dat;
reg           dst_rdy;
wire          src_rdy;
wire          dst_vld;
wire [7:0]    dst_dat;
wire [CW-1:0] cnt;
wire          afull;
wire          aempty;
wire          ovf;
wire          udf;

CBB_FIFO #(
     .DAT_W      (8    )
    ,.FIFO_DEP_N (DEP  )
    ,.PT_EN      (PT   )
    ,.RST_EN     (RST  )
) U_DUT (
     .clk         (clk          )
    ,.rst_n       (rst_n        )
    ,.i_clr       (clr          )
    ,.i_src_vld   (src_vld      )
    ,.o_src_rdy   (src_rdy      )
    ,.i_src_dat   (src_dat      )
    ,.o_dst_vld   (dst_vld      )
    ,.i_dst_rdy   (dst_rdy      )
    ,.o_dst_dat   (dst_dat      )
    ,.i_af_lvl    (DEP[CW-1:0]  )
    ,.i_ae_lvl    ({CW{1'b0}}   )
    ,.o_cnt       (cnt          )
    ,.o_afull     (afull        )
    ,.o_aempty    (aempty       )
    ,.o_overflow  (ovf          )
    ,.o_underflow (udf          )
);

//---- cycle model: the items in storage, head first
reg [7:0] mq [0:255];
integer   m_head;
integer   m_cnt;
integer   seed;
integer   t;
integer   errs;
integer   n_full_inout;     // full, PT_EN=1: one in and one out in the same cycle
integer   n_full_rdy_rej;   // full, PT_EN=0: downstream takes one, the source is still held back
integer   n_pt_direct;      // empty, PT_EN=1: passed through and taken, not written
integer   n_empty_store;    // empty: the source item is written (not taken / PT_EN=0)
integer   n_hold;           // valid not taken: next cycle must show the same head
integer   n_wr;             // writes into storage (pointer wrap = n_wr / DEP)
integer   n_clr;
integer   n_rst;
integer   n_udf;

reg       e_src_rdy;
reg       e_dst_vld;
reg [7:0] e_dst_dat;
reg       push;
reg       pop;
reg       byp;
reg       in_rst;
reg       prev_rst;

//---- stimulus segments (cycles after the first reset)
localparam S_PT    = 3;                 // vld 1 rdy 1 while empty
localparam S_STORE = S_PT + 1;          // vld 1 rdy 0 once
localparam S_HOLD  = S_STORE + 3;       // vld 0 rdy 0
localparam S_FILL  = S_HOLD + DEP + 2;  // vld 1 rdy 0 to full and beyond
localparam S_INOUT = S_FILL + 3*DEP + 2;// vld 1 rdy 1 at full (wraps the pointers)
localparam S_DRAIN = S_INOUT + DEP + 3; // vld 0 rdy 1 to empty and beyond
localparam S_CLR   = S_DRAIN + 5;       // 2 in, clear with vld 1 rdy 1, 2 idle
localparam S_RAND  = S_CLR + 300;       // random
localparam S_MRST  = S_RAND + 2;        // reset in the middle of a run
localparam S_END   = S_MRST + 60;       // random again

initial begin
    done = 1'b0; fail = 1'b0; seed = SEED; t = -3; errs = 0;
    n_full_inout = 0; n_full_rdy_rej = 0; n_pt_direct = 0; n_empty_store = 0; n_hold = 0; n_wr = 0;
    n_clr = 0; n_rst = 0; n_udf = 0;
    m_head = 0; m_cnt = 0; prev_rst = 1'b1;
    rst_n = 1'b0; clr = 1'b0; src_vld = 1'b0; src_dat = 8'd0; dst_rdy = 1'b0;
end

always@(negedge clk) begin : BLK_DRIVE
    t = t + 1;
    src_dat = $random(seed);
    clr     = 1'b0;
    rst_n   = 1'b1;
    if(t < 0) begin
        rst_n = 1'b0; src_vld = 1'b0; dst_rdy = 1'b0;
    end else if(t < S_PT) begin
        src_vld = 1'b1; dst_rdy = 1'b1;
    end else if(t < S_STORE) begin
        src_vld = 1'b1; dst_rdy = 1'b0;
    end else if(t < S_HOLD) begin
        src_vld = 1'b0; dst_rdy = 1'b0;
    end else if(t < S_FILL) begin
        src_vld = 1'b1; dst_rdy = 1'b0;
    end else if(t < S_INOUT) begin
        src_vld = 1'b1; dst_rdy = 1'b1;
    end else if(t < S_DRAIN) begin
        src_vld = 1'b0; dst_rdy = 1'b1;
    end else if(t < S_CLR) begin
        src_vld = (t < S_DRAIN + 3); dst_rdy = (t == S_DRAIN + 2); clr = (t == S_DRAIN + 2);
    end else if(t < S_RAND) begin
        src_vld = ($random(seed) & 15) < 10; dst_rdy = ($random(seed) & 15) < 10; clr = ($random(seed) & 63) == 0;
    end else if(t < S_MRST) begin
        rst_n = 1'b0; src_vld = $random(seed); dst_rdy = $random(seed);
    end else if(t < S_END) begin
        src_vld = ($random(seed) & 15) < 11; dst_rdy = ($random(seed) & 15) < 8;
    end else begin
        src_vld = 1'b0; dst_rdy = 1'b0;
        if(done == 1'b0) begin
            fail = (errs != 0)
                 | ((PT == 1) & ((n_full_inout == 0) | (n_pt_direct == 0)))
                 | ((PT == 0) & (n_full_rdy_rej == 0))
                 | (n_empty_store == 0) | (n_hold == 0) | (n_wr < 2*DEP) | (n_clr == 0) | (n_rst < 2) | (n_udf == 0);
            $display("%s cbb_fifo_directed DEP=%0d PT_EN=%0d RST_EN=%0d errs %0d FULL_INOUT %0d FULL_RDY_REJ %0d PT_DIRECT %0d EMPTY_STORE %0d HOLD %0d WRAP %0d CLR %0d RESET %0d UNDERFLOW %0d",
                     fail ? "FAIL" : "PASS", DEP, PT, RST, errs, n_full_inout, n_full_rdy_rej, n_pt_direct,
                     n_empty_store, n_hold, n_wr / DEP, n_clr, n_rst, n_udf);
            done = 1'b1;
        end
    end
end

task automatic chk(input [8*12-1:0] name, input [31:0] got, input [31:0] exp);
    if(got !== exp) begin                // !== so an X / Z output counts as a mismatch
        errs = errs + 1;
        if(errs <= 5)
            $display("  DEP=%0d PT_EN=%0d t=%0d: %0s = %0d, expected %0d", DEP, PT, t, name, got, exp);
    end
endtask

always@(posedge clk) begin : BLK_CHECK
    in_rst = (rst_n == 1'b0);
    if(in_rst) begin
        m_head = 0; m_cnt = 0;
    end else if(done == 1'b0) begin
        if(prev_rst) n_rst = n_rst + 1;     // first cycle after a reset release (A8 is the model check of this cycle)
        // expected outputs from the model and this cycle's inputs
        e_src_rdy = (m_cnt != DEP) | ((PT == 1) & dst_rdy);
        e_dst_vld = (m_cnt != 0) | ((PT == 1) & src_vld);
        e_dst_dat = (m_cnt != 0) ? mq[m_head % 256] : src_dat;
        chk("o_cnt",       cnt,     m_cnt);
        chk("o_src_rdy",   src_rdy, e_src_rdy);
        chk("o_dst_vld",   dst_vld, e_dst_vld);
        chk("o_afull",     afull,   m_cnt >= DEP);
        chk("o_aempty",    aempty,  m_cnt <= 0);
        chk("o_overflow",  ovf,     src_vld & ~e_src_rdy);
        chk("o_underflow", udf,     dst_rdy & ~e_dst_vld);
        if(e_dst_vld) chk("o_dst_dat", dst_dat, e_dst_dat);
        // advance the model
        push = src_vld & e_src_rdy;
        pop  = e_dst_vld & dst_rdy;
        byp  = (PT == 1) & (m_cnt == 0) & push & pop;
        if((m_cnt == DEP) & push & pop) n_full_inout = n_full_inout + 1;
        if((m_cnt == DEP) & src_vld & dst_rdy & ~push) n_full_rdy_rej = n_full_rdy_rej + 1;
        if(byp) n_pt_direct = n_pt_direct + 1;
        if((m_cnt == 0) & push & ~byp) n_empty_store = n_empty_store + 1;
        if(e_dst_vld & ~dst_rdy & ~clr) n_hold = n_hold + 1;
        if(dst_rdy & ~e_dst_vld) n_udf = n_udf + 1;
        if(clr) n_clr = n_clr + 1;
        if(!byp) begin
            if(pop) begin
                m_head = m_head + 1; m_cnt = m_cnt - 1;
            end
            if(push) begin
                mq[(m_head + m_cnt) % 256] = src_dat; m_cnt = m_cnt + 1; n_wr = n_wr + 1;
            end
        end
        if(clr) m_cnt = 0;
    end
    prev_rst = in_rst;
end

endmodule

module tb;

reg  clk;
wire [3:0] done;
wire [3:0] fail;

initial clk = 1'b0;
always #5 clk = ~clk;

fifo_dir_chk #(.DEP(2), .PT(0), .RST(0), .SEED(256021)) U_D2_P0 (.clk(clk), .done(done[0]), .fail(fail[0]));
fifo_dir_chk #(.DEP(2), .PT(1), .RST(1), .SEED(256022)) U_D2_P1 (.clk(clk), .done(done[1]), .fail(fail[1]));
fifo_dir_chk #(.DEP(8), .PT(0), .RST(1), .SEED(256081)) U_D8_P0 (.clk(clk), .done(done[2]), .fail(fail[2]));
fifo_dir_chk #(.DEP(8), .PT(1), .RST(0), .SEED(256082)) U_D8_P1 (.clk(clk), .done(done[3]), .fail(fail[3]));

initial begin
    wait(&done);
    #1;
    if(|fail) $fatal(1, "FAIL tb_cbb_fifo_directed: %0d of 4 instances failed", $countones(fail));
    $display("PASS tb_cbb_fifo_directed: 4 instances");
    $finish;
end

initial begin
    #200000;
    $fatal(1, "FAIL tb_cbb_fifo_directed: timeout");
end

endmodule
