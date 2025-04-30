# DoW-849 微信机器人

基于WX849协议的Dify AI微信接入方案，支持私聊、群聊、图片识别、语音识别等功能。

## 功能特点

- **多种协议支持**: 支持849(iPad)、855(安卓PAD)、iPad新版协议
- **高稳定性**: 基于成熟的WX849协议，连接稳定，功能丰富
- **多样化交互**: 支持文本、图片、语音、文件等多种消息类型
- **智能对话**: 对接Dify API，提供智能对话服务
- **灵活配置**: 支持白名单、黑名单等多样化配置

## 环境要求

- Python 3.8+
- Redis服务器
- Windows 10/11、Linux或macOS
- 稳定的网络环境

## 安装步骤

### 1. 下载源码

```bash
git clone https://github.com/你的用户名/dow-849.git
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
  "wx849_api_host": "127.0.0.1",       
  "wx849_api_port": 9011,              
  "wx849_protocol_version": "849",     
  "debug": true,                       
  "model": "dify",                     
  "single_chat_prefix": [""],          
  "group_chat_prefix": ["@bot"],       
  "group_name_white_list": ["ALL_GROUP"] 
}
```

## 使用方法

### Windows用户

1. 启动WX849服务
   ```bash
   scripts\wx849_start.bat
   ```

2. 扫描终端显示的二维码登录

3. 在另一个终端启动主程序
   ```bash
   python app.py
   ```

4. 关闭服务
   ```bash
   scripts\wx849_stop.bat
   ```

### Linux/Mac用户

1. 启动WX849服务
   ```bash
   chmod +x scripts/wx849_*.sh
   ./scripts/wx849_start.sh
   ```

2. 扫描终端显示的二维码登录

3. 在另一个终端启动主程序
   ```bash
   python3 app.py
   # 或使用
   ./start.sh
   ```

4. 关闭服务
   ```bash
   ./scripts/wx849_stop.sh
   ./stop.sh
   ```

## 消息交互

### 私聊交互
直接向机器人发送消息即可获得回复

### 群聊交互
默认使用`@bot`前缀，例如：`@bot 今天天气怎么样？`

### 基础命令
- `帮助`或`help`: 显示帮助信息
- `清空会话`或`clear`: 重置当前对话上下文
- `设置角色<角色名>`: 切换预设角色
- `/godmode <密码>`: 管理员模式

## 高级配置

### 协议版本选择

`wx849_protocol_version`可选以下值：
- `"849"`: iPad版本协议（稳定）
- `"855"`: 安卓PAD版本协议
- `"ipad"`: 新版iPad协议

### 消息过滤

```json
{
  "wx849_ignore_mode": "Whitelist",  
  "wx849_whitelist": ["wxid_xxx", "wxid_yyy"], 
  "wx849_blacklist": ["wxid_zzz"]
}
```

### 日志级别

```json
{
  "log_level": "INFO"  // DEBUG, INFO, WARNING, ERROR
}
```

## 常见问题

### 服务无法启动
- 检查Redis是否运行
- 检查端口是否被占用
- 尝试切换协议版本

### 登录问题
- 确保网络稳定
- 尝试重启服务
- 更换协议版本

### 消息不响应
- 检查白名单/黑名单配置
- 查看日志是否有错误
- 尝试使用`help`命令测试

### UNKNOWN错误
确保`wx849_channel.py`中添加了以下代码：
```python
# 添加 ContextType.UNKNOWN 类型（如果不存在）
if not hasattr(ContextType, 'UNKNOWN'):
    setattr(ContextType, 'UNKNOWN', 'UNKNOWN')
```

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

## 贡献指南

欢迎提交Pull Request或Issue来帮助改进本项目！

---

**免责声明**：本项目仅供学习和研究使用，请勿用于商业或违法用途。使用本项目产生的任何后果由用户自行承担。
