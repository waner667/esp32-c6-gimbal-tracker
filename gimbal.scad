// =====================================================================
//  USB 摄像头两轴云台 · 参数化模型（OpenSCAD）
//  舵机：SG90 ×2（已按查证尺寸写死）；主控 ESP32-C6；结构件 A1 mini 打印
//
//  用法：
//   1. 装 OpenSCAD（https://openscad.org，免费）
//   2. 打开本文件，顶部 part 变量选 "preview" 先看整机组装
//   3. 核对镜头筒位置参数 lens_z_off（唯一影响前避让的估算量）
//   4. 把 part 改成 "base" / "uframe" / "cradle"，逐个导出 STL
//      （OpenSCAD 菜单 Design → Export → STL）
//   5. STL 丢进 Bambu Studio 切片打印
//
//  坐标约定：
//    Z = 竖直向上（pan 轴方向，底座在底部）
//    X = 左右（tilt 轴方向，水平）
//    Y = 前后（摄像头镜头朝向 +Y）
//
//  ---- 2026-10-20 重修记录（v2）----
//  1. tilt 舵机改为中心轴沿 X（旧版轴沿 Z，摄像头只能偏航不能俯仰）；
//     舵机在横梁内偏置，输出轴心对 X=+6，cradle 插座几乎正对轴、无悬臂。
//  2. 摄像头夹改 桥(压顶)+背板+底托+底前唇 四向夹持：
//     - 旧版前唇四面悬空（不连背板不连底托）→ 已用顶部横桥连成整体；
//     - 旧版底托 Y 深度只有 1.8mm（PCB 底边只搭 0.3mm）→ 改为 7.8mm 全断面承托；
//     - 旧版臂插槽宽 3.0mm（SG90 单臂宽约 5mm 插不进）→ 改为 5.6mm 并放宽摆动让位。
//  3. U 框底盘坐到 pan 舵机臂板顶面（旧版下沉 3mm 与舵机/围框干涉）。
//  4. 两根立柱加 Ø5 走线通孔（摄像头信号线穿到 C6）。
//  5. 横梁加厚到 15mm（旧 14mm 时舵机腔上下壁仅 0.55mm）。
// =====================================================================

// ===================== SG90 舵机参数（已查证，一般不用改） =====================
servo_l     = 23.0;   // 机身长（安装耳分布方向）
servo_w     = 12.5;   // 机身厚（窄边）
servo_h     = 22.5;   // 机身高（输出轴方向）
ear_dx      = 13.5;   // 安装耳孔中心到中心距离（两孔距 ≈ 27）
ear_d       = 2.8;    // 安装耳孔直径
shaft_d     = 5.5;    // 输出轴花键外径
shaft_top   = 3.0;    // 轴高出机身顶的高度
screw_d     = 2.4;    // 自攻螺丝过孔直径（PLA 里自攻，比耳孔略小）
horn_boss_d = 6.0;    // 舵机臂中心套外径（套在轴上）
horn_arm_r  = 13.0;   // 舵机臂螺丝孔中心半径
horn_hole_d = 2.4;    // 舵机臂螺丝孔直径
horn_arm_w  = 5.0;    // SG90 单臂宽度（估，插槽按 5+间隙开）

// ===================== 摄像头参数（2026-10-20 waner 实测提供） =====================
//  安装方式：PCB 竖放（55mm 长边竖直），元件面朝前(+Y)，镜头轴线水平朝 +Y
pcb_w  = 19;     // PCB 短边（水平 X）——商品页 55*19，已确认
pcb_h  = 55;     // PCB 长边（竖直 Z）——商品页 55*19，已确认
pcb_t  = 1.8;    // ✅实测：将近两毫米
lens_d = 14.5;   // ✅实测：镜头筒外径 1.4~1.5cm，取中值
lens_h = 25;     // ✅实测：镜头筒高出板面约 2.5cm（沿 Y 伸出）
led_h  = 18;     // LED 灯柱高出板面避让高度（仍待核：量一下灯柱高度）
lens_z_off = 12; // ⚠️ 镜头筒心到 PCB 顶边的距离（估 12；导出前在 OpenSCAD 里核对，
                 //    它决定桥/底前唇与镜头筒的避让，估错会撞筒）
usb_dir = "";    // ⚠️ 出线方向仍待定（从 PCB 底边出线时无需改造背板；
                 //    若从顶边/侧边出，需在背板对应位置开出线槽）

// ===================== 结构通用参数 =====================
wall   = 2.0;   // 壁厚
clear  = 0.4;   // 装配间隙
post_h = 75;    // 立柱高（摄像头吊在 tilt 轴下 ~79mm，加高避免扫到底座围框）
tilt_axis_x = 6; // tilt 舵机输出轴心 X 偏置（机身 X -16.5~6，腔左壁仍有 1.3mm；
                 //   轴心越靠左腔左壁越薄，+6 是横梁 ±18 内的极限位置）

