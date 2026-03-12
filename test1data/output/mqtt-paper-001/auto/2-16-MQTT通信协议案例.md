# MQTT通信协议案例

# Revision History

<table><tr><td>Draft Date</td><td>Revision No.</td><td>Description</td></tr><tr><td>2024/09/30</td><td>V1.0</td><td>1. 初始版本。</td></tr></table>

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 1/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

# 目 录

前言.. 3

# 1 MQTT通信协议简介. 4

1.1 概述.  
1.2 应用场景.  
1.3 Mosquitto 工具安装

2mqtt_client案例. .6

2.1 案例说明...   
2.2 案例测试..   
2.2.1评估板发布/上位机订阅. .8   
2.2.2评估板订阅/上位机发布 .9   
2.3 案例编译. .10   
2.4 关键代码.

3 mqtt_sinewave_pub 案例.. .12

3.1 案例说明. 12  
3.2 案例测试..  
3.3 案例编译. 15  
3.4 关键代码. .16

更多帮助. .18

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 2/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

# 前言

本文主要介绍创龙科技TL3588-EVM评估板基于MQTT通信协议的开发案例，适用开发环境如下。

Windows 开发环境：Windows 7 64bit、Windows 10 64bit

虚拟机：VMware16.2.5

Linux 开发环境：Ubuntu20.04.6 64bit

U-Boot: U-Bo0t-2017.09

Kernel: Linux-5.10.160、Linux-RT-5.10.160

Debian: Debian 11

LinuxSDK:LinuxSDK-[版本号]（基于rk3588_linux_release_v1.2.1_20230720）

我司提供的 MQTT通信协议开发案例主要包括 mqtt_client 和 mqtt_sinewave_pub，位于产品资料“4-软件资料\Demo\mqtt-demos\”目录下。 包

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 3/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

# 1 MQTT通信协议简介

# 1.1概述

MQTT（Message Queuing Telemetry Transport，消息队列遥测传输协议），是一种基于发布/订阅(Publish/Subscribe)模式的“轻量级”通讯协议，该协议构建于TCP/IP 协议上，由 IBM在1999 年发布。MQTT最大优点在于，可以极少的代码和有限的带宽，为连接远程设备提供实时可靠的消息服务。 创龙

MQTT 是轻量、简单、开放和易于实现的，同时作为一种低开销、低带宽占用的即时通讯协议，使其在物联网、小型设备、移动应用等方面有较广泛的应用。

![](images/86fc7d59478b5764d39455f8aa57fb8042c1ea2f7350e390f4f9db989e147308.jpg)  
图1

MQTT具有如下特点：

（1）轻量可靠：MQTT 的报文格式精简、紧凑，可在严重受限的硬件设备和低带宽、高延迟的网络上实现稳定传输。

（2）发布/订阅模式(Publish/Subscribe)：发布/订阅模式的优点在于发布者与订阅者的解耦，实现异步协议。即订阅者与发布者无需建立直接连接，亦无需同时在线。

（3）为物联网而生：提供心跳机制、遗嘱消息、QoS质量等级 $^ +$ 离线消息、主题和安全管理等全面的物联网应用特性。

（4） 生态更完善：覆盖范围广，已成为众多云厂商物联网平台的标准通信协议。

# 因我们的存在，让嵌入式应用更简单

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 4/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

# 1.2应用场景

MQTT作为一种低开销，低带宽占用的即时通讯协议，可以极少的代码和带宽为联网设备提供实时可靠的消息服务，适用于硬件资源有限的设备及带宽有限的网络环境。常见的应用场景如下：

(1) 物联网M2M通信，物联网大数据采集(2) 移动即时消息及消息推送。 龙(3) 智能硬件、智能家居、智能电器。(4) 车联网通信，电动车站桩采集。(5) 智慧城市、远程医疗、远程教育。(6) 电力能源、石油能源。

# 1.3 Mosquitto 工具安装

