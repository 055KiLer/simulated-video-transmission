# 模拟图传串口桥（Simulated Video Transmission）

用一块 STM32F103C8T6 开发板 + RS232→TTL 模块，在**自定义控制器的 DB9 口（RS232 115200）**和**机器人图传串口（TTL 921600）**之间做双向透明转发。帧内容一个字节都不改写，接收完全交给 DMA，CPU 只在中断里记一个位置。

RoboMaster 2026 机甲大师高校系列赛 · 队内项目。

## 数据通路

```
自定义控制器 DB9 ──RS232 115200──► [RS232→TTL 模块] ──► PA3 = USART2_RX
                                                            │ DMA1_Ch6 (Circular 128B)
                                                            ▼
                                        rx2_buffer + IDLE 中断记录的写指针
                                                            │ 主循环 bridge_forward()
                                                            ▼
                                          HAL_UART_Transmit 阻塞发到 PA2 = USART2_TX ──► 控制器
                                          
机器人图传串口 ◄──TTL 921600── PA9 = USART1_TX
                  PA10 = USART1_RX ──► DMA1_Ch5 (Circular 512B) ──► rx1_buffer ──► 同上，转给 USART2
```

两个方向各自独立：RX 由 DMA 搬运（CPU 零参与），一帧收完由 USART 的 IDLE 中断记下写指针，主循环再把新到的字节按序发往对端。**发送用的是阻塞 `HAL_UART_Transmit`，不是 TX DMA** —— 921600 侧排空速度是 115200 侧的 8 倍，阻塞发不构成瓶颈，代码因此简单很多。

## 外设占用（以仓库里的代码为准）

| 外设 | 实例 | 引脚 | 参数 | 用途 |
|---|---|---|---|---|
| USART | USART1 | PA9 TX / PA10 RX | 921600 8N1 无流控 | 机器人图传串口 |
| USART | USART2 | PA2 TX / PA3 RX | 115200 8N1 无流控 | RS232 侧（经转接模块） |
| DMA1 | Channel 5 | — | Peripheral→Memory，**Circular**，512B | USART1_RX 搬运 |
| DMA1 | Channel 6 | — | Peripheral→Memory，**Circular**，128B | USART2_RX 搬运 |
| NVIC | — | — | 优先级分组 4 | USART1/2 全局中断 + DMA Ch5/Ch6 |
| RCC | HSE + PLL | 8MHz ×9 | **SYSCLK 72MHz** | 921600 的精度全靠它 |

HSE 起振失败时 `Error_Handler` 之前会静默回退 HSI，那样 USART1 的 921600 直接错，上板第一件事是确认 SYSCLK = 72MHz。

设计文档（`运行流程与外设清单.md`）里还规划了 **USART3 调试口打印统计、IWDG 看门狗、PC13 心跳 LED**，当前固件没有实现——透传本身不需要帧解析，先把通路跑稳再加。

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

本地自环接法（**不需要任何外部设备**，性价比最高的一步）：USB 调试器的串口引脚挂到 USART2，再用一根跳线把 USART1 自己环回自己。

```
调试器 TX ──► PA3 (USART2_RX)
调试器 RX ◄── PA2 (USART2_TX)
调试器 GND ── 板子 GND          ⚠️ 必须共地
跳线       PA9 (USART1_TX) ──► PA10 (USART1_RX)
```

```powershell
# 发一帧认得出的数据，看能否原样回来
tools/loopback_test.ps1 -PortName COM10 -Baud 115200

# 压力测试：包长扫描 + 512B 环形缓冲回绕 + 30Hz 持续流约 40s，逐帧按字节校验
tools/stress_test.ps1 -PortName COM10 -Baud 115200
```

`COM10` 是脚本里的默认值（对应 ST-Link 的虚拟串口），换机器先用
`Get-WmiObject -Class Win32_PnPEntity | Select Name` 查自己实际端口，别照抄。

```bash
# 分析串口助手存下来的原始抓包：按协议帧同步 + CRC8/CRC16 校验，输出命令码直方图
python tools/parse_capture.py capture.bin -v
```

这一步回答的是整个任务的分叉点——DB9 上到底跑哪些命令码，决定了固件是纯透传还是要按 cmd_id 过滤。

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

- [x] 协议要点摘录，帧格式与命令码确认（`0xA5 + len(2) + seq + CRC8 + cmd_id(2) + data + CRC16`，三条链路共用）
- [x] CubeMX 工程 + 双向透传固件（IDLE 中断定位帧尾 + DMA Circular 接收 + 主循环转发）
- [x] F1 HAL 的坑：串线上一个毛刺产生 FE/NE/ORE，HAL 会直接 `Abort` 掉 RX DMA 且永不恢复 → 主循环每圈检查接收状态，清标志、指针归零、重起 DMA
- [x] 本地回环验收：包长扫描与 512B 回绕 100% 无误；30Hz 长跑 1200 帧丢 3 帧（0.25%，低于被替代的无线图传 1~3% 指标）
- [ ] 接 RS232 模块 + 真实控制器，用 `parse_capture.py` 确认 DB9 上的命令码集合
- [ ] 接机器人主控板双向全链路

**已知边界（不是 bug）**：USART2 侧缓冲只有 128B 且没开半传输中断，连续无间隙突发超过 128B 会被环形覆盖。协议里最大单帧 39B，当前应用碰不到；将来要长突发需开 HT 中断或加大缓冲。

另外这三条不在代码里，但决定做出来的东西能不能上场，需要向硬件负责人确认：GH1.25 座子线序、板子供电路径、以及协议 `RobotModuleStatus` 中"图传模块状态"检测项——用有线替代图传会不会被判离线。
