#!/bin/bash

# 定义颜色
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}+------------------------------------------------+${NC}"
echo -e "${BLUE}|         WX849 Protocol Service Starter         |${NC}"
echo -e "${BLUE}+------------------------------------------------+${NC}"

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 第一步：启动Redis服务
echo -e "${YELLOW}[1/3] 正在启动Redis服务...${NC}"
cd $PROJECT_ROOT/lib/wx849/849/redis
redis-server redis.conf &
REDIS_PID=$!
echo -e "${GREEN}Redis服务已启动，PID: $REDIS_PID${NC}"
sleep 2

# 第二步：启动PAD服务
echo -e "${YELLOW}[2/3] 正在启动 PAD 服务...${NC}"

# 读取配置文件中的协议版本
PROTOCOL_VERSION=$(grep "wx849_protocol_version" $PROJECT_ROOT/config.json | grep -o '"[0-9][0-9][0-9]"' | tr -d '"')

if [ -z "$PROTOCOL_VERSION" ]; then
    PROTOCOL_VERSION="849"
    echo -e "${YELLOW}未找到协议版本配置，使用默认版本: $PROTOCOL_VERSION${NC}"
else
    echo -e "${GREEN}使用配置的协议版本: $PROTOCOL_VERSION${NC}"
fi

# 根据协议版本选择不同的PAD目录
if [ "$PROTOCOL_VERSION" == "855" ]; then
    PAD_DIR="$PROJECT_ROOT/lib/wx849/849/pad2"
    echo -e "${BLUE}使用855协议 (pad2)${NC}"
elif [ "$PROTOCOL_VERSION" == "ipad" ]; then
    PAD_DIR="$PROJECT_ROOT/lib/wx849/849/pad3"
    echo -e "${BLUE}使用iPad协议 (pad3)${NC}"
else
    PAD_DIR="$PROJECT_ROOT/lib/wx849/849/pad"
    echo -e "${BLUE}使用849协议 (pad)${NC}"
fi

# 检查PAD目录是否存在
if [ ! -d "$PAD_DIR" ]; then
    echo -e "${RED}PAD目录 $PAD_DIR 不存在!${NC}"
    echo -e "${RED}正在关闭Redis服务...${NC}"
    kill $REDIS_PID
    exit 1
fi

# 启动PAD服务
cd $PAD_DIR
if [ -f "linuxService" ]; then
    chmod +x linuxService
    ./linuxService &
    PAD_PID=$!
    echo -e "${GREEN}PAD服务已启动，PID: $PAD_PID${NC}"
elif [ -f "linuxService.exe" ]; then
    wine linuxService.exe &
    PAD_PID=$!
    echo -e "${GREEN}PAD服务已启动 (通过Wine)，PID: $PAD_PID${NC}"
else
    echo -e "${RED}找不到PAD服务可执行文件!${NC}"
    echo -e "${RED}正在关闭Redis服务...${NC}"
    kill $REDIS_PID
    exit 1
fi

sleep 3

# 第三步：配置并启动主程序
echo -e "${YELLOW}[3/3] 配置完成，请扫描二维码登录微信...${NC}"
echo -e "${GREEN}WX849 协议服务已全部启动!${NC}"
echo
echo -e "${YELLOW}现在可以运行主程序，请确保在配置文件中设置:${NC}"
echo -e "${BLUE}  \"channel_type\": \"wx849\",${NC}"
echo -e "${BLUE}  \"wx849_protocol_version\": \"$PROTOCOL_VERSION\",${NC}"
echo -e "${BLUE}  \"wx849_api_host\": \"127.0.0.1\",${NC}"
echo -e "${BLUE}  \"wx849_api_port\": \"9000\"${NC}"
echo
echo -e "${YELLOW}提示: 如需停止WX849服务，请按Ctrl+C后运行 wx849_stop.sh 脚本${NC}"
echo -e "${BLUE}+------------------------------------------------+${NC}"

# 保持脚本运行
wait $PAD_PID
echo -e "${RED}PAD服务已停止，正在关闭Redis服务...${NC}"
kill $REDIS_PID
echo -e "${RED}所有服务已关闭${NC}" 