Mosquitto 是一款开源的MQTT消息代理（服务器）软件，提供轻量级的、支持可发布/可订阅的的消息推送模式。我司提供的评估板文件系统已支持 Mosquitto 工具，本文mqtt_client案例采用Mosquitto工具演示 MQTT通信协议的通信功能。由于上位机Ubuntu系统作为通信对象，因此需在 Ubuntu 终端执行如下命令安装 Mosquitto 工具，出现提示时输入"Y"并按下回车即可。 型技

Host#sudo apt-get install mosquitto-clients

# 因我们的存在，让嵌入式应用更简单

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 5/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

![](images/838c73a7dc303b97ac995d023890e40349f4504921662b84643f45e9d5623f27.jpg)  
图2

# 2mqtt_client 案例

# 2.1案例说明

案例功能：使用 libmosquitto(MQTT version 5.0/3.1.1)的 API与 MQTT 代理服务器通信。基于 MQTT通信协议，实现发布和订阅消息功能。

程序流程图如下图所示。

# 因我们的存在，让嵌入式应用更简单

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 6/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

![](images/12228942f1fd622ee8912b7a1cefc1ab0b70ca0dc3876102acec288c8c8eb612.jpg)  
图3

# 2.2案例测试

本案例使用公网MQTT HiveMQ 服务器与上位机Ubuntu Mosquitto 工具通信。请通过网线将评估板千兆网口 ETH0 RGMII和上位机连接至公网，确保可正常访问互联网。

下表提供了可用的在线公共MQTT服务器，可根据需要自行切换。

表1  

<table><tr><td rowspan=1 colspan=1>服务器名称</td><td rowspan=1 colspan=1>Broker地址</td><td rowspan=1 colspan=1>TCP 端口</td><td rowspan=1 colspan=1>WebSocket</td></tr><tr><td rowspan=1 colspan=1>HiveMQ</td><td rowspan=1 colspan=1>broker.hivemq.com</td><td rowspan=1 colspan=1>1883</td><td rowspan=1 colspan=1>8000</td></tr><tr><td rowspan=1 colspan=1>Mosquitto</td><td rowspan=1 colspan=1>test.mosquitto.org</td><td rowspan=1 colspan=1>1883</td><td rowspan=1 colspan=1>80       创</td></tr><tr><td rowspan=1 colspan=1>Eclipse</td><td rowspan=1 colspan=1>mqtt.eclipseprojects.io</td><td rowspan=1 colspan=1>1883</td><td rowspan=1 colspan=1>80/443</td></tr><tr><td rowspan=1 colspan=1>EMQX（国内）</td><td rowspan=1 colspan=1>broker-cn.emqx.io</td><td rowspan=1 colspan=1>1883</td><td rowspan=1 colspan=1>8083/8084</td></tr></table>

评估板启动,将案例bin 目录下mqtt_client可执行文件拷贝至评估板文件系统的任意目录下，执行如下命令查看程序参数说明。

Target# ./mqtt_client --help

# 因我们的存在，让嵌入式应用更简单

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 7/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

![](images/ad5437d1e389a91bcff478325a576bc8accdc7d1717863923b6254f654835582.jpg)  
图4

# 2.2.1 评估板发布/上位机订阅

在上位机执行如下命令，使用 mosquitto_sub 工具订阅 MQTT主题。Host# mosquitto_sub -h broker.hivemq.com -p 1883 -t test/data参数解析：-h：指定MQTT 服务器；-p：指定 MQTT 服务器 TCP 端口；-t：定义MQTT主题，可自定义命名。

图5

在评估板文件系统执行如下命令发布消息至MQTT 服务器。

Target# ./mqtt_client -h broker.hivemq.com -p 1883 -M publish -t test/data -m 'www.tronlong.com'

参数解析：-h：MQTT 服务器-p：MQTT服务器端口 创龙-M：模式，publish 为发布，subscribe 为订阅-t：MQTT主题，可随便命名-m：发布的MQTT 消息

# 因我们的存在，让嵌入式应用更简单

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 8/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

![](images/2d671372791f75b5189ce71a2bc07605af5aa88f815835e676af53291ed068aa.jpg)  
图6评估板发布

