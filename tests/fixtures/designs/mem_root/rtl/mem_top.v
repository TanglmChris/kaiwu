// 行为模型存储器夹具（内部#188）：4 × DAT_W 的寄存器数组，同步写、寄存读，yosys 推断成 $mem
module MEM_TOP #(parameter DAT_W = 8) (input wire clk, input wire rst_n, input wire we,
                                      input wire [1:0] wa, input wire [1:0] ra, input wire [DAT_W-1:0] d,
                                      output reg [DAT_W-1:0] q);
    reg [DAT_W-1:0] mem [0:3];
    always @(posedge clk) if (we) mem[wa] <= d;
    always @(posedge clk or negedge rst_n) if (!rst_n) q <= 0; else q <= mem[ra];
endmodule
