// 面积拆分夹具（area-breakdown）：层次 AREA_TOP → {AREA_LEAF ×2, AREA_MID → {AREA_SUB → AREA_MEM, AREA_MEM}}
module AREA_MEM #(parameter DAT_W = 8) (input wire clk, input wire we, input wire [DAT_W-1:0] d, output wire [DAT_W-1:0] q);
    reg [DAT_W-1:0] m0, m1;
    always @(posedge clk) if (we) begin m0 <= d; m1 <= m0; end
    assign q = m0 ^ m1;
endmodule

module AREA_SUB #(parameter DAT_W = 8) (input wire clk, input wire [DAT_W-1:0] d, output wire [DAT_W-1:0] q);
    wire [DAT_W-1:0] mq;
    reg  [DAT_W-1:0] r;
    AREA_MEM #(.DAT_W(DAT_W)) U_AREA_SUB_MEM (.clk(clk), .we(d[0]), .d(d + 1'b1), .q(mq));
    always @(posedge clk) r <= mq + d;
    assign q = r;
endmodule

module AREA_MID #(parameter DAT_W = 8) (input wire clk, input wire [DAT_W-1:0] d, output wire [DAT_W-1:0] q);
    wire [DAT_W-1:0] sq, mq;
    AREA_SUB #(.DAT_W(DAT_W)) U_AREA_MID_SUB (.clk(clk), .d(d), .q(sq));
    AREA_MEM #(.DAT_W(DAT_W)) U_AREA_MID_MEM (.clk(clk), .we(d[1]), .d(sq), .q(mq));
    assign q = sq & mq;
endmodule

module AREA_LEAF #(parameter DAT_W = 8) (input wire clk, input wire [DAT_W-1:0] d, output wire [DAT_W-1:0] q);
    reg [DAT_W-1:0] r;
    always @(posedge clk) r <= d * 3;
    assign q = r;
endmodule

module AREA_TOP #(parameter DAT_W = 8) (input wire clk, input wire [DAT_W-1:0] a, input wire [DAT_W-1:0] b,
                                        output wire [DAT_W-1:0] y);
    wire [DAT_W-1:0] l0, l1, m;
    AREA_LEAF #(.DAT_W(DAT_W)) U_AREA_TOP_LEAF0 (.clk(clk), .d(a), .q(l0));
    AREA_LEAF #(.DAT_W(DAT_W)) U_AREA_TOP_LEAF1 (.clk(clk), .d(b), .q(l1));
    AREA_MID  #(.DAT_W(DAT_W)) U_AREA_TOP_MID   (.clk(clk), .d(l0 ^ l1), .q(m));
    assign y = m | (l0 & l1);
endmodule