// =====================================================================
//  选择导出零件：preview（整机组装预览）/ base / uframe / cradle
// =====================================================================
part = "preview";

if (part == "base")    base();
if (part == "uframe")  uframe();
if (part == "cradle")  cradle();
if (part == "preview") {
  base();
  // U 框坐在 pan 舵机臂板顶面上（臂板顶 = base_th 7 + servo_h 22.5 + 板厚 2 = 31.5）
  translate([0, 0, servo_h + 9]) uframe();
  // cradle 原点 = tilt 舵机输出轴高度
  //   = uframe 底 31.5 + 底盘 7 + 立柱 75 + 横梁半厚 7.5
  translate([0, 0, servo_h + 9 + 7 + post_h + 15/2]) cradle();
}

// ===================== 1. 底座（容纳 pan 舵机 + 耳朵孔 + 轴让位） =====================
module base() {
  base_th = 7;                       // 底板厚
  wall_h  = servo_h + 2;             // 围框高（略高于机身）
  outer_l = 2*ear_dx + 2*wall;       // 必须包住耳朵孔：27 + 4 = 31
  outer_w = servo_w + 2*wall;        // 12.5 + 4 = 16.5

  difference() {
    union() {
      // 底板
      translate([0, 0, base_th/2])
        cube([outer_l, outer_w, base_th], center=true);
      // 机身围框（顶开口，舵机轴朝上）
      translate([0, 0, base_th + wall_h/2])
        cube([outer_l, outer_w, wall_h], center=true);
    }
    // 机身容纳腔（顶部开口）
    translate([0, 0, base_th + (servo_h + clear)/2])
      cube([servo_l + clear, servo_w + clear, servo_h + clear + 0.2], center=true);
    // 安装耳孔（自攻螺丝，贯穿底板+围框，此处是实心材料）
    for (sx = [-1, 1])
      translate([sx*ear_dx, 0, 0])
        cylinder(h = base_th + wall_h + 4, d = screw_d, $fn=18, center=true);
    // 中心轴让位孔（给花键轴让位，不顶到）
    translate([0, 0, base_th + servo_h/2])
      cylinder(h = servo_h + 6, d = shaft_d + 1.5, $fn=24, center=true);
  }
}

// ===================== 2. U 型框（pan 臂接口 + 双立柱 + 顶部横梁装 tilt 舵机） =====================
//  tilt 舵机姿态（v2 重修）：轴沿 X（水平），可做俯仰；
//    机身：X = servo_h 22.5（轴方向）、Y = servo_l 23（耳朵方向）、Z = servo_w 12.5（窄边）
//    偏置：轴心 X=+6，耳朵在 Y±13.5，耳朵螺丝沿 Z 竖直拧入横梁
module uframe() {
  bottom_t = 7;                       // 底盘厚
  post_w   = 9;                       // 立柱宽
  top_t    = 15;                      // 横梁厚（容纳 tilt 舵机 12.5 窄边，壁 ~1.2）
  post_x   = pcb_w/2 + post_w/2 + 4;  // 立柱中心 X（跨在 PCB 两侧外，PCB 竖放宽 19）
  span_l   = 2*post_x + post_w;       // U 框外宽

  // ---- 底盘（接 pan 舵机臂；底 = 臂板顶面，坐正不沉）----
  difference() {
    translate([0, 0, bottom_t/2])
      cube([span_l, span_l*0.7, bottom_t], center=true);
    // 中心 boss 让位
    translate([0, 0, -1])
      cylinder(h = bottom_t + 2, d = horn_boss_d + 0.3, $fn=24);
    // 舵机臂固定孔（2 个，半径 horn_arm_r）
    for (a = [45, 225]) {            // 对角线布置，避开立柱
      translate([horn_arm_r*cos(a), horn_arm_r*sin(a), 0])
        cylinder(h = bottom_t + 2, d = horn_hole_d, $fn=18, center=true);
    }
  }

  // ---- 两根立柱（各打 Ø5 走线通孔：摄像头线穿到 C6）----
  for (sx = [-1, 1])
    difference() {
      translate([sx*post_x, 0, bottom_t + post_h/2])
        cube([post_w, post_w, post_h], center=true);
      // 走线孔（偏后侧 Y-2，线走背板后面那侧；两柱都打，实际用一侧）
      translate([sx*post_x, -2, bottom_t + post_h/2])
        cylinder(h = post_h + 2, d = 5, $fn=24, center=true);
    }

