# DoW-849 微信机器人

基于WX849协议的Dify AI微信接入方案，支持私聊、群聊、图片识别、语音识别等功能（还在实验中，bug较多许多功能暂不可用）。

## 功能特点

- **多种协议支持**: 支持849(iPad)
- **高稳定性**: 基于成熟的WX849协议，连接稳定，功能丰富
- **多样化交互**: 支持文本、图片、语音、文件等多种消息类型
- **智能对话**: 对接Dify API，提供智能对话服务
- **灵活配置**: 支持白名单、黑名单等多样化配置

## 环境要求

- Python 3.11+
- Redis
- Windows 10/11、Linux或macOS

## 交流群
欢迎进群进行交流讨论

![qr](images/qr.png)

## 安装步骤

### 1. 下载源码

```bash
git clone https://github.com/WoodGoose/dow-849.git
cd dow-849
```

### 2. 安装依赖

```bash
# 安装基础依赖
pip install -r requirements.txt

# 安装可选依赖（语音识别等）
pip install -r requirements-optional.txt
```

### 3. 配置文件

复制`config-template.json`为`config.json`，并修改关键配置：

```json
{
    "dify_api_base": "https://api.dify.ai/v1",  
    "dify_api_key": "你的Dify_API_Key",       
    "channel_type": "wx849",             
    "wx849_api_host": "127.0.0.1",  # 微信849协议API地址
    "wx849_api_port": 9000,  # 微信849协议API端口
    "wx849_protocol_version": "849",  # 微信849协议版本，可选: "849", "855", "ipad"
    "wx849_ignore_mode": "None",  # 消息过滤模式，可选: None, Whitelist, Blacklist
    "wx849_whitelist": [],  # 白名单列表，当 wx849_ignore_mode 为 Whitelist 时生效
    "wx849_blacklist": [],  # 黑名单列表，当 wx849_ignore_mode 为 Blacklist 时生效
    "wx849_ignore_protection": False,  # 是否忽略保护模式
    "log_level": "INFO",     
    "debug": true,                       
    "model": "dify",                     
    "single_chat_prefix": [""],          
    "group_chat_prefix": ["@bot"],       
    "group_name_white_list": ["ALL_GROUP"] 
}
```

## 使用方法

#### Windows 用户

1. 运行 `scripts/wx849_start.bat` 脚本启动 WX849 协议服务
2. 等待服务完全启动后
3. 使用 `python app.py` 启动主程序

停止服务：
- 运行 `scripts/wx849_stop.bat` 脚本停止 WX849 协议服务

#### Linux/macOS 用户

1. 赋予脚本执行权限：`chmod +x scripts/wx849_start.sh`
2. 运行 `./scripts/wx849_start.sh` 脚本启动 WX849 协议服务
3. 等待服务完全启动后
4. 使用 `python app.py` 启动主程序

停止服务：
- 运行 `./scripts/wx849_stop.sh` 脚本停止 WX849 协议服务

## 消息交互

### 私聊交互
直接向机器人发送消息即可获得回复

### 群聊交互
默认使用`@bot`前缀，例如：`@bot 今天天气怎么样？`

## 常见问题

### 服务无法启动
- 检查Redis是否运行
- 检查端口是否被占用
- 尝试切换协议版本

### 登录问题
- 确保网络稳定
- 尝试重启服务
- 更换协议版本


## 注意事项

1. WX849协议为非官方实现，可能随微信更新而需要调整
2. 建议使用备用微信账号进行测试
3. 避免频繁登录/登出操作，防止触发风控
4. 定期更新代码以获取最新功能和修复

## 目录结构

```
dow-849/
├── channel/                    # 通道目录
│   ├── wx849/                  # WX849通道实现
│   │   ├── wx849_channel.py    # 通道主文件
│   │   └── wx849_message.py    # 消息处理
│   └── ...
├── lib/
│   └── wx849/                  # WX849协议库
│       ├── 849/                # 协议核心实现
│       └── WechatAPI/          # API接口实现
├── scripts/                    # 启动脚本
│   ├── wx849_start.bat         # Windows启动脚本
│   └── wx849_start.sh          # Linux启动脚本
├── config-template.json        # 配置模板
└── app.py                      # 主程序
```

## 更新与维护

1. 定期拉取最新代码：
   ```bash
   git pull
   ```

2. 更新依赖：
   ```bash
   pip install -r requirements.txt --upgrade
   ```

## 许可证

本项目采用MIT许可证。详见LICENSE文件。

## 贡献

感谢项目：[CoW(chatgpt-on-wechat)](https://github.com/zhayujie/chatgpt-on-wechat)与[DoW(dify-on-wechat)](https://github.com/hanfangyuan4396/dify-on-wechat)

提供了微信机器人的基础架构和核心功能

感谢[xxxbot-pad](https://github.com/NanSsye/xxxbot-pad)

提供的ipad协议跟接入的参考

因本人不会代码，此项目全由ai写作不好的地方
欢迎提交Pull Request或Issue来帮助改进本项目！

---

**免责声明**：本项目仅供学习和研究使用，请勿用于商业或违法用途。使用本项目产生的任何后果由用户自行承担。