消息发布成功后，上位机将从MQTT服务器接收到对应的消息。

![](images/5f4faad745c73a47473daaa1c739c519aa3b64b23a13136f6c1aa14d2eb940d0.jpg)  
图7上位机订阅

# 2.2.2评估板订阅/上位机发布

在评估板文件系统执行如下命令订阅 MQTT主题。

# Target#

./mqtt_client -h broker.hivemq.com -p 1883 -M subscribe -t test/data

![](images/54eb07c097f0dc7ba5c0f56f3581743e7c2b26db3dad0ad44c3f5371365d9b7a.jpg)  
图8

在上位机执行如下命令发布消息至MQTT 服务器。

Host#mosquitto_pub -h broker.hivemq.com -p 1883 -t test/data -m www.tronlong.com

![](images/a3fd5064815083835e6a0ca257e36c2f6f2b6c8f670f4c329e590bc2140ec6f6.jpg)  
图9上位机发布

消息发布成功后，评估板将从MQTT 服务器接收到对应消息。

![](images/ac665c79e8ed83e51c890acc1be79ef35c11b8ebd10fb5615848d7cbaa758dfe.jpg)  
图 10 评估板订阅

# 因我们的存在，让嵌入式应用更简单

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 9/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

# 2.3案例编译

将案例 src 文件夹拷贝至 Ubuntu工作目录下，请先确保已参考《Debian 系统使用手册》编译过 LinuxSDK。在案例 src 目录执行如下命令，配置交叉编译工具链环境变量，并修改Makefile文件。

Host#export PATH $=$ /home/tronlong/RK3588/rk3588_linux_release_v1.2.1/extra-tools/gcc -linaro-10.2.1-2021.01-x86_64_aarch64-linux-gnu/bin:\$PATH

Host#vim Makefile

图11

修改的内容如下：

![](images/df9787d75b575985f7234d5984aa5b82bd5ae56d9a333f25df509c7922db4e17.jpg)  
图12

执行如下命令，进行案例编译。编译完成后在当前目录下生成可执行文件。

Host#make CC=aarch64-linux-gnu-gcc

![](images/09bf073de35ab4834f6be190c93eedf910b599df59f0973231dfe056ca0fe0d9.jpg)  
图13

# 因我们的存在，让嵌入式应用更简单

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 10/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

# 2.4关键代码

（1）创建 Mosquitto 实例。

![](images/d76e24c53c96f051986616ba06b7fb052d4697be030ae71877fac45746d433d8.jpg)  
图14