  // ---- 顶部横梁（装 tilt 舵机，轴沿 X）----
  translate([0, 0, bottom_t + post_h + top_t/2]) {
    difference() {
      cube([span_l, post_w + servo_l + 2*wall, top_t], center=true);
      // tilt 舵机机身腔：轴沿 X。X=22.9(轴向) / Y=23.4(长边+耳) / Z=12.9(窄边)
      // 偏置：轴心 X=+6，腔中心 X = tilt_axis_x - servo_h/2 = -5.25
      translate([tilt_axis_x - servo_h/2, 0, 0])
        cube([servo_h + clear, servo_l + clear, servo_w + clear], center=true);
      // 轴让位孔（轴从端面 X=6 伸出 3mm，孔通到横梁端面）
      translate([tilt_axis_x + 6, 0, 0])
        rotate([0, 90, 0])
          cylinder(h = 14, d = shaft_d + 1.5, $fn=24, center=true);
      // 朝下大开口（tilt 舵机臂穿出 + 全行程摆动让位）：
      // 臂 X±3.1、插座顶面扫掠 Y±7（tilt 20°~110° 时前/后角上抬 ~±6.6）
      translate([tilt_axis_x, 0, 0])
        cube([14, 20, top_t + 2], center=true);
      // tilt 舵机耳朵固定孔（螺丝沿 Z 竖直拧入横梁，耳朵在 Y±ear_dx）
      for (sy = [-1, 1])
        translate([tilt_axis_x, sy*ear_dx, 0])
          cylinder(h = top_t + 4, d = screw_d, $fn=18, center=true);
    }
  }
}

// ===================== 3. 摄像头夹（PCB 模组版，v2 重修） =====================
//  结构：挂在 tilt 舵机单臂下方——臂插入顶部插槽、一颗自攻螺丝横穿（沿 Y）固定；
//        PCB 由 顶部横桥（压顶边）+ 背板（贴后）+ 底托（承底）+ 底前唇（压下部前缘）
//        四向夹持，从下方插入。
//  坐标：cradle 原点 = tilt 舵机输出轴高度（偏置 X=+6，插座中心对齐轴心）
//  避让：桥/底前唇位置按镜头筒（Ø14.5、筒心在 PCB 顶下 lens_z_off）让位；
//        臂末端（r≈16）最低点在背板顶上方 1mm、桥顶上方 2mm。
module cradle() {
  t      = 3;
  insert = 22;                    // PCB 顶边到舵机轴的距离（容纳臂长 r≤18 + 桥）
  bw     = pcb_w + 2*t;           // 结构件总宽 = 25
  z_top  = -insert;               // PCB 顶边 z = -22
  z_bot  = z_top - pcb_h;         // PCB 底边 z = -77（坐在底托上）
  z_back_top = -19;               // 背板顶（伸进插座/桥里熔接 1mm）
  z_lens_c   = z_top - lens_z_off;          // 镜头筒心 z = -34

  union() {
    // --- 顶部舵机臂插座（z: -20 ~ 0，中心对齐 tilt 轴 X=+6；加深到 -20 与背板/桥熔接）---
    difference() {
      translate([tilt_axis_x, 0, -10]) cube([14, 14, 20], center=true);
      // boss 让位（轴沿 X；中心下移 1.2 包容臂上套筒）
      translate([tilt_axis_x, -1.2, 0]) rotate([0, 90, 0])
        cylinder(h = 16, d = horn_boss_d + 0.8, $fn = 24, center=true);
      // 臂槽（宽 horn_arm_w+0.6 容臂宽；厚 6.8 含 tilt 摆动让位；贯穿插座底）
      translate([tilt_axis_x, 0, -10])
        cube([6.8, horn_arm_w + 0.6, 22], center=true);
      // 横穿自攻螺丝孔（沿 Y，对正舵机臂螺丝孔 r=13 → z=-13）
      translate([tilt_axis_x, 0, -horn_arm_r]) rotate([90, 0, 0])
        cylinder(h = 20, d = 2.0, $fn = 16, center=true);
    }

    // --- 顶部横桥（底面贴 PCB 顶边，把背板/前侧连成整体；PCB 从桥下插入）---
    translate([0, pcb_t/2, z_top + 2])
      cube([bw, pcb_t + 2*t + 3, 4], center=true);

    // --- 背板（贴住 PCB 背面，上端伸进插座/桥里熔接，下端伸进底托 1mm）---
    translate([0, -3, (z_back_top + z_bot - 5)/2])
      cube([bw, t, (z_back_top - (z_bot - 5))], center=true);

    // --- 底托（PCB 底边坐这里，承重；Y 从背板后沿 -4.5 到前唇后沿 3.3 全断面）---
    translate([0, (pcb_t - t)/2, z_bot - 2])
      cube([bw, pcb_t + t + 3, 4], center=true);

    // --- 底前唇（下端坐进底托 1mm，压住 PCB 下部前缘；顶面避让镜头筒底）---
    lip_bot = z_bot - 1;                  // 唇底 -78，伸进底托（-81~-77）熔接
    lip_h   = 16;                         // 唇高，唇顶 -62
    // 避让自检（OpenSCAD 控制台打印）：唇顶 -62 应远低于镜头筒底（lens_z_off=12 时 -41.25）
    echo(str("底前唇顶 z=", lip_bot + lip_h, " | 镜头筒底 z=", z_lens_c - lens_d/2));
    translate([0, pcb_t + 1.5 + t/2, lip_bot + lip_h/2])
      cube([bw, t, lip_h], center=true);
  }
}
