#!/bin/bash

# 定义颜色
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}+------------------------------------------------+${NC}"
echo -e "${BLUE}|         WX849 Protocol Service Stopper         |${NC}"
echo -e "${BLUE}+------------------------------------------------+${NC}"

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 停止PAD服务
echo -e "${YELLOW}[1/2] 正在停止PAD服务...${NC}"
PAD_PROCESSES=$(ps aux | grep 'linuxService' | grep -v grep | awk '{print $2}')
WINE_PROCESSES=$(ps aux | grep 'wine.*linuxService.exe' | grep -v grep | awk '{print $2}')

if [ -n "$PAD_PROCESSES" ]; then
    for pid in $PAD_PROCESSES; do
        echo -e "${YELLOW}  正在终止PAD服务进程 (PID: $pid)...${NC}"
        kill -9 $pid
    done
    echo -e "${GREEN}PAD服务已停止${NC}"
elif [ -n "$WINE_PROCESSES" ]; then
    for pid in $WINE_PROCESSES; do
        echo -e "${YELLOW}  正在终止Wine PAD服务进程 (PID: $pid)...${NC}"
        kill -9 $pid
    done
    echo -e "${GREEN}Wine PAD服务已停止${NC}"
else
    echo -e "${YELLOW}未发现运行中的PAD服务进程${NC}"
fi

# 停止Redis服务
echo -e "${YELLOW}[2/2] 正在停止Redis服务...${NC}"
REDIS_PROCESSES=$(ps aux | grep 'redis-server' | grep -v grep | awk '{print $2}')

if [ -n "$REDIS_PROCESSES" ]; then
    for pid in $REDIS_PROCESSES; do
        echo -e "${YELLOW}  正在终止Redis服务进程 (PID: $pid)...${NC}"
        kill -9 $pid
    done
    echo -e "${GREEN}Redis服务已停止${NC}"
else
    echo -e "${YELLOW}未发现运行中的Redis服务进程${NC}"
fi

echo -e "${GREEN}所有WX849服务已停止!${NC}"
echo -e "${BLUE}+------------------------------------------------+${NC}" 