(2） 设置回调函数。

![](images/9d2d2a0ffa077d7aaa2187c8b8051caef14f9c9d62111ab9067c97133305acaf.jpg)  
图15

# （3）连接MQTT服务器。

![](images/9ed3b290fb1869652765efa0a3d2193889e04d09f202cf1b6a1e3a3059379a17.jpg)  
图16

（4）发布消息。

# 因我们的存在，让嵌入式应用更简单

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 11/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

![](images/db860ac1635f1be8e2cb286421c747a5fec67376617bc6a86500c7e6b2c70153.jpg)  
图17

(5） 订阅主题。

![](images/db6bdc237ff4592f0f145ad3d8c56a23d0b7c6cbd329e139a2fea6568d5a046e.jpg)  
图18

# 3mqtt_sinewave_pub 案例

# 3.1案例说明

案例功能：使用 libmosquitto(MQTT version 5.0/3.1.1)的 API与 MQTT 代理服务器通信。评估板生成正弦波数据,每秒发送512个采样点的数据至MQTT服务器；上位机通过Web页面从MQTT服务器接收到数据后，将会绘制波形。

程序流程图如下图所示。

# 因我们的存在，让嵌入式应用更简单

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 12/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

![](images/017305d9ea5ed72a557f54f577b8744a7efe098e9ed21fbc384f44cae04831ad.jpg)  
图19

# 3.2 案例测试

本案例使用公网 MQTT HiveMQ 服务器与上位机Ubuntu Web 程序通信。请通过网线将评估板千兆网口 ETH0 RGMI和上位机连接至公网，确保可正常访问互联网。

评估板启动，将案例bin 目录下 mqtt_sinewave_pub 可执行文件拷贝至评估板文件系统的任意目录下，执行如下命令查看程序参数说明。

Target# ./mqtt_sinewave_pub --help

![](images/ed027d26fe44be5a1345231402b58c41bc31a7e873e5bceba3af7a70ff068973.jpg)  
图20

执行如下命令运行程序，连接MQTT服务器，并发送正弦波数据至MQTT服务器。

Target# ./mqtt_sinewave_pub -h broker.hivemq.com -p 1883

# 因我们的存在，让嵌入式应用更简单

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 13/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

![](images/35fb93dbbc89fbf33d242d2cb87a83f0351d0b00f3a835549db6f8ff24fb300c.jpg)  
图21

评估板程序运行后，在上位机使用浏览器打开"tools\web_mqtt_sub\"目录下的 index.html 文件。在弹出的Web 页面（如下图），依次输入MQTT 服务器：broker.hivemq.com，端口号：8000，最后点击连接，Web页面将会从MQTT 服务器获取正弦波数据并进行波形绘制。

备注：ARM 端 MQTT通信协议基于TCP 协议，Web 端 MQTT通信协议基于WebSocket 协议，因此使用的端口号不同。

![](images/07c6782fc073d2fabd6197ca960abf4dbbbd062da63219dc88f75b095196ba97.jpg)  
图22

# 因我们的存在，让嵌入式应用更简单

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 14/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

![](images/f0b71a8a0973277944c092522f5b88c5656465f2439eff989ee47f9662fc41db.jpg)  
图23

# 3.3案例编译

将案例 src文件夹拷贝至 Ubuntu 工作目录下，请先确保已参考《Debian 系统使用手册》编译过 LinuxSDK。在案例 src 目录执行如下命令，配置交叉编译工具链环境变量，并修改 Makefile 文件。 龙科

Host#export PATH $=$ /home/tronlong/RK3588/rk3588_linux_release_v1.2.1/extra-tools/gcc -linaro-10.2.1-2021.01-x86_64_aarch64-linux-gnu/bin:\$PATH

Host#vim Makefile

图24

修改的内容如下：

![](images/03633a4d486847322bd4d0a9f3b926165363af25b47285aa577ab8c8e01945d3.jpg)  
图25

执行如下命令，进行案例编译。编译完成后在当前目录下生成可执行文件。

Host#make $\complement { \mathsf { C } } =$ aarch64-linux-gnu-gcc

图26

# 3.4关键代码

（1）创建 Mosquitto 实例。

![](images/149565899f11799267c07b95909b1e35827961f50dd2905835b246ab34035bb5.jpg)  
图27

(2） 设置回调函数。

![](images/50acd96ee394b76db09361444b18e96050c6e2b404d5771f8a4efdae6628d1cd.jpg)  
图28

# 因我们的存在，让嵌入式应用更简单

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 16/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

（3）连接MQTT 服务器。

![](images/e764386b02d8d695e72bc10629f1409270a5a871f979a55b6baa527782a3f213.jpg)  
图29

（4） 发送数据。

![](images/8372c1ba77c4b4425f65b28868c5a0a9490b27f446152fe01333ec3740d82fcc.jpg)  
图30

# 因我们的存在，让嵌入式应用更简单

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 17/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734

# 更多帮助

销售邮箱：sales@tronlong.com技术邮箱：support@tronlong.com创龙总机：020-8998-6280技术热线：020-3893-9734创龙官网：www.tronlong.com技术论坛：www.51ele.net官方商城：tronlong.tmall.com

# 因我们的存在，让嵌入式应用更简单

公司官网：www.tronlong.com 销售邮箱：sales@tronlong.com 公司总机：020-8998-6280 18/18  
技术论坛：www.51ele.net 技术邮箱：support@tronlong.com 技术热线：020-3893-9734