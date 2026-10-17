# 模拟图传串口桥（Simulated Video Transmission）

用一块 STM32F103C8T6 开发板 + RS232→TTL 模块，在**自定义控制器的 DB9 口（RS232 115200）**和**机器人图传串口（TTL 921600）**之间做双向透明转发。帧内容不改写，CPU 不参与逐字节收发。

RoboMaster 2026 机甲大师高校系列赛 · 队内项目。

## 数据通路

```
自定义控制器 DB9 ──RS232 115200──► [RS232→TTL 模块] ──► PA2/PA3 USART2
                                                                    │ DMA1_Ch4 (Circular 256B)
                                                                    ▼
                                       环形缓冲 bridge_forward()
                                                                    │
                          DMA1_Ch5 (Normal) ◄── USART1 PA9/PA10 ◄────┘
                                          │
机器人主控板图传串口 ◄──TTL 921600─────────┘
```

回程方向对称。921600 进 / 115200 出是"宽进窄出"，出向带宽只有入向 1/8，所以带溢出计数，不默默丢包。

## 外设占用

| 外设 | 实例 | 引脚 | 参数 | 用途 |
|---|---|---|---|---|
| USART | USART1 | PA9 / PA10 | 921600 8N1 | 机器人图传串口 |
| USART | USART2 | PA2 / PA3 | 115200 8N1 | RS232 侧（经转接模块） |
| USART | USART3 | PB10 / PB11 | 115200 | 调试口，打印统计 |
| DMA1 | Ch3/Ch4/Ch5/Ch6 | — | RX 用 Circular，TX 用 Normal | 四个方向的字节搬运 |
| IWDG | — | LSI 40kHz | ≈3.5 s | 死机自动复位 |
| GPIO | PC13 | 低电平点亮 | — | 心跳 LED，快闪=有错误 |

HSE 8MHz × PLL9 = SYSCLK 72MHz。921600 的波特率精度完全依赖 HSE 起振成功——`Error_Handler` 里 HSE 失败会静默回退 HSI，那样 USART1 直接出错，上板第一件事是确认 SYSCLK = 72MHz。

## 目录结构

```
.
├── Simulated Video Transmission/     CubeMX 工程（.ioc + 源码）
│   ├── Core/Src/main.c               桥逻辑：IDLE 取指针、环形缓冲、ORE 恢复
│   ├── Core/Src/stm32f1xx_it.c       USART1/2 中断里的 IDLE 处理
│   └── MDK-ARM/                      Keil 工程 + EIDE 配置
├── tools/                            PC 端调试脚本
├── docs/                             RoboMaster 2026 通信协议原文与要点摘录
├── 运行流程与外设清单.md               外设总清单、初始化与运行时数据流
├── 固件外设配置.md                    CubeMX 逐项配置、接线与烧板风险
├── 实施步骤.md                        按协议逐条推导的 6 步执行顺序
└── 模拟图传-任务拆解与执行计划.md        路线选择、时间表、BOM、风险
```

## 编译

工程同时保留了 Keil MDK 和 EIDE 两套配置，任选其一：

- **Keil**：打开 `Simulated Video Transmission/MDK-ARM/Simulated Video Transmission.uvprojx`，Build。
- **EIDE（VS Code）**：打开 `MDK-ARM` 目录，EIDE 插件首次构建会自动拉取 CMSIS 设备包并生成 `.cmsis/`，所以这个目录没有入库，属正常现象。

`build/`、`DebugConfig/`、Keil 的 Objects 目录都是编译产物，已由 `.gitignore` 排除，clone 后不需要手动创建。

## PC 端调试脚本

```powershell
# 本地自环（PA9↔PA3、PA10↔PA2 短接）：发一帧认得出的数据，看能否原样回来
tools/loopback_test.ps1 -PortName COM3 -Baud 115200

# 压力测试：包长扫描 + DMA 环形缓冲回绕 + 30Hz 持续流约 40s，逐帧按字节校验
tools/stress_test.ps1 -PortName COM3 -Baud 115200
```

```bash
# 分析串口助手存下来的原始抓包，按协议帧同步 + CRC8/CRC16 校验，输出命令码直方图
python tools/parse_capture.py capture.bin
```

串口号用 `Get-WmiObject -Class Win32_PnPEntity | Select Name` 查自己机器上的实际端口，别照抄文档里的编号。

## 文档索引

| 文件 | 什么时候看 |
|---|---|
| [实施步骤.md](实施步骤.md) | 想知道"现在该做哪一步"，以及每步的判据 |
| [运行流程与外设清单.md](运行流程与外设清单.md) | 想看完整数据流、RAM 预算、调试顺序 |
| [固件外设配置.md](固件外设配置.md) | 重新用 CubeMX 生成工程，或核对配置 |
| [模拟图传-任务拆解与执行计划.md](模拟图传-任务拆解与执行计划.md) | 硬件选型、BOM、两周时间表 |
| [docs/协议要点-2026通信协议V2.0.0.md](docs/协议要点-2026通信协议V2.0.0.md) | 帧格式、命令码、三条链路的差异 |
| `docs/RoboMaster2026通信协议V2.0.0.pdf` | 官方协议原文（20260626 版） |

## 状态

- [x] 协议要点摘录、帧格式与命令码确认
- [x] CubeMX 工程 + 双向透传固件（IDLE + DMA 环形缓冲）
- [x] HAL ORE 错误导致 RX DMA 被中止的问题：清标志并重新起 DMA，已在 `main.c` 处理
- [ ] 本地自环 10 万字节计数一致、`overflow = 0`
- [ ] DB9 实接 + 命令码分布确认
- [ ] 机器人主控板双向全链路，连续 10 分钟 `crc_err = 0`
- [ ] GH1.25 线序、板子供电路径、以及"有线替代图传是否被判离线"——需与硬件负责人确认
